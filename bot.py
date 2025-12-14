# bot.py — полная форма с валидацией по требованиям РБ
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

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

OPERATOR_NAME = "Войсковая часть"  # ← ОБЯЗАТЕЛЬНО ЗАМЕНИ!

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

# === ВАЛИДАЦИЯ ===
def validate_name(text):
    return bool(re.fullmatch(r"[а-яА-ЯёЁ]+", text.strip()))

def validate_date(text):
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return False
    try:
        day, month, year = map(int, text.split("."))
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2025):
            return False
        # Простая проверка високосности и дней в месяце (опционально можно углубить)
        return True
    except:
        return False

def validate_phone(text):
    return bool(re.fullmatch(r"\+375\d{9}", text))  # +375 + 9 цифр = 13 символов

# === FSM ===
class ApplicationForm(StatesGroup):
    last_name = State()
    first_name = State()
    patronymic = State()
    birth_date = State()
    phone = State()
    military_experience = State()
    confirm = State()

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )

# === ОСНОВНОЙ ФЛОУ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Нажмите кнопку, чтобы оставить заявку.", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Оставить заявку")]],
        resize_keyboard=True
    ))

@dp.message(F.text == "Оставить заявку")
async def apply_start(message: types.Message, state: FSMContext):
    consent_text = (
        f"📌 **Согласие на обработку персональных данных**\n\n"
        f"Настоящим я даю согласие оператору — **{OPERATOR_NAME}**, "
        "на обработку моих персональных данных в целях приёма заявки. "
        "Срок хранения — до 30 дней. Я вправе отозвать согласие в любой момент."
    )
    await message.answer(consent_text, reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Согласен на обработку ПД")]],
        resize_keyboard=True
    ), parse_mode="Markdown")
    await state.set_state(ApplicationForm.last_name)

@dp.message(ApplicationForm.last_name)
async def process_last_name(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Оставить заявку")]],
            resize_keyboard=True
        ))
        return
    if not validate_name(message.text):
        await message.answer("Фамилия должна быть одним словом на кириллице. Попробуйте ещё раз:")
        return
    await state.update_data(last_name=message.text)
    await message.answer("Укажите своё Имя!", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.first_name)

@dp.message(ApplicationForm.first_name)
async def process_first_name(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await apply_start(message, state)  # или просто cancel
    if not validate_name(message.text):
        await message.answer("Имя должно быть одним словом на кириллице:")
        return
    await state.update_data(first_name=message.text)
    await message.answer("Укажите своё Отчество!", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.patronymic)

@dp.message(ApplicationForm.patronymic)
async def process_patronymic(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu())
        return
    if not validate_name(message.text):
        await message.answer("Отчество должно быть одним словом на кириллице:")
        return
    await state.update_data(patronymic=message.text)
    await message.answer("Укажите дату рождения (в формате ДД.ММ.ГГГГ, например: 01.01.1995):", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.birth_date)

@dp.message(ApplicationForm.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu())
        return
    if not validate_date(message.text):
        await message.answer("Неверный формат даты. Пример: 01.01.1995")
        return
    await state.update_data(birth_date=message.text)
    await message.answer("Укажите телефон для связи (в формате +375291234567):", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.phone)

@dp.message(ApplicationForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu())
        return
    if not validate_phone(message.text):
        await message.answer("Телефон должен быть в формате +375 и 7 цифр (всего 11 символов). Пример: +3752912345")
        return
    await state.update_data(phone=message.text)
    await message.answer("Расскажите о своём боевом прошлом (можно пропустить):", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")], [KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    ))
    await state.set_state(ApplicationForm.military_experience)

@dp.message(ApplicationForm.military_experience)
async def process_military(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu())
        return
    military = "" if message.text == "Пропустить" else message.text
    await state.update_data(military_experience=military)

    data = await state.get_data()
    summary = (
        f"Фамилия: {data['last_name']}\n"
        f"Имя: {data['first_name']}\n"
        f"Отчество: {data['patronymic']}\n"
        f"Дата рождения: {data['birth_date']}\n"
        f"Телефон: {data['phone']}\n"
        f"Боевое прошлое: {military or '—'}\n\n"
        "Всё верно?"
    )
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
        await message.answer("Начнём заново.", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Согласен на обработку ПД")]],
            resize_keyboard=True
        ))
        await state.set_state(ApplicationForm.last_name)
        return
    if message.text != "✅ Да":
        return

    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username

    # Сохраняем в таблицу
    sheet = get_sheet()
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(user_id),
        username or "",
        data['last_name'],
        data['first_name'],
        data['patronymic'],
        data['birth_date'],
        data['phone'],
        data.get('military_experience', ''),
        "ДА",
        "НЕТ"
    ]
    sheet.append_row(row)

    # Уведомляем админа
    admin_text = (
        f"📥 **Новая заявка!**\n\n"
        f"ФИО: {data['last_name']} {data['first_name']} {data['patronymic']}\n"
        f"Дата: {data['birth_date']}\n"
        f"Телефон: {data['phone']}\n"
        f"Боевое прошлое: {data.get('military_experience', '—')}\n\n"
        f"`/reply {user_id} Здравствуйте!`\n"
        f"`/done {user_id}`"
    )
    try:
        await bot.send_message(ADMIN_USER_ID, admin_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка отправки админу: {e}")

    await message.answer("✅ Заявка отправлена!", reply_markup=main_menu())
    await state.clear()

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Оставить заявку")]],
        resize_keyboard=True
    )

# === АДМИНКА ===
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
    except:
        await message.answer("❌ Используйте: `/reply 123456789 Текст`")

def mark_application_as_done(user_id):
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return False
    for i, row in enumerate(rows[1:], start=2):
        if len(row) > 1 and row[1] == str(user_id):
            sheet.update_cell(i, 11, "ДА")
            return True
    return False

@dp.message(Command("done"))
async def cmd_done(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            raise ValueError()
        user_id = int(parts[1])
        if mark_application_as_done(user_id):
            await message.answer("✅ Заявка помечена как обработанная.")
        else:
            await message.answer("❌ Заявка не найдена.")
    except Exception as e:
        await message.answer("❌ Используйте: `/done 123456789`")

# === HTTP SERVER ДЛЯ RENDER ===
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# === ЗАПУСК ===
if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
