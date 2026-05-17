import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилище
threads = {} 
# Список пользователей, которые выбрали "Получить скан"
waiting_for_scan_data = set()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    # Кнопка со ссылкой (URL-кнопка)
    builder.row(types.InlineKeyboardButton(
        text="Загрузить файл для печати", 
        url="https://tiny.cc/xrcent")
    )
    # Обычная кнопка для взаимодействия
    builder.row(types.InlineKeyboardButton(
        text="Получить скан", 
        callback_data="get_scan")
    )
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здравствуйте! Выберите нужную опцию:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: CallbackQuery):
    waiting_for_scan_data.add(callback.from_user.id)
    await callback.message.answer("Пожалуйста, напишите ваш email")
    await callback.answer()

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    if message.text == "/start":
        return

    user_id = message.from_user.id
    
    # Создаем ветку, если ее еще нет
    if user_id not in threads:
        try:
            topic = await bot.create_forum_topic(
                chat_id=ADMIN_GROUP_ID, 
                name=f"{message.from_user.full_name} [{user_id}]"
            )
            threads[user_id] = topic.message_thread_id
        except Exception as e:
            print(f"Ошибка создания темы: {e}")
            return

    # Пересылаем сообщение админу
    await bot.copy_message(
        chat_id=ADMIN_GROUP_ID,
        message_thread_id=threads[user_id],
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )
    
    # Логика ответа: только если пользователь нажал "Получить скан" ранее
    if user_id in waiting_for_scan_data:
        await message.answer("Пожалуйста, ожидайте.")
        # Удаляем из списка ожидания, чтобы не слать это на каждое последующее сообщение
        waiting_for_scan_data.remove(user_id)

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def forward_to_user(message: types.Message):
    if not message.message_thread_id:
        return

    user_id = next((uid for uid, tid in threads.items() if tid == message.message_thread_id), None)
    
    if user_id:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=ADMIN_GROUP_ID,
                message_id=message.message_id
            )
        except Exception as e:
            print(f"Ошибка отправки: {e}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
