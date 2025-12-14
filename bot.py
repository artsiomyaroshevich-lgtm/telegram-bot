# bot.py — Telegram-бот + фиктивный HTTP-сервер для Render
import asyncio
import logging
import json
import os
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import gspread
from google.oauth2.service_account import Credentials

# === Получаем переменные из окружения ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# === Инициализация бота ===
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

# === FSM состояния ===
class ApplicationForm(StatesGroup):
    name = State()
    phone = State()
    message = State()

# === Обработчики ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("👋 Привет! Пожалуйста, оставьте заявку.\nКак вас зовут?")
    await state.set_state(ApplicationForm.name)

@dp.message(ApplicationForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("📞 Укажите ваш телефон для связи:")
    await state.set_state(ApplicationForm.phone)

@dp.message(ApplicationForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("💬 Опишите ваш запрос:")
    await state.set_state(ApplicationForm.message)

@dp.message(ApplicationForm.message)
async def process_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data["name"]
    phone = data["phone"]
    user_msg = message.text

    user_id = message.from_user.id
    username = message.from_user.username

    save_to_sheet(user_id, username, name, phone, user_msg)

    await message.answer("✅ Спасибо! Ваша заявка принята. Мы свяжемся с вами в ближайшее время.")
    await state.clear()

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Доступ запрещён.")
        return
    await message.answer("✅ Бот работает. Все заявки — в Google Таблице.")

# === Фиктивный HTTP-сервер для Render ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# === Запуск ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем HTTP-сервер в фоновом потоке
    Thread(target=run_health_server, daemon=True).start()
    # Запускаем бота
    asyncio.run(main())
