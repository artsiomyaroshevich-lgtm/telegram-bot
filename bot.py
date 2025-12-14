
# bot.py — улучшенный UI с кнопками и валидацией
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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

import gspread
from google.oauth2.service_account import Credentials

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === Google Sheets ===
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

def save_to_sheet(user_id, username, name, phone, msg):
    try:
        sheet = get_sheet()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user_id),
            username or "",
            name,
            phone,
            msg
        ]
        sheet.append_row(row)
    except Exception as e:
        print(f"Ошибка записи в таблицу: {e}")

# === Состояния ===
class ApplicationForm(StatesGroup):
    name = State()
    phone = State()
    message = State()
    confirm = State()

# === Клавиатуры ===
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Оставить заявку")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )

# === Команды ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать! Нажмите кнопку ниже, чтобы оставить заявку.",
        reply_markup=main_menu()
    )

@dp.message(F.text == "Оставить заявку")
async def apply_start(message: types.Message, state: FSMContext):
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
    await message.answer("Укажите ваш телефон для связи (например, +79991234567):", reply_markup=cancel_menu())
    await state.set_state(ApplicationForm.phone)

@dp.message(ApplicationForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return

    # Простая валидация: оставляем только цифры
    digits = re.sub(r"\D", "", message.text)
    if len(digits) < 10:
        await message.answer("📞 Пожалуйста, введите корректный телефон (минимум 10 цифр).")
        return

    await state.update_data(phone=message.text)
    await message.answer("Опишите ваш запрос:", reply_markup=cancel_only())
    await state.set_state(ApplicationForm.message)

def cancel_only():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )

@dp.message(ApplicationForm.message)
async def process_message(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return

    await state.update_data(message=message.text)
    data = await state.get_data()

    # Показываем сводку
    summary = (
        "Пожалуйста, подтвердите данные:\n\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Сообщение: {data['message']}\n\n"
        "Всё верно?"
    )
    await message.answer(summary, reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, всё верно")],
            [KeyboardButton(text="❌ Нет, начать заново")]
        ],
        resize_keyboard=True
    ))
    await state.set_state(ApplicationForm.confirm)

@dp.message(ApplicationForm.confirm)
async def confirm_application(message: types.Message, state: FSMContext):
    if message.text == "❌ Нет, начать заново":
        await state.clear()
        await message.answer("Начнём заново. Как вас зовут?", reply_markup=cancel_menu())
        await state.set_state(ApplicationForm.name)
        return

    if message.text != "✅ Да, всё верно":
        await message.answer("Пожалуйста, выберите вариант ниже.")
        return

    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username

    save_to_sheet(user_id, username, data['name'], data['phone'], data['message'])

    await message.answer(
        "✅ Спасибо! Ваша заявка принята. Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_menu()
    )
    await state.clear()

# === Админка ===
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Доступ запрещён.")
        return
    await message.answer("✅ Бот работает. Все заявки — в Google Таблице.")

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
