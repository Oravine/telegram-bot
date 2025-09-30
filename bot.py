import os
import asyncio
import sqlite3
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    filters
)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '5466865775'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '123456')

# База данных
DB_NAME = "users.db"

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_or_create_user(tg_id: int, username: str = None) -> int:
    """Получить или создать пользователя в базе данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Проверяем существование пользователя
    cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    result = cursor.fetchone()
    
    if result:
        user_id = result[0]
    else:
        # Создаем нового пользователя
        username_display = username if username else "None"
        cursor.execute(
            "INSERT INTO users (tg_id, username) VALUES (?, ?)",
            (tg_id, username_display)
        )
        user_id = cursor.lastrowid
        conn.commit()
    
    conn.close()
    return user_id

def get_all_users():
    """Получить всех пользователей из базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    conn.close()
    return users

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    message = update.message
    
    # Получаем или создаем пользователя в базе
    user_id = get_or_create_user(user.id, user.username)
    
    # Сохраняем user_id в контексте для дальнейшего использования
    context.user_data['bot_user_id'] = user_id
    
    # Создаем клавиатуру с кнопкой "Отправить сообщение"
    keyboard = [
        [InlineKeyboardButton("Отправить сообщение", callback_data="send_message")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        "Чтобы отправить сообщение в канал нажмите кнопку ниже.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на инлайн кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "send_message":
        # Пользователь нажал "Отправить сообщение"
        keyboard = [
            [InlineKeyboardButton("Отмена", callback_data="cancel_send")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Введите ваше сообщение. Вы можете прикрепить медиа",
            reply_markup=reply_markup
        )
        
        # Устанавливаем состояние ожидания сообщения
        context.user_data['waiting_for_message'] = True
        
    elif query.data == "cancel_send":
        # Пользователь нажал "Отмена"
        await query.delete_message()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Отправка отменена"
        )
        context.user_data.pop('waiting_for_message', None)
        
    elif query.data == "confirm_send":
        # Пользователь подтвердил отправку
        message_data = context.user_data.get('message_to_send')
        if message_data:
            try:
                # Отправляем сообщение в канал
                if message_data['type'] == 'text':
                    await context.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message_data['text']
                    )
                elif message_data['type'] == 'media':
                    media = []
                    for media_item in message_data['media']:
                        if media_item['type'] == 'photo':
                            media.append(InputMediaPhoto(media_item['file_id']))
                        elif media_item['type'] == 'video':
                            media.append(InputMediaVideo(media_item['file_id']))
                    
                    if media:
                        # Добавляем текст к первому медиа
                        media[0].caption = message_data['text']
                        await context.bot.send_media_group(
                            chat_id=CHANNEL_ID,
                            media=media
                        )
                
                await query.edit_message_text("Сообщение успешно отправлено в канал!")
                
            except Exception as e:
                await query.edit_message_text(f"Ошибка при отправке: {str(e)}")
        
        # Очищаем данные
        context.user_data.pop('message_to_send', None)
        context.user_data.pop('waiting_for_message', None)
        
    elif query.data == "cancel_confirm":
        # Пользователь отменил отправку на этапе подтверждения
        await query.delete_message()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Отменено."
        )
        context.user_data.pop('message_to_send', None)
        context.user_data.pop('waiting_for_message', None)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений от пользователя"""
    if not context.user_data.get('waiting_for_message'):
        return
    
    user = update.effective_user
    message = update.message
    user_id = context.user_data.get('bot_user_id')
    
    # Формируем финальный текст
    footer_text = f"\n\n(Подслушано 1699)[https://Pod1699.t.me] | Сообщение отправлено пользователем [ID: {user_id}]"
    
    # Обрабатываем разные типы сообщений
    if message.text:
        # Текстовое сообщение
        final_text = message.text + footer_text
        context.user_data['message_to_send'] = {
            'type': 'text',
            'text': final_text
        }
        
        # Отправляем предпросмотр пользователю
        await message.reply_text(final_text)
        
    elif message.photo or message.video:
        # Сообщение с медиа
        media_items = []
        
        if message.photo:
            # Берем самую большую фотографию
            photo = message.photo[-1]
            media_items.append({
                'type': 'photo',
                'file_id': photo.file_id
            })
        elif message.video:
            media_items.append({
                'type': 'video', 
                'file_id': message.video.file_id
            })
        
        caption = message.caption if message.caption else ""
        final_text = caption + footer_text
        
        context.user_data['message_to_send'] = {
            'type': 'media',
            'text': final_text,
            'media': media_items
        }
        
        # Отправляем предпросмотр пользователю
        if media_items[0]['type'] == 'photo':
            await message.reply_photo(
                photo=media_items[0]['file_id'],
                caption=final_text
            )
        else:
            await message.reply_video(
                video=media_items[0]['file_id'],
                caption=final_text
            )
    
    # Отправляем сообщение с подтверждением
    keyboard = [
        [
            InlineKeyboardButton("Отправить", callback_data="confirm_send"),
            InlineKeyboardButton("Отмена", callback_data="cancel_confirm")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirmation_message = await message.reply_text(
        "Подтвердите отправку",
        reply_markup=reply_markup
    )
    
    # Устанавливаем таймер на 30 секунд
    context.user_data['confirmation_message_id'] = confirmation_message.message_id
    context.user_data['confirmation_chat_id'] = confirmation_message.chat_id
    
    asyncio.create_task(delete_after_timeout(context, 30))

async def delete_after_timeout(context: ContextTypes.DEFAULT_TYPE, seconds: int):
    """Удаляет сообщение подтверждения после таймаута"""
    await asyncio.sleep(seconds)
    
    message_id = context.user_data.get('confirmation_message_id')
    chat_id = context.user_data.get('confirmation_chat_id')
    
    if message_id and chat_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(chat_id=chat_id, text="Отменено. Время истекло (30 с.)")
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    # Очищаем данные
    context.user_data.pop('message_to_send', None)
    context.user_data.pop('waiting_for_message', None)
    context.user_data.pop('confirmation_message_id', None)
    context.user_data.pop('confirmation_chat_id', None)

async def take_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /takedb для администратора"""
    user = update.effective_user
    
    # Проверяем, является ли пользователь администратором
    if user.id != ADMIN_ID:
        return  # Игнорируем команду от не-админа
    
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("База данных пуста.")
        return
    
    # Формируем текст с данными пользователей
    db_text = "База данных пользователей:\n\n"
    for user_data in users:
        db_text += f"{user_data[0]} {user_data[1]} {user_data[2]}\n"
    
    await update.message.reply_text(db_text)

def main():
    """Основная функция"""
    # Проверяем наличие токена
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не установлен!")
        return
    
    # Инициализируем базу данных
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("takedb", take_db))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
