import os, asyncio, html, aiomysql, urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
pool = None

# --- РАБОТА С БАЗОЙ ---
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
    """Находит живой топик или создает новый, если старый удален."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    if thread_id:
        try:
            # Проверка: жив ли топик в Telegram?
            await bot.send_chat_action(ADMIN_GROUP_ID, "typing", message_thread_id=thread_id)
        except Exception:
            # Если топик удален вручную, стираем его из базы
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            thread_id = None

    if not thread_id:
        try:
            name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
            topic = await bot.create_forum_topic(ADMIN_GROUP_ID, name)
            thread_id = topic.message_thread_id
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('INSERT INTO threads (user_id, thread_id) VALUES (%s, %s)', (user.id, thread_id))
        except Exception as e:
            print(f"ОШИБКА СОЗДАНИЯ ТОПИКА: {e}")
            return None
    return thread_id

# --- ОБРАБОТЧИКИ (ТЕКСТЫ ТУТ) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # 1. Текст кнопок
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📥 Загрузить файл", url="https://tiny.cc/xrcent"))
    builder.row(types.InlineKeyboardButton(text="📄 Получить скан", callback_data="get_scan"))
    
    # 2. Приветственный текст
    welcome_text = (
        f"Здравствуйте, <b>{message.from_user.first_name}</b>! 👋\n\n"
        "Я — бот поддержки. Вы можете отправить мне сообщение или файл, "
        "и администратор сразу получит их.\n\n"
        "Либо воспользуйтесь кнопками ниже:"
    )
    await message.answer(welcome_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "get_scan")
async def process_scan_button(callback: types.CallbackQuery):
    await callback.answer() # Убирает индикатор загрузки на кнопке
    
    thread_id = await get_valid_thread(callback.from_user)
    if thread_id:
        # Текст, который увидит админ в группе
        admin_alert = f"🔔 Пользователь <b>{html.escape(callback.from_user.full_name)}</b> просит прислать скан."
        await bot.send_message(ADMIN_GROUP_ID, admin_alert, message_thread_id=thread_id, parse_mode="HTML")
        
        # Текст подтверждения для пользователя
        await callback.message.answer("✅ Запрос отправлен. Администратор скоро пришлет скан в этот чат.")
    else:
        await callback.message.answer("❌ Ошибка связи с администратором. Попробуйте написать сообщение вручную.")

@dp.message(F.chat.type == "private")
async def to_admin_forward(message: types.Message):
    """Пересылка любого сообщения от пользователя к админу."""
    if message.text == "/start": return
    
    thread_id = await get_valid_thread(message.from_user)
    if thread_id:
        await bot.copy_message(ADMIN_GROUP_ID, message.chat.id, message.message_id, message_thread_id=thread_id)

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def from_admin_reply(message: types.Message):
    """Ответ админа из топика летит пользователю."""
    if not message.message_thread_id: return
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (message.message_thread_id,))
            res = await cur.fetchone()
            if res:
                try:
                    await bot.copy_message(res[0], ADMIN_GROUP_ID, message.message_id)
                except Exception:
                    pass

# --- ЗАПУСК ---
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
