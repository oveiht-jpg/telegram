import os, asyncio, aiomysql, urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# Конфигурация из Railway
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
            # Создаем таблицу заново
            await cur.execute('CREATE TABLE IF NOT EXISTS threads (user_id BIGINT PRIMARY KEY, thread_id BIGINT)')

async def get_thread(user: types.User):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            
            if res:
                # Пытаемся проверить, живой ли топик
                try:
                    await bot.send_chat_action(ADMIN_GROUP_ID, "typing", message_thread_id=res[0])
                    return res[0]
                except:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            
            # Если топика нет, создаем новый
            try:
                topic = await bot.create_forum_topic(ADMIN_GROUP_ID, f"User: {user.full_name}")
                new_id = topic.message_thread_id
                await cur.execute('INSERT INTO threads (user_id, thread_id) VALUES (%s, %s)', (user.id, new_id))
                return new_id
            except Exception as e:
                print(f"КРИТИЧЕСКАЯ ОШИБКА: Не могу создать топик! Причина: {e}")
                return None

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer("Напишите что-нибудь, чтобы создать чат с поддержкой.")

@dp.message(F.chat.type == "private")
async def forward_to_admin(m: types.Message):
    tid = await get_thread(m.from_user)
    if tid:
        await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=tid)
    else:
        await m.answer("Ошибка: бот не может создать тему в админ-группе. Проверьте права бота.")

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def forward_to_user(m: types.Message):
    if not m.message_thread_id: return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (m.message_thread_id,))
            res = await cur.fetchone()
            if res:
                try: await bot.copy_message(res[0], ADMIN_GROUP_ID, m.message_id)
                except: pass

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
