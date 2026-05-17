import os
import asyncio
import aiomysql
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery

# Настройки из Railway
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()

pool = None

# --- РАБОТА С MYSQL ---
async def init_db():
    global pool
    # Разбор строки подключения mysql://user:pass@host:port/db
    user_pass, host_port_db = DATABASE_URL.split('//')[1].split('@')
    user, password = user_pass.split(':')
    host_port, db = host_port_db.split('/')
    host, port = host_port.split(':')

    pool = await aiomysql.create_pool(
        host=host,
        port=int(port),
        user=user,
        password=password,
        db=db,
        autocommit=True
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('''
                CREATE TABLE IF NOT EXISTS threads 
                (user_id BIGINT PRIMARY KEY, thread_id BIGINT)
            ''')

async def get_thread_from_db(user_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user_id,))
            result = await cur.fetchone()
            return result[0] if result else None

async def save_thread_to_db(user_id, thread_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'INSERT INTO threads (user_id, thread_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE thread_id=%s',
                (user_id, thread_id, thread_id)
            )

async def get_user_id_by_thread(thread_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (thread_id,))
            result = await cur.fetchone()
            return result[0] if result else None
# ------------------------------

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Загрузить файл для печати", url="https://tiny.cc/xrcent"))
    builder.row(types.InlineKeyboardButton(text="Получить скан", callback_data="get_scan"))
    return builder.as_markup()

async def get_or_create_thread(user: types.User):
    thread_id = await get_thread_from_db(user.id)
    if not thread_id:
        try:
            topic = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=f"{user.full_name} [{user.id}]")
            thread_id = topic.message_thread_id
            await save_thread_to_db(user.id, thread_id)
        except Exception as e:
            print(f"Ошибка создания темы: {e}")
            return None
    return thread_id

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Просто отправляем сообщение с кнопками без закрепления
    await message.answer(
        "Здравствуйте! Выберите нужную опцию:", 
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: CallbackQuery):
    await callback.message.answer("Пожалуйста, ожидайте.")
    await callback.answer()
    
    thread_id = await get_or_create_thread(callback.from_user)
    if thread_id:
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID, 
            message_thread_id=thread_id, 
            text="🔔 Пользователь выбрал опцию: **Получить скан**"
        )

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    if message.text == "/start": 
        return
        
    thread_id = await get_or_create_thread(message.from_user)
    if thread_id:
        await bot.copy_message(
            chat_id=ADMIN_GROUP_ID, 
            message_thread_id=thread_id, 
            from_chat_id=message.chat.id, 
            message_id=message.message_id
        )

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def forward_to_user(message: types.Message):
    if not message.message_thread_id: 
        return
        
    user_id = await get_user_id_by_thread(message.message_thread_id)
    if user_id:
        try:
            await bot.copy_message(
                chat_id=user_id, 
                from_chat_id=ADMIN_GROUP_ID, 
                message_id=message.message_id
            )
        except Exception as e:
            print(f"Ошибка пересылки пользователю: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
