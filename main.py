import os
import asyncio
import html
import aiomysql
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
pool = None

async def init_db():
    global pool
    url = urllib.parse.urlparse(DATABASE_URL)
    pool = await aiomysql.create_pool(
        host=url.hostname, port=url.port or 3306,
        user=url.username, password=url.password,
        db=url.path.lstrip('/'), autocommit=True
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('CREATE TABLE IF NOT EXISTS threads (user_id BIGINT PRIMARY KEY, thread_id BIGINT)')

async def get_or_create_thread(user: types.User):
    # 1. Проверяем БД
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    # 2. Если ID есть, проверим его валидность
    if thread_id:
        try:
            await bot.send_chat_action(chat_id=ADMIN_GROUP_ID, action="typing", message_thread_id=thread_id)
            return thread_id
        except Exception as e:
            print(f"Старый топик {thread_id} не работает: {e}. Создаю новый...")
            thread_id = None

    # 3. Создаем новый топик
    if not thread_id:
        topic_name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
        try:
            print(f"Попытка создать топик в чате {ADMIN_GROUP_ID}...")
            topic = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=topic_name)
            thread_id = topic.message_thread_id
            
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('INSERT INTO threads (user_id, thread_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE thread_id=%s', (user.id, thread_id, thread_id))
            print(f"Успешно создан топик: {thread_id}")
            return thread_id
        except Exception as e:
            print(f"!!! ОШИБКА TELEGRAM: {e}")
            return None

@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("Бот готов к работе. Напишите что-нибудь.")

@dp.message(F.chat.type == "private")
async def handle_private(m: types.Message):
    tid = await get_or_create_thread(m.from_user)
    if tid:
        await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=tid)
    else:
        await m.answer("Технические работы в панели администратора. Попробуйте позже.")

# Узнаем ID группы, если бот в ней что-то видит
@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def handle_admin(m: types.Message):
    print(f"Сообщение в админ-группе. ID чата: {m.chat.id}, ID топика: {m.message_thread_id}")

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
