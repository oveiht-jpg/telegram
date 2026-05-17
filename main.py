import os
import asyncio
import urllib.parse
import html
import aiomysql
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()

pool = None

# --- РАБОТА С БАЗОЙ ДАННЫХ (MYSQL) ---

async def init_db():
    global pool
    # Безопасный разбор URL для подключения к базе
    url = urllib.parse.urlparse(DATABASE_URL)
    
    pool = await aiomysql.create_pool(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        db=url.path.lstrip('/'),
        autocommit=True
    )
    
    # Создаем таблицу для хранения связей Юзер <-> Топик
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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Получить скан", callback_data="get_scan"))
    return builder.as_markup()

async def get_or_create_thread(user: types.User):
    """Находит или создает топик с форматом: Имя Фамилия (@nickname)"""
    thread_id = await get_thread_from_db(user.id)
    
    if not thread_id:
        try:
            # Формируем красивое название топика
            topic_name = user.full_name
            if user.username:
                topic_name += f" (@{user.username})"
            
            # Создаем топик в админ-группе
            topic = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=topic_name)
            thread_id = topic.message_thread_id
            
            # Сохраняем в MySQL
            await save_thread_to_db(user.id, thread_id)
        except Exception as e:
            print(f"Ошибка создания топика: {e}")
            return None
    return thread_id

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здравствуйте! Нажмите на кнопку, чтобы запросить скан:»,
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: CallbackQuery):
    await callback.message.answer("Пожалуйста, ожидайте.")
    await callback.answer()

    user = callback.from_user
    # Формируем имя для уведомления: Имя Фамилия (@никнейм)
    display_name = html.escape(user.full_name)
    if user.username:
        display_name += f" (@{html.escape(user.username)})"

    thread_id = await get_or_create_thread(user)
    if thread_id:
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            message_thread_id=thread_id,
            text=f"<b>{display_name}</b> ожидает скан…",
            parse_mode="HTML"
        )

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    """Пересылка сообщений от пользователя админам"""
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
    """Ответ админа из топика пользователю в ЛС"""
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
            print(f"Ошибка пересылки: {e}")

# --- ЗАПУСК ---

async def main():
    await init_db()
    # Удаляем вебхуки и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
