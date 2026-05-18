import os
import asyncio
import html
import aiomysql
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройки из Railway
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

async def get_valid_thread_id(user: types.User):
    """
    Гарантирует получение ID РАБОЧЕГО топика. 
    Если топик удален — создает новый.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    # ПРОВЕРКА НА ВШИВОСТЬ: жив ли топик?
    if thread_id:
        try:
            # Пытаемся отправить имитацию набора текста именно в этот топик
            await bot.send_chat_action(chat_id=ADMIN_GROUP_ID, action="typing", message_thread_id=thread_id)
        except Exception:
            # Если возникла любая ошибка (топик удален/не найден)
            thread_id = None
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))

    # Если топика нет или он оказался "битым" — создаем новый
    if not thread_id:
        try:
            name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
            topic = await bot.create_forum_topic(ADMIN_GROUP_ID, name)
            thread_id = topic.message_thread_id
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'INSERT INTO threads (user_id, thread_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE thread_id=%s',
                        (user.id, thread_id, thread_id)
                    )
        except Exception as e:
            print(f"Ошибка создания топика: {e}")
            return None
    
    return thread_id

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 Загрузить файл", url="https://tiny.cc/xrcent"))
    kb.row(types.InlineKeyboardButton(text="📄 Получить скан", callback_data="get_scan"))
    
    await m.answer(
        f"Здравствуйте, {m.from_user.first_name}! 👋\nНапишите сообщение администратору или выберите опцию:",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(cb: types.CallbackQuery):
    await cb.answer()
    tid = await get_valid_thread_id(cb.from_user)
    if tid:
        await bot.send_message(
            ADMIN_GROUP_ID, 
            f"🔔 Пользователь <b>{html.escape(cb.from_user.full_name)}</b> запрашивает скан.",
            message_thread_id=tid,
            parse_mode="HTML"
        )
        await cb.message.answer("Запрос отправлен.")

@dp.message(F.chat.type == "private")
async def to_admin(m: types.Message):
    if m.text == "/start": return
    tid = await get_valid_thread_id(m.from_user)
    if tid:
        # Принудительно передаем thread_id. Если функция выше отработала верно, 
        # здесь будет только живой ID.
        await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=tid)

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def from_admin(m: types.Message):
    # Игнорируем всё, что пишут в General (где нет thread_id)
    if not m.message_thread_id: return
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (m.message_thread_id,))
            res = await cur.fetchone()
            if res:
                try:
                    await bot.copy_message(res[0], ADMIN_GROUP_ID, m.message_id)
                except:
                    pass

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
