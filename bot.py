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

# Глобальный словарь для хранения групп медиа
media_groups = {}

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
                elif message_data['type'] == 'single_photo':
                    await context.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=message_data['file_id'],
                        caption=message_data['text']
                    )
                elif message_data['type'] == 'single_video':
                    await context.bot.send_video(
                        chat_id=CHANNEL_ID,
                        video=message_data['file_id'],
                        caption=message_data['text']
                    )
                elif message_data['type'] == 'media_group':
                    # Отправляем группу медиа с подписью к первому элементу
                    media_with_caption = message_data['media'].copy()
                    if message_data['text']:
                        # Создаем копию первого медиа с подписью
                        first_media = media_with_caption[0]
                        if isinstance(first_media, InputMediaPhoto):
                            media_with_caption[0] = InputMediaPhoto(
                                media=first_media.media,
                                caption=message_data['text']
                            )
                        elif isinstance(first_media, InputMediaVideo):
                            media_with_caption[0] = InputMediaVideo(
                                media=first_media.media,
                                caption=message_data['text']
                            )
                    
                    await context.bot.send_media_group(
                        chat_id=CHANNEL_ID,
                        media=media_with_caption
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

async def handle_single_media(update: Update, context: ContextTypes.DEFAULT_TYPE, message_data: dict):
    """Обработка одиночного медиа"""
    user_id = context.user_data.get('bot_user_id')
    footer_text = f"\n\n(Подслушано 1699)[https://Pod1699.t.me] | Сообщение отправлено пользователем [ID: {user_id}]"
    
    caption = update.message.caption if update.message.caption else ""
    final_text = caption + footer_text
    
    message_data.update({
        'text': final_text
    })
    
    # Отправляем предпросмотр пользователю
    if message_data['type'] == 'single_photo':
        await update.message.reply_photo(
            photo=message_data['file_id'],
            caption=final_text
        )
    elif message_data['type'] == 'single_video':
        await update.message.reply_video(
            video=message_data['file_id'],
            caption=final_text
        )

async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    """Обработка группы медиа"""
    user_id = context.user_data.get('bot_user_id')
    footer_text = f"\n\n(Подслушано 1699)[https://Pod1699.t.me] | Сообщение отправлено пользователем [ID: {user_id}]"
    
    # Инициализируем группу, если ее еще нет
    if media_group_id not in media_groups:
        media_groups[media_group_id] = {
            'media': [],
            'caption': '',
            'user_id': user_id,
            'chat_id': update.message.chat_id,
            'processed': False
        }
    
    # Добавляем медиа в группу
    if update.message.photo:
        photo = update.message.photo[-1]
        media_groups[media_group_id]['media'].append(
            InputMediaPhoto(media=photo.file_id)
        )
    elif update.message.video:
        media_groups[media_group_id]['media'].append(
            InputMediaVideo(media=update.message.video.file_id)
        )
    
    # Сохраняем подпись (берем из первого сообщения с подписью)
    if update.message.caption and not media_groups[media_group_id]['caption']:
        media_groups[media_group_id]['caption'] = update.message.caption + footer_text
    
    # Если подписи нет, но есть медиа, добавляем только footer
    if not media_groups[media_group_id]['caption'] and media_groups[media_group_id]['media']:
        media_groups[media_group_id]['caption'] = footer_text.strip()
    
    # Ждем 2 секунды, чтобы собрать все медиа группы
    await asyncio.sleep(2)
    
    # Проверяем, не обработали ли мы уже эту группу
    if media_groups[media_group_id]['processed']:
        return
    
    # Помечаем группу как обработанную
    media_groups[media_group_id]['processed'] = True
    
    group_data = media_groups[media_group_id]
    
    # Подготавливаем данные для отправки
    context.user_data['message_to_send'] = {
        'type': 'media_group',
        'media': group_data['media'],
        'text': group_data['caption']
    }
    
    # Отправляем предпросмотр пользователю
    try:
        # Создаем копию медиа с подписью для предпросмотра
        preview_media = group_data['media'].copy()
        if group_data['caption'] and preview_media:
            first_media = preview_media[0]
            if isinstance(first_media, InputMediaPhoto):
                preview_media[0] = InputMediaPhoto(
                    media=first_media.media,
                    caption=group_data['caption']
                )
            elif isinstance(first_media, InputMediaVideo):
                preview_media[0] = InputMediaVideo(
                    media=first_media.media,
                    caption=group_data['caption']
                )
        
        preview_messages = await context.bot.send_media_group(
            chat_id=group_data['chat_id'],
            media=preview_media
        )
        
        # Отправляем сообщение с подтверждением
        keyboard = [
            [
                InlineKeyboardButton("Отправить", callback_data="confirm_send"),
                InlineKeyboardButton("Отмена", callback_data="cancel_confirm")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        confirmation_message = await context.bot.send_message(
            chat_id=group_data['chat_id'],
            text="Подтвердите отправку",
            reply_markup=reply_markup
        )
        
        # Устанавливаем таймер на 30 секунд
        context.user_data['confirmation_message_id'] = confirmation_message.message_id
        context.user_data['confirmation_chat_id'] = confirmation_message.chat_id
        
        asyncio.create_task(delete_after_timeout(context, 30))
        
    except Exception as e:
        await update.message.reply_text(f"Ошибка при создании предпросмотра: {str(e)}")
    
    # Удаляем группу из временного хранилища через 10 секунд
    await asyncio.sleep(10)
    if media_group_id in media_groups:
        del media_groups[media_group_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений от пользователя"""
    if not context.user_data.get('waiting_for_message'):
        return
    
    user = update.effective_user
    message = update.message
    
    # Обрабатываем группы медиа
    if message.media_group_id:
        await handle_media_group(update, context, message.media_group_id)
        return
    
    # Обрабатываем одиночные сообщения
    if message.text:
        # Текстовое сообщение
        user_id = context.user_data.get('bot_user_id')
        footer_text = f"\n\n(Подслушано 1699)[https://Pod1699.t.me] | Сообщение отправлено пользователем [ID: {user_id}]"
        
        final_text = message.text + footer_text
        context.user_data['message_to_send'] = {
            'type': 'text',
            'text': final_text
        }
        
        # Отправляем предпросмотр пользователю
        await message.reply_text(final_text)
        
    elif message.photo:
        # Одиночное фото
        photo = message.photo[-1]
        context.user_data['message_to_send'] = {
            'type': 'single_photo',
            'file_id': photo.file_id
        }
        await handle_single_media(update, context, context.user_data['message_to_send'])
        
    elif message.video:
        # Одиночное видео
        context.user_data['message_to_send'] = {
            'type': 'single_video',
            'file_id': message.video.file_id
        }
        await handle_single_media(update, context, context.user_data['message_to_send'])
    
    # Для одиночных сообщений отправляем подтверждение
    if not message.media_group_id:
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
