import os
import asyncio
from aiogram import Bot, Dispatcher, types, F

# Данные берем из настроек Railway
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище (очистится при перезагрузке)
threads = {} 

@dp.message(F.chat.type == "private")
async def forward_to_admin(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in threads:
        # Создаем новую ветку для нового пользователя
        topic = await bot.create_forum_topic(
            chat_id=ADMIN_GROUP_ID, 
            name=f"{message.from_user.full_name} [{user_id}]"
        )
        threads[user_id] = topic.message_thread_id
    
    # Пересылаем сообщение в ветку
    await bot.copy_message(
        chat_id=ADMIN_GROUP_ID,
        message_thread_id=threads[user_id],
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

@dp.message(F.chat.id == ADMIN_GROUP_ID)
async def forward_to_user(message: types.Message):
    # Проверяем, что ответ написан в ветке, а не в общем чате
    if not message.message_thread_id:
        return

    # Ищем пользователя, которому принадлежит эта ветка
    user_id = next((uid for uid, tid in threads.items() if tid == message.message_thread_id), None)
    
    if user_id:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=ADMIN_GROUP_ID,
            message_id=message.message_id
        )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
