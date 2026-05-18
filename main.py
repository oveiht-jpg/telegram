import os
import asyncio
import html
import aiomysql
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# --- КОНФИГУРАЦИЯ (Railway автоматически подставит эти переменные) ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
pool = None

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
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
            # Создаем таблицу, если её нет
            await cur.execute('''
                CREATE TABLE IF NOT EXISTS threads (
                    user_id BIGINT PRIMARY KEY, 
                    thread_id BIGINT
                )
            ''')

# --- ЛОГИКА ПРОВЕРКИ И СОЗДАНИЯ ТОПИКА ---
async def get_valid_thread(user: types.User):
    """
    Ищет ID топика в базе. 
    Если топик удален в Telegram — удаляет его из базы и создает новый.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT thread_id FROM threads WHERE user_id = %s', (user.id,))
            res = await cur.fetchone()
            thread_id = res[0] if res else None

    # Если ID найден в базе, проверяем, не удален ли топик в самом Telegram
    if thread_id:
        try:
            # Попытка сделать "typing" в топик. Если топик удален, вернется ошибка.
            await bot.send_chat_action(chat_id=ADMIN_GROUP_ID, action="typing", message_thread_id=thread_id)
        except Exception:
            # Ошибка означает, что топика больше нет. Чистим базу.
            print(f"DEBUG: Топик {thread_id} для {user.id} не существует. Пересоздаю...")
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('DELETE FROM threads WHERE user_id = %s', (user.id,))
            thread_id = None

    # Если топика нет в базе или он был только что удален как невалидный
    if not thread_id:
        try:
            topic_name = f"{user.full_name}" + (f" (@{user.username})" if user.username else "")
            topic = await bot.create_forum_topic(chat_id=ADMIN_GROUP_ID, name=topic_name)
            thread_id = topic.message_thread_id
            
            # Сохраняем новый ID в базу
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'INSERT INTO threads (user_id, thread_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE thread_id=%s',
                        (user.id, thread_id, thread_id)
                    )
            print(f"DEBUG: Создан новый топик {thread_id} для {user.id}")
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать топик: {e}")
            return None
            
    return thread_id

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    # Настройка кнопок
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 Загрузить файл", url="https://tiny.cc/xrcent"))
    kb.row(types.InlineKeyboardButton(text="📄 Получить скан", callback_data="get_scan"))
    
    await m.answer(
        f"Здравствуйте, <b>{m.from_user.first_name}</b>! 👋\n\n"
        "Я помогу вам связаться с администратором. Вы можете просто написать сообщение здесь, "
        "или воспользоваться кнопками ниже:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "get_scan")
async def handle_scan_button(cb: types.CallbackQuery):
    await cb.answer()
    tid = await get_valid_thread(cb.from_user)
    
    if tid:
        # Уведомляем админа в соответствующем топике
        admin_text = f"🔔 Пользователь <b>{html.escape(cb.from_user.full_name)}</b> запрашивает скан."
        await bot.send_message(ADMIN_GROUP_ID, admin_text, message_thread_id=tid, parse_mode="HTML")
        await cb.message.answer("✅ Запрос на получение скана отправлен администратору.")
    else:
        await cb.message.answer("❌ Ошибка: не удалось создать ветку обсуждения. Сообщите администратору.")

@dp.message(F.chat.type == "private")
async def handle_private_message(m: types.Message):
    """Пересылка из ЛС бота в топик группы админов."""
    if m.text == "/start": return
    
    tid = await get_valid_thread(m.from_user)
    if tid:
        try:
            await bot.copy_message(
                chat_id=ADMIN_GROUP_ID,
                from_chat_id=m.chat.id,
                message_id=m.message_id,
                message_thread_id=tid
            )
        except TelegramBadRequest as e:
            # На случай, если что-то пошло не так при копировании
            print(f"Ошибка копирования: {e}")
    else:
        await m.answer("Техническая ошибка в группе администратора. Попробуйте позже.")

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def handle_admin_reply(m: types.Message):
    """Пересылка ответа из топика обратно пользователю."""
    if not m.message_thread_id: return # Игнорируем сообщения в General
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT user_id FROM threads WHERE thread_id = %s', (m.message_thread_id,))
            res = await cur.fetchone()
            
            if res:
                user_id = res[0]
                try:
                    await bot.copy_message(
                        chat_id=user_id,
                        from_chat_id=ADMIN_GROUP_ID,
                        message_id=m.message_id
                    )
                except Exception as e:
                    print(f"Не удалось отправить ответ пользователю {user_id}: {e}")

# --- ЗАПУСК ---
async def main():
    await init_db()
    # Удаляем старые обновления, чтобы бот не спамил при запуске
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
