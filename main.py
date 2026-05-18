import os, asyncio, html, aiomysql, urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# Конфигурация
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

async def get_valid_thread(user: types.User):
    """Проверяет топик на реальное существование."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    if thread_id:
        try:
            # Если топик удален, этот вызов выдаст TelegramBadRequest
            await bot.get_chat(chat_id=ADMIN_GROUP_ID) 
            await bot.send_chat_action(chat_id=ADMIN_GROUP_ID, action="typing", message_thread_id=thread_id)
        except Exception:
            # Если хоть что-то пошло не так — забываем этот ID
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            thread_id = None

    if not thread_id:
        try:
            topic = await bot.create_forum_topic(ADMIN_GROUP_ID, f"{user.full_name}")
            thread_id = topic.message_thread_id
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('INSERT INTO threads (user_id, thread_id) VALUES (%s, %s)', (user.id, thread_id))
        except Exception as e:
            print(f"Критическая ошибка создания темы: {e}")
            return None
    return thread_id

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 Загрузить файл", url="https://tiny.cc/xrcent"))
    kb.row(types.InlineKeyboardButton(text="📄 Получить скан", callback_data="get_scan"))
    await m.answer(f"Привет, {m.from_user.first_name}!", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "get_scan")
async def process_scan(cb: types.CallbackQuery): # Название из вашего лога
    await cb.answer()
    tid = await get_valid_thread(cb.from_user)
    if tid:
        try:
            await bot.send_message(ADMIN_GROUP_ID, f"🔔 Скан от {html.escape(cb.from_user.full_name)}", message_thread_id=tid)
            await cb.message.answer("Запрос отправлен.")
        except Exception:
            await cb.message.answer("Ошибка. Попробуйте еще раз.")

@dp.message(F.chat.type == "private")
async def to_admin(m: types.Message):
    if m.text == "/start": return
    tid = await get_valid_thread(m.from_user)
    if tid:
        try:
            await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=tid)
        except:
            pass

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def from_admin(m: types.Message):
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
