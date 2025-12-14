# bot.py — с согласием по закону РБ и HTTP health server
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

# === НАСТРОЙКИ (НЕ МЕНЯЙ — всё берётся из Render) ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# === УКАЖИ СВОЁ ФИО / НАЗВАНИЕ КОМПАНИИ ===
OPERATOR_NAME = "Войсковая часть"  # ← ОБЯЗАТЕЛЬНО ЗАМЕНИ!

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

def save_to_sheet(user_id, username, name, phone, msg, consent=True):
    try:
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user_id),
            username or "",
            name,
            phone,
            msg,
            "ДА" if consent else "НЕТ"
        ]
        sheet.append_row(row)
    except Exception as e:
        print(f"Ошибка записи: {e}")

# === Текст согласия ===
CONSENT_TEXT = (
    "📌 **Согласие на обработку персональных данных**\n\n"
    f"Настоящим я даю согласие оператору — **{OPERATOR_NAME}**, "
    "на обработку моих персональных данных (имя, телефон, текст сообщения) "
    "в целях приёма и обработки заявки. Срок хранения — до 30 дней. "
    "Я вправе отозвать согласие в любой момент."
)

# === Состояния ===
class ApplicationForm(StatesGroup):
    consent = State()
    name = State()
    phone = State()
    message = State()
    confirm = State()

# === Клавиатуры ===
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Оставить заявку")]],
        resize_keyboard=True
    )

def consent_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Согласен на обработку ПД")]],
        resize_keyboard=True
    )

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )

# === Обработчики ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Нажмите кнопку, чтобы оставить заявку.", reply_markup=main_menu())

@dp.message(F.text == "Оставить заявку")
async def apply_start(message: types.Message, state: FSMContext):
    await message.answer(CONSENT_TEXT, reply_markup=consent_menu(), parse_mode="Markdown")
    await state.set_state(ApplicationForm.consent)

@dp.message(ApplicationForm.consent)
async def process_consent(message: types.Message, state: FSMContext):
    if message.text != "✅ Согласен на обработку ПД":
        await message.answer("Требуется согласие на обработку ПД.", reply_markup=consent_menu())
        return
    await message.answer("Как вас зовут?", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.name)

@dp.message(F.text == "Отмена")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заявка отменена.", reply_markup=main_menu())

@dp.message(ApplicationForm.name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    await state.update_data(name=message.text)
    await message.answer("Телефон (например, +375291234567):", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.phone)

@dp.message(ApplicationForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    digits = re.sub(r"\D", "", message.text)
    if len(digits) < 10:
        await message.answer("Введите корректный телефон (минимум 10 цифр).")
        return
    await state.update_data(phone=message.text)
    await message.answer("Ваш запрос:", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.message)

@dp.message(ApplicationForm.message)
async def process_message(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    await state.update_data(message=message.text)
    data = await state.get_data()
    summary = f"Имя: {data['name']}\nТелефон: {data['phone']}\nСообщение: {data['message']}\n\nВсё верно?"
    await message.answer(summary, reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да")],
            [KeyboardButton(text="❌ Нет")]
        ],
        resize_keyboard=True
    ))
    await state.set_state(ApplicationForm.confirm)

@dp.message(ApplicationForm.confirm)
async def confirm_application(message: types.Message, state: FSMContext):
    if message.text == "❌ Нет":
        await state.clear()
        await message.answer("Начнём заново.", reply_markup=consent_menu())
        await state.set_state(ApplicationForm.consent)
        return
    if message.text != "✅ Да":
        return
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username
    save_to_sheet(user_id, username, data['name'], data['phone'], data['message'])
    await message.answer("✅ Заявка принята!", reply_markup=main_menu())
    await state.clear()

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    await message.answer("✅ Бот работает.")

# === HTTP Health Server для Render ===
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# === Запуск ===
if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
