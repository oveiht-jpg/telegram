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
    url = urllib.parse.urlparse(DATABASE_URL)
    
    pool = await aiomysql.create_pool(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        db=url.path.lstrip('/'),
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

# --- ЛОГИКА ТОПИКОВ ---

async def get_or_create_thread(user: types.User):
    """
    Находит топик в базе. Если он был удален в Telegram — 
    чистит базу и создает новый.
    """
    thread_id = await get_thread_from_db(user.id)
    
    if thread_id:
        try:
            # Проверяем "живучесть" топика отправкой статуса "печатает"
            await bot.send_chat_action(
                chat_id=ADMIN_GROUP_ID, 
                action="typing", 
                message_thread_id=thread_id
            )
        except Exception:
            # Если топик не найден (удален пользователем), удаляем его из БД
            print(f"Топик {thread_id} для {user.id} не найден. Сбрасываю...")
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            thread_id = None 

    if not thread_id:
        try:
            # Формируем название: Имя Фамилия (@nickname)
            topic_name = user.full_name
            if user.username:
                topic_name += f" (@{user.username})"
            
            # Создаем топик в админ-группе
            topic = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=topic_name)
            thread_id = topic.message_thread_id
            
            # Сохраняем новую связку в MySQL
            await save_thread_to_db(user.id, thread_id)
        except Exception as e:
            print(f"Ошибка при создании топика: {e}")
            return None
            
    return thread_id

# --- КЛАВИАТУРА ---

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Загрузить файл для печати", url="https://tiny.cc/xrcent"))
    builder.row(types.InlineKeyboardButton(text="Получить скан", callback_data="get_scan"))
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здравствуйте! Выберите нужную опцию:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: CallbackQuery):
    await callback.message.answer("Пожалуйста, ожидайте.")
    await callback.answer()

    user = callback.from_user
    display_name = html.escape(user.full_name)
    if user.username:
        display_name += f" (@{html.escape(user.username)})"

    thread_id = await get_or_create_thread(user)
    
    if thread_id:
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            message_thread_id=thread_id,
            text=f"🔔 <b>{display_name}</b> ожидает скан",
            parse_mode="HTML"
        )
    else:
        # Резервный канал (General)
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=f"🔔 <b>{display_name}</b> ожидает скан (ошибка топика)"
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
    else:
        # Если создать топик не удалось, шлем в общую ветку
        await bot.copy_message(
            chat_id=ADMIN_GROUP_ID,
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
            print(f"Не удалось ответить пользователю: {e}")

# --- ЗАПУСК ---

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
