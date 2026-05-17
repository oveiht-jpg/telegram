import os
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
DB_PATH = "/app/data/bot_database.db" # Путь внутри Volume

def init_db():
    # Создаем папку, если её нет (на случай локального запуска)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS threads 
        (user_id INTEGER PRIMARY KEY, thread_id INTEGER)
    ''')
    conn.commit()
    conn.close()

def get_thread_from_db(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT thread_id FROM threads WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def save_thread_to_db(user_id, thread_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO threads (user_id, thread_id) VALUES (?, ?)', (user_id, thread_id))
    conn.commit()
    conn.close()

def get_user_id_by_thread(thread_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM threads WHERE thread_id = ?', (thread_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None
# ------------------------------

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Загрузить файл для печати", url="https://tiny.cc/xrcent"))
    builder.row(types.InlineKeyboardButton(text="Получить скан", callback_data="get_scan"))
    return builder.as_markup()

async def get_or_create_thread(user: types.User):
    # Пытаемся взять ID ветки из базы
    thread_id = get_thread_from_db(user.id)
    
    if not thread_id:
        try:
            topic = await bot.create_forum_topic(
                chat_id=ADMIN_GROUP_ID, 
                name=f"{user.full_name} [{user.id}]"
            )
            thread_id = topic.message_thread_id
            # Сохраняем в базу навсегда
            save_thread_to_db(user.id, thread_id)
        except Exception as e:
            print(f"Ошибка создания темы: {e}")
            return None
    return thread_id

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    sent_message = await message.answer(
        "Здравствуйте! Выберите нужную опцию:",
        reply_markup=get_main_keyboard()
    )
    try:
        await bot.pin_chat_message(chat_id=message.chat.id, message_id=sent_message.message_id, disable_notification=True)
    except: pass

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: CallbackQuery):
    await callback.message.answer("Пожалуйста, ожидайте.")
    await callback.answer()
    thread_id = await get_or_create_thread(callback.from_user)
    if thread_id:
        await bot.send_message(chat_id=ADMIN_GROUP_ID, message_thread_id=thread_id, text="🔔 Выбрана опция: Получить скан")

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    if message.text == "/start": return
    thread_id = await get_or_create_thread(message.from_user)
    if thread_id:
        await bot.copy_message(chat_id=ADMIN_GROUP_ID, message_thread_id=thread_id, from_chat_id=message.chat.id, message_id=message.message_id)

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def forward_to_user(message: types.Message):
    if not message.message_thread_id: return
    user_id = get_user_id_by_thread(message.message_thread_id)
    if user_id:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=ADMIN_GROUP_ID, message_id=message.message_id)
        except: pass

async def main():
    init_db() # Инициализируем базу при запуске
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
