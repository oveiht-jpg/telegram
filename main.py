import os, asyncio, html, aiomysql, urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# --- КОНФИГУРАЦИЯ ---
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
    """
    1000% надежный метод получения топика.
    Проверяет топик через попытку изменения заголовка.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    # Если ID есть в базе, проверяем его на реальность
    if thread_id:
        try:
            # Пытаемся "тронуть" топик. Если он удален, это вызовет ошибку.
            name = f"{user.full_name}"
            await bot.edit_forum_topic(ADMIN_GROUP_ID, thread_id, name=name[:120])
        except Exception:
            # Топик мертв. Удаляем из базы.
            thread_id = None
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))

    # Если топика нет или он был удален — создаем с нуля
    if not thread_id:
        try:
            topic_name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
            new_topic = await bot.create_forum_topic(ADMIN_GROUP_ID, topic_name[:120])
            thread_id = new_topic.message_thread_id
            
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'INSERT INTO threads (user_id, thread_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE thread_id=%s',
                        (user.id, thread_id, thread_id)
                    )
        except Exception as e:
            print(f"CRITICAL ERROR: Не удалось создать топик: {e}")
            return None

    return thread_id

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 Загрузить файл", url="clck.ru/3ThXvR"))
    kb.row(types.InlineKeyboardButton(text="📄 Получить скан", callback_data="get_scan"))
    
    await m.answer(
        f"Здравствуйте, {m.from_user.first_name}! 👋\nПожалуйста, выберите опцию:",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(cb: types.CallbackQuery):
    await cb.answer()
    tid = await get_or_create_thread(cb.from_user)
    
    if tid:
        # Формируем красивое имя: Имя Фамилия (@username)
        user = cb.from_user
        display_name = html.escape(user.full_name)
        if user.username:
            display_name += f" (@{html.escape(user.username)})"
            
        try:
            await bot.send_message(
                ADMIN_GROUP_ID, 
                f"🔔 <b>{display_name}</b> ожидает скан...",
                message_thread_id=tid,
                parse_mode="HTML"
            )
            await cb.message.answer("✅ Запрос отправлен.")
        except TelegramBadRequest:
            # Если топик внезапно "отвалился" в момент отправки
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            return await process_scan(cb)

@dp.message(F.chat.type == "private")
async def to_admin_forward(m: types.Message):
    if m.text == "/start": return
    
    tid = await get_or_create_thread(m.from_user)
    if tid:
        try:
            await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=tid)
        except TelegramBadRequest:
            # Если тема не найдена прямо в момент отправки
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (m.from_user.id,))
            new_tid = await get_or_create_thread(m.from_user)
            await bot.copy_message(ADMIN_GROUP_ID, m.chat.id, m.message_id, message_thread_id=new_tid)

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def from_admin_reply(m: types.Message):
    # Игнорируем General (thread_id=None или 1 в некоторых случаях)
    if not m.message_thread_id or m.message_thread_id == 1:
        return
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (m.message_thread_id,))
            res = await cur.fetchone()
            if res:
                try:
                    await bot.copy_message(res[0], ADMIN_GROUP_ID, m.message_id)
                except Exception:
                    pass

# --- ЗАПУСК ---
async def main():
    await init_db()
    # Сбрасываем очередь сообщений, чтобы не захлебнуться старыми ошибками
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
