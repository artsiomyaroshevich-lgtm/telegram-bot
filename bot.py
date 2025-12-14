# bot.py — Google Таблица версия
import asyncio
import logging
import json
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import gspread
from google.oauth2.service_account import Credentials

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = "1xTCcGRW-jsolnONiv9gptpSTTRtexHbJTlHoQLotFD4"  # ← ЗАМЕНИ ЭТУ СТРОКУ!

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === GOOGLE SHEETS ===
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

# === СОСТОЯНИЯ ===
class ApplicationForm(StatesGroup):
    name = State()
    phone = State()
    message = State()

# === СОХРАНЕНИЕ В ТАБЛИЦУ ===
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

# === КОМАНДЫ ===
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

# === АДМИНКА ===
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Доступ запрещён.")
        return
    await message.answer("✅ Бот работает. Все заявки — в Google Таблице.")

# === ЗАПУСК ===
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
