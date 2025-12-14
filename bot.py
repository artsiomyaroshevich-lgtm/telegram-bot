# bot.py — с админкой для управления заявками
import asyncio
import logging
import json
import os
import re
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import gspread
from google.oauth2.service_account import Credentials

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

OPERATOR_NAME = "Войсковая часть"  # ← ЗАМЕНИ НА СВОЁ!

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def save_application(user_id, username, name, phone, msg):
    sheet = get_sheet()
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(user_id),
        username or "",
        name,
        phone,
        msg,
        "ДА",
        "НЕТ"  # обработано = НЕТ
    ]
    sheet.append_row(row)

def get_unprocessed_applications():
    sheet = get_sheet()
    data = sheet.get_all_values()
    if len(data) < 2:
        return []
    unprocessed = []
    for row in data[1:]:  # пропускаем заголовок
        if len(row) < 8 or row[7] != "ДА":  # колонка H = "Обработано"
            unprocessed.append(row)
    return unprocessed

def mark_as_processed(user_id):
    sheet = get_sheet()
    data = sheet.get_all_values()
    for i, row in enumerate(data[1:], start=2):
        if len(row) > 1 and row[1] == str(user_id):
            sheet.update_cell(i, 8, "ДА")  # колонка H
            return True
    return False

# === UI ===
class ApplicationForm(StatesGroup):
    consent = State()
    name = State()
    phone = State()
    message = State()
    confirm = State()

def main_menu():
    return ReplyMarkup([[KeyboardButton(text="Оставить заявку")]])

def ReplyMarkup(keyboard):
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# === Обработчики (сокращённые для краткости — оставь как в предыдущей версии) ===
CONSENT_TEXT = (
    "📌 **Согласие на обработку персональных данных**\n\n"
    f"Настоящим я даю согласие оператору — **{OPERATOR_NAME}**, "
    "на обработку моих персональных данных (имя, телефон, текст сообщения) "
    "в целях приёма и обработки заявки. Срок хранения — до 30 дней. "
    "Я вправе отозвать согласие в любой момент."
)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Нажмите кнопку, чтобы оставить заявку.", reply_markup=main_menu())

@dp.message(F.text == "Оставить заявку")
async def apply_start(message: types.Message, state: FSMContext):
    await message.answer(CONSENT_TEXT, reply_markup=ReplyMarkup([[KeyboardButton(text="✅ Согласен на обработку ПД")]]), parse_mode="Markdown")
    await state.set_state(ApplicationForm.consent)

@dp.message(ApplicationForm.consent)
async def process_consent(message: types.Message, state: FSMContext):
    if message.text != "✅ Согласен на обработку ПД":
        await message.answer("Требуется согласие.", reply_markup=ReplyMarkup([[KeyboardButton(text="✅ Согласен на обработку ПД")]]))
        return
    await message.answer("Как вас зовут?", reply_markup=ReplyMarkup([[KeyboardButton(text="Отмена")]]))
    await state.set_state(ApplicationForm.name)

@dp.message(F.text == "Отмена")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(ApplicationForm.name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await cancel_handler(message, state)
    await state.update_data(name=message.text)
    await message.answer("Телефон (например, +375291234567):", reply_markup=ReplyMarkup([[KeyboardButton(text="Отмена")]]))
    await state.set_state(ApplicationForm.phone)

@dp.message(ApplicationForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await cancel_handler(message, state)
    digits = re.sub(r"\D", "", message.text)
    if len(digits) < 10:
        await message.answer("Введите корректный телефон.")
        return
    await state.update_data(phone=message.text)
    await message.answer("Ваш запрос:", reply_markup=ReplyMarkup([[KeyboardButton(text="Отмена")]]))
    await state.set_state(ApplicationForm.message)

@dp.message(ApplicationForm.message)
async def process_message(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await cancel_handler(message, state)
    await state.update_data(message=message.text)
    data = await state.get_data()
    summary = f"Имя: {data['name']}\nТелефон: {data['phone']}\nСообщение: {data['message']}\n\nВсё верно?"
    kb = ReplyMarkup([
        [KeyboardButton(text="✅ Да")],
        [KeyboardButton(text="❌ Нет")]
    ])
    await message.answer(summary, reply_markup=kb)
    await state.set_state(ApplicationForm.confirm)

@dp.message(ApplicationForm.confirm)
async def confirm_application(message: types.Message, state: FSMContext):
    if message.text == "❌ Нет":
        await state.clear()
        await message.answer("Начнём заново.", reply_markup=ReplyMarkup([[KeyboardButton(text="✅ Согласен на обработку ПД")]]))
        await state.set_state(ApplicationForm.consent)
        return
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username
    save_application(user_id, username, data['name'], data['phone'], data['message'])
    await message.answer("✅ Заявка принята!", reply_markup=main_menu())
    await state.clear()

# === АДМИНКА ===
@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    apps = get_unprocessed_applications()
    if not apps:
        await message.answer("📭 Нет непрочитанных заявок.")
        return
    # Берём первую (самую старую)
    app = apps[0]
    text = (
        f"📥 Новая заявка:\n\n"
        f"ID: `{app[1]}`\n"
        f"Имя: {app[3]}\n"
        f"Телефон: {app[4]}\n"
        f"Сообщение: {app[5]}\n\n"
        f"Команды:\n"
        f"`/reply {app[1]} Привет!`\n"
        f"`/done {app[1]}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("reply"))
async def cmd_reply(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    try:
        parts = message.text.split(" ", 2)
        if len(parts) < 3:
            raise ValueError()
        user_id = int(parts[1])
        reply_text = parts[2]
        await bot.send_message(user_id, f"📬 Ответ от поддержки:\n\n{reply_text}")
        await message.answer("✅ Ответ отправлен!")
    except Exception as e:
        await message.answer("❌ Ошибка. Используйте: `/reply 123456789 Текст ответа`", parse_mode="Markdown")

@dp.message(Command("done"))
async def cmd_done(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            raise ValueError()
        user_id = int(parts[1])
        if mark_as_processed(user_id):
            await message.answer("✅ Заявка помечена как обработанная.")
        else:
            await message.answer("❌ Заявка не найдена.")
    except:
        await message.answer("❌ Используйте: `/done 123456789`")

# === HTTP Server для Render ===
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
