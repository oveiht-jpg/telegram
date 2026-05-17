import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

threads = {}

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Получить скан", callback_data="get_scan"))
    builder.row(types.InlineKeyboardButton(text="Загрузить файл для печати", callback_data="upload_file"))
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Бот просто отвечает пользователю, в группу ничего не шлет
    await message.answer(
        "Здравствуйте! Выберите нужную опцию:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "get_scan")
async def process_scan(callback: types.Callback_query):
    await callback.message.answer("Пожалуйста, напишите ваш email")
    await callback.answer()

@dp.callback_query(F.data == "upload_file")
async def process_upload(callback: types.Callback_query):
    await callback.message.answer("Пожалуйста, отправьте файл")
    await callback.answer()

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    # Проверка: если пользователь прислал /start в виде текста, игнорируем
    if message.text == "/start":
        return

    user_id = message.from_user.id
    
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

    # Пересылаем только содержательные сообщения (email или файл)
    await bot.copy_message(
        chat_id=ADMIN_GROUP_ID,
        message_thread_id=threads[user_id],
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )
    
    await message.answer("Пожалуйста, ожидайте.")

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
