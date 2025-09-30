import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            ban_until TIMESTAMP,
            reason TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
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

def is_user_banned(user_id: int) -> tuple:
    """Проверяет, забанен ли пользователь. Возвращает (забанен_ли, время_окончания, причина)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT ban_until, reason FROM bans WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False, None, None
    
    ban_until, reason = result
    
    # Если бан вечный (ban_until is None)
    if ban_until is None:
        return True, None, reason
    
    # Проверяем, не истек ли срок бана
    ban_until_dt = datetime.fromisoformat(ban_until)
    if datetime.now() > ban_until_dt:
        # Удаляем истекший бан
        remove_ban(user_id)
        return False, None, None
    
    return True, ban_until_dt, reason

def add_ban(user_id: int, hours: float, reason: str = None):
    """Добавляет бан пользователю"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if hours == float('inf'):  # Вечный бан
        ban_until = None
    else:
        ban_until = datetime.now() + timedelta(hours=hours)
    
    cursor.execute(
        "INSERT OR REPLACE INTO bans (user_id, ban_until, reason) VALUES (?, ?, ?)",
        (user_id, ban_until.isoformat() if ban_until else None, reason)
    )
    conn.commit()
    conn.close()

def remove_ban(user_id: int):
    """Снимает бан с пользователя"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_ban_list():
    """Получает список всех активных банов"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.user_id, b.ban_until, b.reason, u.tg_id, u.username 
        FROM bans b 
        JOIN users u ON b.user_id = u.id
    ''')
    bans = cursor.fetchall()
    conn.close()
    
    # Фильтруем истекшие баны
    active_bans = []
    for ban in bans:
        user_id, ban_until, reason, tg_id, username = ban
        if ban_until is None:  # Вечный бан
            active_bans.append(ban)
        else:
            ban_until_dt = datetime.fromisoformat(ban_until)
            if datetime.now() <= ban_until_dt:
                active_bans.append(ban)
            else:
                remove_ban(user_id)
    
    return active_bans

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
        # Проверяем, не забанен ли пользователь
        user_id = context.user_data.get('bot_user_id')
        if user_id:
            banned, ban_until, reason = is_user_banned(user_id)
            if banned:
                await query.edit_message_text(
                    "Вы заблокированы и не можете отправить сообщения. Для получения справки напишите /baninfo."
                )
                return
        
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
        # Проверяем, не забанен ли пользователь
        user_id = context.user_data.get('bot_user_id')
        if user_id:
            banned, ban_until, reason = is_user_banned(user_id)
            if banned:
                await query.edit_message_text(
                    "Вы заблокированы и не можете отправить сообщения. Для получения справки напишите /baninfo."
                )
                context.user_data.pop('message_to_send', None)
                context.user_data.pop('waiting_for_message', None)
                return
        
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
                elif message_data['type'] == 'single_document':
                    await context.bot.send_document(
                        chat_id=CHANNEL_ID,
                        document=message_data['file_id'],
                        caption=message_data['text']
                    )
                elif message_data['type'] == 'voice':
                    # Для голосового сначала отправляем голосовое
                    voice_message = await context.bot.send_voice(
                        chat_id=CHANNEL_ID,
                        voice=message_data['file_id']
                    )
                    # Затем отправляем подпись в ответ на голосовое сообщение в канале
                    if message_data['text']:
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=message_data['text'],
                            reply_to_message_id=voice_message.message_id
                        )
                elif message_data['type'] == 'video_note':
                    # Для видеосообщения сначала отправляем видеосообщение
                    video_note_message = await context.bot.send_video_note(
                        chat_id=CHANNEL_ID,
                        video_note=message_data['file_id']
                    )
                    # Затем отправляем подпись в ответ на видеосообщение в канале
                    if message_data['text']:
                        await context.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=message_data['text'],
                            reply_to_message_id=video_note_message.message_id
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
                        elif isinstance(first_media, InputMediaDocument):
                            media_with_caption[0] = InputMediaDocument(
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

async def send_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение с подтверждением"""
    keyboard = [
        [
            InlineKeyboardButton("Отправить", callback_data="confirm_send"),
            InlineKeyboardButton("Отмена", callback_data="cancel_confirm")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirmation_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Подтвердите отправку",
        reply_markup=reply_markup
    )
    
    # Сохраняем ID сообщения с подтверждением (без таймера)
    context.user_data['confirmation_message_id'] = confirmation_message.message_id
    context.user_data['confirmation_chat_id'] = confirmation_message.chat_id

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
    elif message_data['type'] == 'single_document':
        await update.message.reply_document(
            document=message_data['file_id'],
            caption=final_text
        )
    elif message_data['type'] == 'voice':
        # Для голосового отправляем сначала голосовое
        voice_message = await update.message.reply_voice(
            voice=message_data['file_id']
        )
        # Затем отправляем подпись в ответ на голосовое сообщение
        if final_text.strip():
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=final_text,
                reply_to_message_id=voice_message.message_id
            )
    elif message_data['type'] == 'video_note':
        # Для видеосообщения отправляем сначала видеосообщение
        video_note_message = await update.message.reply_video_note(
            video_note=message_data['file_id']
        )
        # Затем отправляем подпись в ответ на видеосообщение
        if final_text.strip():
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=final_text,
                reply_to_message_id=video_note_message.message_id
            )

async def process_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает собранную группу медиа"""
    if media_group_id not in media_groups:
        return
    
    group_data = media_groups[media_group_id]
    
    # Проверяем, что у нас есть хотя бы 2 медиа для группы
    if len(group_data['media']) < 2:
        # Если только одно медиа, обрабатываем как одиночное
        if group_data['media']:
            first_media = group_data['media'][0]
            if isinstance(first_media, InputMediaPhoto):
                context.user_data['message_to_send'] = {
                    'type': 'single_photo',
                    'file_id': first_media.media,
                    'text': group_data['caption']
                }
                # Отправляем предпросмотр одиночного фото
                await context.bot.send_photo(
                    chat_id=group_data['chat_id'],
                    photo=first_media.media,
                    caption=group_data['caption']
                )
            elif isinstance(first_media, InputMediaVideo):
                context.user_data['message_to_send'] = {
                    'type': 'single_video',
                    'file_id': first_media.media,
                    'text': group_data['caption']
                }
                # Отправляем предпросмотр одиночного видео
                await context.bot.send_video(
                    chat_id=group_data['chat_id'],
                    video=first_media.media,
                    caption=group_data['caption']
                )
            elif isinstance(first_media, InputMediaDocument):
                context.user_data['message_to_send'] = {
                    'type': 'single_document',
                    'file_id': first_media.media,
                    'text': group_data['caption']
                }
                # Отправляем предпросмотр одиночного документа
                await context.bot.send_document(
                    chat_id=group_data['chat_id'],
                    document=first_media.media,
                    caption=group_data['caption']
                )
        del media_groups[media_group_id]
        return
    
    # Подготавливаем данные для отправки группы медиа
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
            elif isinstance(first_media, InputMediaDocument):
                preview_media[0] = InputMediaDocument(
                    media=first_media.media,
                    caption=group_data['caption']
                )
        
        preview_messages = await context.bot.send_media_group(
            chat_id=group_data['chat_id'],
            media=preview_media
        )
        
        # Отправляем сообщение с подтверждением
        await send_confirmation_from_context(context, group_data['chat_id'])
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=group_data['chat_id'],
            text=f"Ошибка при создании предпросмотра: {str(e)}"
        )
    
    # Удаляем группу из временного хранилища
    del media_groups[media_group_id]

async def send_confirmation_from_context(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Отправляет подтверждение из контекста"""
    keyboard = [
        [
            InlineKeyboardButton("Отправить", callback_data="confirm_send"),
            InlineKeyboardButton("Отмена", callback_data="cancel_confirm")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirmation_message = await context.bot.send_message(
        chat_id=chat_id,
        text="Подтвердите отправку",
        reply_markup=reply_markup
    )
    
    # Сохраняем ID сообщения с подтверждением (без таймера)
    context.user_data['confirmation_message_id'] = confirmation_message.message_id
    context.user_data['confirmation_chat_id'] = confirmation_message.chat_id

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
            'last_update': asyncio.get_event_loop().time(),
            'task': None
        }
    
    # Обновляем время последнего обновления
    media_groups[media_group_id]['last_update'] = asyncio.get_event_loop().time()
    
    # Добавляем медиа в группу
    if update.message.photo:
        photo = update.message.photo[-1]
        # Проверяем, нет ли уже этого медиа в группе
        media_exists = any(
            isinstance(media, InputMediaPhoto) and media.media == photo.file_id 
            for media in media_groups[media_group_id]['media']
        )
        if not media_exists:
            media_groups[media_group_id]['media'].append(
                InputMediaPhoto(media=photo.file_id)
            )
    elif update.message.video:
        # Проверяем, нет ли уже этого медиа в группе
        media_exists = any(
            isinstance(media, InputMediaVideo) and media.media == update.message.video.file_id 
            for media in media_groups[media_group_id]['media']
        )
        if not media_exists:
            media_groups[media_group_id]['media'].append(
                InputMediaVideo(media=update.message.video.file_id)
            )
    elif update.message.document:
        # Проверяем, нет ли уже этого медиа в группе
        media_exists = any(
            isinstance(media, InputMediaDocument) and media.media == update.message.document.file_id 
            for media in media_groups[media_group_id]['media']
        )
        if not media_exists:
            media_groups[media_group_id]['media'].append(
                InputMediaDocument(media=update.message.document.file_id)
            )
    
    # Сохраняем подпись (берем из первого сообщения с подписью)
    if update.message.caption and not media_groups[media_group_id]['caption']:
        media_groups[media_group_id]['caption'] = update.message.caption + footer_text
    
    # Если подписи нет, но есть медиа, добавляем только footer
    if not media_groups[media_group_id]['caption'] and media_groups[media_group_id]['media']:
        media_groups[media_group_id]['caption'] = footer_text.strip()
    
    # Отменяем предыдущую задачу обработки, если она есть
    if media_groups[media_group_id]['task']:
        media_groups[media_group_id]['task'].cancel()
    
    # Создаем новую задачу для обработки группы через 1.5 секунды
    media_groups[media_group_id]['task'] = asyncio.create_task(
        delayed_process_media_group(media_group_id, context, 1.5)
    )

async def delayed_process_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE, delay: float):
    """Отложенная обработка группы медиа"""
    await asyncio.sleep(delay)
    await process_media_group(media_group_id, context)

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
        
    elif message.document:
        # Файл (документ)
        context.user_data['message_to_send'] = {
            'type': 'single_document',
            'file_id': message.document.file_id
        }
        await handle_single_media(update, context, context.user_data['message_to_send'])
        
    elif message.voice:
        # Голосовое сообщение
        context.user_data['message_to_send'] = {
            'type': 'voice',
            'file_id': message.voice.file_id
        }
        await handle_single_media(update, context, context.user_data['message_to_send'])
        
    elif message.video_note:
        # Видеосообщение (кружок)
        context.user_data['message_to_send'] = {
            'type': 'video_note',
            'file_id': message.video_note.file_id
        }
        await handle_single_media(update, context, context.user_data['message_to_send'])
    
    # Для ВСЕХ типов сообщений отправляем подтверждение после предпросмотра
    if not message.media_group_id:
        # Ждем немного чтобы предпросмотр успел отправиться
        await asyncio.sleep(0.5)
        await send_confirmation(update, context)

# Команды для банов
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /ban для блокировки пользователя"""
    user = update.effective_user
    
    # Проверяем, является ли пользователь администратором
    if user.id != ADMIN_ID:
        return  # Игнорируем команду от не-админа
    
    if not context.args:
        await update.message.reply_text("Использование: /ban [ID пользователя] [время в часах или x для вечного бана] [причина]")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /ban [ID пользователя] [время в часах или x для вечного бана] [причина]")
        return
    
    try:
        user_id = int(context.args[0])
        time_arg = context.args[1].lower()
        
        if time_arg == 'x':
            hours = float('inf')  # Вечный бан
        else:
            hours = float(time_arg)
        
        # Получаем причину (все оставшиеся аргументы)
        reason = ' '.join(context.args[2:]) if len(context.args) > 2 else None
        
        # Проверяем существование пользователя
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        user_exists = cursor.fetchone()
        conn.close()
        
        if not user_exists:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
            return
        
        # Добавляем бан
        add_ban(user_id, hours, reason)
        
        if hours == float('inf'):
            time_text = "Вечная"
        else:
            time_text = f"{hours} часов"
        
        reason_text = reason if reason else "Не указана"
        
        await update.message.reply_text(
            f"Пользователь [ID: {user_id}] заблокирован.\n"
            f"Время: {time_text}\n"
            f"Причина: {reason_text}"
        )
        
    except ValueError:
        await update.message.reply_text("Ошибка: ID пользователя должен быть числом, а время - числом или 'x' для вечного бана.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unban для разблокировки пользователя"""
    user = update.effective_user
    
    # Проверяем, является ли пользователь администратором
    if user.id != ADMIN_ID:
        return  # Игнорируем команду от не-админа
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Использование: /unban [ID пользователя]")
        return
    
    try:
        user_id = int(context.args[0])
        
        # Проверяем существование пользователя
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        user_exists = cursor.fetchone()
        conn.close()
        
        if not user_exists:
            await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
            return
        
        # Проверяем, забанен ли пользователь
        banned, _, _ = is_user_banned(user_id)
        if not banned:
            await update.message.reply_text(f"Пользователь [ID: {user_id}] не заблокирован.")
            return
        
        # Снимаем бан
        remove_ban(user_id)
        await update.message.reply_text(f"Пользователь [ID: {user_id}] разблокирован.")
        
    except ValueError:
        await update.message.reply_text("Ошибка: ID пользователя должен быть числом.")

async def baninfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /baninfo для проверки статуса блокировки"""
    user = update.effective_user
    
    # Получаем ID пользователя в боте
    user_id = get_or_create_user(user.id, user.username)
    
    # Проверяем бан
    banned, ban_until, reason = is_user_banned(user_id)
    
    if not banned:
        await update.message.reply_text("Вы не заблокированы.")
        return
    
    if ban_until is None:
        time_text = "Вечная"
    else:
        time_left = ban_until - datetime.now()
        hours_left = int(time_left.total_seconds() / 3600)
        minutes_left = int((time_left.total_seconds() % 3600) / 60)
        
        if hours_left > 0:
            time_text = f"{hours_left} часов {minutes_left} минут"
        else:
            time_text = f"{minutes_left} минут"
    
    reason_text = reason if reason else "Не указана"
    
    await update.message.reply_text(
        f"Вы заблокированы.\n"
        f"Закончится через: {time_text}\n"
        f"Причина: {reason_text}"
    )

async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /banlist для просмотра списка заблокированных"""
    user = update.effective_user
    
    # Проверяем, является ли пользователь администратором
    if user.id != ADMIN_ID:
        return  # Игнорируем команду от не-админа
    
    bans = get_ban_list()
    
    if not bans:
        await update.message.reply_text("Нет активных блокировок.")
        return
    
    ban_list_text = ""
    for i, ban in enumerate(bans):
        user_id, ban_until, reason, tg_id, username = ban
        
        if ban_until is None:
            time_text = "Бессрочно"
        else:
            ban_until_dt = datetime.fromisoformat(ban_until)
            time_left = ban_until_dt - datetime.now()
            hours_left = int(time_left.total_seconds() / 3600)
            time_text = f"{hours_left} часов"
        
        reason_text = reason if reason else "Не указана"
        
        ban_list_text += f"{user_id}\n{time_text}\n{reason_text}"
        
        if i < len(bans) - 1:
            ban_list_text += "\n\n"
    
    await update.message.reply_text(ban_list_text)

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
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("baninfo", baninfo_command))
    application.add_handler(CommandHandler("banlist", banlist_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
