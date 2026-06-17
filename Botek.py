import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from collections import deque, defaultdict
from flask import Flask
import threading

# --- Настройки ---
API_TOKEN = os.environ.get('API_TOKEN', "ВАШ_ТОКЕН_ЕСЛИ_НЕТ_В_SECRETS")
ADMIN_ID = 8577385618  # ЗАМЕНИ НА СВОЙ TELEGRAM ID!!!

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Очереди ожидания
wait_men = deque()
wait_women = deque()
wait_any = deque()

# Пары, пол пользователей, статус поиска
pairs = {}  # {user_id: partner_id}
user_gender = {}  # {user_id: "m"/"f"}
searching_status = {}  # {user_id: "searching"}

# Бан-лист
banned_users = set()

# ИСТОРИЯ ДИАЛОГОВ
# {dialogue_id: {"user1": id, "user2": id, "messages": [...], "start_time": datetime, "end_time": datetime}}
dialogue_history = []
active_dialogue_logs = defaultdict(list)  # {dialogue_id: [messages]}
dialogue_counter = 0

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- Логирование сообщений ---
def log_message(sender_id, receiver_id, message):
    """Сохраняет сообщение в историю активного диалога"""
    dialogue_id = get_dialogue_id(sender_id)
    if dialogue_id is not None:
        msg_data = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "sender": sender_id,
            "receiver": receiver_id,
            "type": message.content_type,
            "content": None
        }
        
        if message.content_type == "text":
            msg_data["content"] = message.text
        elif message.content_type == "photo":
            msg_data["content"] = "[ФОТО]"
        elif message.content_type == "video":
            msg_data["content"] = "[ВИДЕО]"
        elif message.content_type == "voice":
            msg_data["content"] = "[ГОЛОСОВОЕ]"
        elif message.content_type == "sticker":
            msg_data["content"] = f"[СТИКЕР] {message.sticker.emoji if message.sticker else ''}"
        elif message.content_type == "video_note":
            msg_data["content"] = "[ВИДЕОКРУЖОК]"
        elif message.content_type == "audio":
            msg_data["content"] = "[АУДИО]"
        elif message.content_type == "document":
            msg_data["content"] = f"[ДОКУМЕНТ] {message.document.file_name if message.document else ''}"
        elif message.content_type == "location":
            msg_data["content"] = "[ГЕОЛОКАЦИЯ]"
        elif message.content_type == "contact":
            msg_data["content"] = "[КОНТАКТ]"
        elif message.content_type == "poll":
            msg_data["content"] = "[ОПРОС]"
        else:
            msg_data["content"] = f"[{message.content_type.upper()}]"
        
        active_dialogue_logs[dialogue_id].append(msg_data)

def get_dialogue_id(user_id):
    """Получает ID диалога по ID пользователя"""
    for i, dialogue in enumerate(dialogue_history):
        if (dialogue["user1"] == user_id or dialogue["user2"] == user_id) and not dialogue.get("ended"):
            return i
    return None

def archive_dialogue(user_id):
    """Архивирует диалог при завершении"""
    dialogue_id = get_dialogue_id(user_id)
    if dialogue_id is not None:
        dialogue_history[dialogue_id]["ended"] = True
        dialogue_history[dialogue_id]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dialogue_history[dialogue_id]["messages"] = active_dialogue_logs.get(dialogue_id, [])
        # Очищаем активные логи
        if dialogue_id in active_dialogue_logs:
            del active_dialogue_logs[dialogue_id]

# --- Меню ---

def menu_no_chat():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎲 Случайный собеседник"))
    builder.add(KeyboardButton(text="👨 Парень"))
    builder.add(KeyboardButton(text="👩 Девушка"))
    builder.row(KeyboardButton(text="👤 Мой пол"))
    return builder.as_markup(resize_keyboard=True)

def menu_in_chat():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Завершить чат"))
    builder.add(KeyboardButton(text="⏭ Следующий"))
    return builder.as_markup(resize_keyboard=True)

def admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Статистика"))
    builder.add(KeyboardButton(text="👁 Читать активный диалог"))
    builder.add(KeyboardButton(text="📜 История диалогов"))
    builder.add(KeyboardButton(text="🛑 Завершить диалог"))
    builder.row(KeyboardButton(text="🚫 Бан"))
    builder.add(KeyboardButton(text="✅ Разбан"))
    builder.row(KeyboardButton(text="👤 Обычное меню"))
    return builder.as_markup(resize_keyboard=True)

def is_banned(user_id):
    return user_id in banned_users

# --- Команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены в этом боте.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if user_id == ADMIN_ID:
        await message.answer("👑 Админ-панель активирована.", reply_markup=admin_menu())
        if user_id not in user_gender:
            await message.answer("Сначала выбери свой пол для теста:", reply_markup=gender_select_keyboard())
        return
    
    if user_id in user_gender:
        await cleanup_user(user_id)
        await message.answer("С возвращением!", reply_markup=menu_no_chat())
        return
    
    await message.answer(
        "👋 Добро пожаловать в анонимный чат!\n\nВыбери свой пол:",
        reply_markup=gender_select_keyboard()
    )

# --- Выбор пола ---
def gender_select_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="👨 Я парень", callback_data="first_gender_m"))
    builder.add(InlineKeyboardButton(text="👩 Я девушка", callback_data="first_gender_f"))
    builder.adjust(2)
    return builder.as_markup()

@dp.callback_query(F.data.startswith("first_gender_"))
async def save_first_gender(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if is_banned(user_id):
        await callback.message.edit_text("⛔ Вы забанены.")
        await callback.answer()
        return
    
    gender = callback.data.split("_")[2]
    user_gender[user_id] = gender
    
    await callback.message.edit_text(f"✅ Твой пол: {'парень' if gender == 'm' else 'девушка'}")
    
    if user_id == ADMIN_ID:
        await callback.message.answer("Готово. Админ-панель:", reply_markup=admin_menu())
    else:
        await callback.message.answer("Готово! Выбирай режим поиска:", reply_markup=menu_no_chat())
    await callback.answer()

# --- Смена пола ---
@dp.message(F.text == "👤 Мой пол")
async def change_gender_button(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Нельзя менять пол во время поиска.")
        return
    
    if user_id in pairs:
        await message.answer("❌ Нельзя менять пол в диалоге. Сначала заверши чат.")
        return
    
    current = "парень" if user_gender[user_id] == "m" else "девушка"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="👨 Парень", callback_data="change_gender_m"))
    builder.add(InlineKeyboardButton(text="👩 Девушка", callback_data="change_gender_f"))
    builder.adjust(2)
    await message.answer(f"Твой текущий пол: {current}\nВыбери новый:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("change_gender_"))
async def change_gender(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    gender = callback.data.split("_")[2]
    
    await cleanup_user(user_id)
    user_gender[user_id] = gender
    await callback.message.edit_text(f"✅ Пол изменён на: {'парень' if gender == 'm' else 'девушка'}")
    await callback.message.answer("Выбирай режим поиска:", reply_markup=menu_no_chat())
    await callback.answer()

# --- Очистка состояния ---
async def cleanup_user(user_id):
    # Архивируем диалог перед удалением
    if user_id in pairs:
        archive_dialogue(user_id)
    
    if user_id in wait_men: wait_men.remove(user_id)
    if user_id in wait_women: wait_women.remove(user_id)
    if user_id in wait_any: wait_any.remove(user_id)
    
    if user_id in searching_status:
        del searching_status[user_id]
    
    if user_id in pairs:
        partner = pairs.pop(user_id)
        if partner in pairs and pairs[partner] == user_id:
            pairs.pop(partner)
            try:
                await bot.send_message(partner, "❌ Собеседник покинул чат.", reply_markup=menu_no_chat())
            except:
                pass

# --- Завершить чат ---
@dp.message(F.text == "❌ Завершить чат")
async def stop_button(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in pairs:
        if user_id in searching_status:
            del searching_status[user_id]
            await message.answer("🔍 Поиск остановлен.", reply_markup=menu_no_chat())
        else:
            await message.answer("Ты не в диалоге.", reply_markup=menu_no_chat())
        return
    
    await cleanup_user(user_id)
    await message.answer("✅ Диалог завершён.", reply_markup=menu_no_chat())

# --- Следующий ---
@dp.message(F.text == "⏭ Следующий")
async def next_partner_button(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in pairs:
        await message.answer("Ты не в диалоге.", reply_markup=menu_no_chat())
        return
    
    await cleanup_user(user_id)
    await message.answer("🔄 Выбери режим поиска:", reply_markup=menu_no_chat())

# --- Поиск ---

@dp.message(F.text == "🎲 Случайный собеседник")
async def search_any(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске!")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге!")
        return
    
    await cleanup_user(user_id)
    partner = None
    
    if wait_any:
        partner = wait_any.popleft()
    elif user_gender[user_id] == "m" and wait_men:
        partner = wait_men.popleft()
    elif user_gender[user_id] == "f" and wait_women:
        partner = wait_women.popleft()
    elif user_gender[user_id] == "m" and wait_women:
        partner = wait_women.popleft()
    elif user_gender[user_id] == "f" and wait_men:
        partner = wait_men.popleft()
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Собеседник найден! Общайтесь.", reply_markup=menu_in_chat())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=menu_in_chat())
    else:
        wait_any.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу случайного собеседника...", reply_markup=menu_no_chat())

@dp.message(F.text == "👨 Парень")
async def search_man(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске!")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге!")
        return
    
    await cleanup_user(user_id)
    partner = None
    
    for waiting_user in list(wait_any):
        if user_gender.get(waiting_user) == "m":
            wait_any.remove(waiting_user)
            partner = waiting_user
            break
    
    if not partner and wait_men:
        partner = wait_men.popleft()
    
    if not partner:
        for waiting_user in list(wait_any):
            if user_gender.get(waiting_user) == "f":
                wait_any.remove(waiting_user)
                partner = waiting_user
                break
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Парень найден! Общайтесь.", reply_markup=menu_in_chat())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=menu_in_chat())
    else:
        wait_men.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу парня...", reply_markup=menu_no_chat())

@dp.message(F.text == "👩 Девушка")
async def search_woman(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске!")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге!")
        return
    
    await cleanup_user(user_id)
    partner = None
    
    for waiting_user in list(wait_any):
        if user_gender.get(waiting_user) == "f":
            wait_any.remove(waiting_user)
            partner = waiting_user
            break
    
    if not partner and wait_women:
        partner = wait_women.popleft()
    
    if not partner:
        for waiting_user in list(wait_any):
            if user_gender.get(waiting_user) == "m":
                wait_any.remove(waiting_user)
                partner = waiting_user
                break
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Девушка найдена! Общайтесь.", reply_markup=menu_in_chat())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=menu_in_chat())
    else:
        wait_women.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу девушку...", reply_markup=menu_no_chat())

async def connect_pair(user1, user2):
    global dialogue_counter
    
    pairs[user1] = user2
    pairs[user2] = user1
    
    for uid in [user1, user2]:
        if uid in searching_status:
            del searching_status[uid]
    
    # Создаём запись в истории
    dialogue_history.append({
        "id": dialogue_counter,
        "user1": user1,
        "user2": user2,
        "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ended": False,
        "messages": []
    })
    active_dialogue_logs[dialogue_counter] = []
    dialogue_counter += 1

# ========================================================
#                 АДМИН-ПАНЕЛЬ
# ========================================================

@dp.message(F.text == "👤 Обычное меню")
async def switch_to_normal_menu(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    if user_id in pairs:
        await message.answer("Обычное меню:", reply_markup=menu_in_chat())
    else:
        await message.answer("Обычное меню:", reply_markup=menu_no_chat())

# --- Статистика ---
@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    total_users = len(user_gender)
    men = sum(1 for g in user_gender.values() if g == "m")
    women = sum(1 for g in user_gender.values() if g == "f")
    active_pairs = len(pairs) // 2
    in_search = len(searching_status)
    total_dialogues = len(dialogue_history)
    active_dialogues = sum(1 for d in dialogue_history if not d.get("ended"))
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"👨 Парней: {men}\n"
        f"👩 Девушек: {women}\n"
        f"💬 Активных диалогов: {active_pairs}\n"
        f"🔍 В поиске: {in_search}\n"
        f"📜 Всего диалогов в истории: {total_dialogues}\n"
        f"📝 Активных логов: {active_dialogues}\n"
        f"🚫 Забанено: {len(banned_users)}"
    )
    await message.answer(stats_text, reply_markup=admin_menu())

# --- Читать активный диалог ---
@dp.message(F.text == "👁 Читать активный диалог")
async def admin_watch_active(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    if not pairs:
        await message.answer("❌ Нет активных диалогов.", reply_markup=admin_menu())
        return
    
    # Показываем список активных пар
    shown = set()
    text = "👁 Активные диалоги:\n\n"
    count = 0
    
    for d_id, dialogue in enumerate(dialogue_history):
        if not dialogue.get("ended"):
            u1 = dialogue["user1"]
            u2 = dialogue["user2"]
            if (u1, u2) not in shown and (u2, u1) not in shown:
                shown.add((u1, u2))
                count += 1
                g1 = "👨" if user_gender.get(u1) == "m" else "👩"
                g2 = "👨" if user_gender.get(u2) == "m" else "👩"
                text += f"{count}. {g1} {u1} ↔ {g2} {u2}\n"
    
    if count == 0:
        await message.answer("❌ Нет активных диалогов.", reply_markup=admin_menu())
        return
    
    text += "\nОтправь ID пользователя, чей диалог хочешь читать.\n"
    text += "Все новые сообщения будут пересылаться тебе."
    
    await message.answer(text, reply_markup=types.ForceReply())

# --- История диалогов ---
@dp.message(F.text == "📜 История диалогов")
async def admin_history(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    if not dialogue_history:
        await message.answer("📜 История пуста.", reply_markup=admin_menu())
        return
    
    # Показываем список всех диалогов
    text = "📜 Все диалоги:\n\n"
    
    for i, dialogue in enumerate(dialogue_history[-10:]):  # Последние 10
        u1 = dialogue["user1"]
        u2 = dialogue["user2"]
        g1 = "👨" if user_gender.get(u1) == "m" else "👩"
        g2 = "👨" if user_gender.get(u2) == "m" else "👩"
        status = "🟢" if not dialogue.get("ended") else "🔴"
        msg_count = len(dialogue.get("messages", []))
        start = dialogue.get("start_time", "?")
        
        text += f"{status} #{dialogue['id']}: {g1}{u1} ↔ {g2}{u2} | {msg_count} сообщ. | {start}\n"
    
    text += "\nОтправь ID диалога (#номер), чтобы прочитать переписку."
    await message.answer(text, reply_markup=types.ForceReply())

# --- Завершить чужой диалог ---
@dp.message(F.text == "🛑 Завершить диалог")
async def admin_force_stop(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    if not pairs:
        await message.answer("❌ Нет активных диалогов.", reply_markup=admin_menu())
        return
    
    # Показываем активные пары
    shown = set()
    text = "🛑 Активные диалоги:\n\n"
    count = 0
    
    for d_id, dialogue in enumerate(dialogue_history):
        if not dialogue.get("ended"):
            u1 = dialogue["user1"]
            u2 = dialogue["user2"]
            if (u1, u2) not in shown and (u2, u1) not in shown:
                shown.add((u1, u2))
                count += 1
                g1 = "👨" if user_gender.get(u1) == "m" else "👩"
                g2 = "👨" if user_gender.get(u2) == "m" else "👩"
                text += f"{count}. {g1} {u1} ↔ {g2} {u2}\n"
    
    text += "\nОтправь ID пользователя для завершения диалога."
    await message.answer(text, reply_markup=types.ForceReply())

# --- Бан ---
@dp.message(F.text == "🚫 Бан")
async def admin_ban(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    await message.answer(
        "Отправь ID пользователя для бана.\nБан работает всегда, даже если пользователь не в диалоге.",
        reply_markup=types.ForceReply()
    )

# --- Разбан ---
@dp.message(F.text == "✅ Разбан")
async def admin_unban(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    if not banned_users:
        await message.answer("Список банов пуст.", reply_markup=admin_menu())
        return
    
    text = "🚫 Забаненные пользователи:\n\n"
    for uid in banned_users:
        g = "👨" if user_gender.get(uid) == "m" else "👩"
        text += f"{g} {uid}\n"
    
    text += "\nОтправь ID для разбана."
    await message.answer(text, reply_markup=types.ForceReply())

# --- Обработка ответов админа ---
@dp.message(F.reply_to_message)
async def handle_admin_replies(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        # Обычный пользователь — пересылаем в чат
        if user_id in pairs:
            await forward_to_partner(message)
        return
    
    if not message.reply_to_message or not message.reply_to_message.text:
        return
    
    reply_text = message.reply_to_message.text
    answer = message.text.strip()
    
    # === Чтение активного диалога ===
    if "Отправь ID пользователя, чей диалог хочешь читать" in reply_text:
        try:
            target_id = int(answer)
            if target_id not in pairs:
                await message.answer("❌ Этот пользователь не в диалоге.", reply_markup=admin_menu())
                return
            
            # Показываем последние сообщения
            dialogue_id = get_dialogue_id(target_id)
            if dialogue_id is not None and dialogue_id in active_dialogue_logs:
                logs = active_dialogue_logs[dialogue_id]
                if logs:
                    text = f"👁 Последние сообщения диалога (User {target_id}):\n\n"
                    for msg in logs[-20:]:  # Последние 20
                        sender = "User1" if msg["sender"] == dialogue_history[dialogue_id]["user1"] else "User2"
                        text += f"[{msg['timestamp']}] {sender}: {msg['content']}\n"
                    
                    if len(text) > 4000:
                        text = text[:4000] + "\n\n... (обрезано)"
                    
                    await message.answer(text)
            
            await message.answer(
                f"✅ Теперь ты читаешь диалог пользователя {target_id}.\n"
                "Все новые сообщения будут пересылаться тебе.\n"
                "Для остановки нажми 👤 Обычное меню.",
                reply_markup=admin_menu()
            )
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return
    
    # === Чтение истории диалогов ===
    if "Отправь ID диалога" in reply_text:
        try:
            dial_id = int(answer.replace("#", ""))
            dialogue = None
            for d in dialogue_history:
                if d["id"] == dial_id:
                    dialogue = d
                    break
            
            if not dialogue:
                await message.answer("❌ Диалог не найден.", reply_markup=admin_menu())
                return
            
            msgs = dialogue.get("messages", [])
            if not msgs:
                await message.answer("📜 В этом диалоге нет сообщений.", reply_markup=admin_menu())
                return
            
            text = f"📜 Диалог #{dial_id}\n"
            text += f"Начало: {dialogue.get('start_time', '?')}\n"
            text += f"Конец: {dialogue.get('end_time', 'активен')}\n\n"
            
            for msg in msgs:
                sender = f"User {msg['sender']}"
                text += f"[{msg['timestamp']}] {sender}: {msg['content']}\n"
            
            # Разбиваем на части если слишком длинное
            if len(text) > 4000:
                parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
                for part in parts:
                    await message.answer(part)
            else:
                await message.answer(text)
            
            await message.answer("✅ Готово.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный номер диалога.", reply_markup=admin_menu())
        return
    
    # === Бан ===
    if "Отправь ID пользователя для бана" in reply_text:
        try:
            target_id = int(answer)
            if target_id == ADMIN_ID:
                await message.answer("❌ Нельзя забанить себя!", reply_markup=admin_menu())
                return
            
            banned_users.add(target_id)
            
            # Завершаем диалог и убираем из очередей
            await cleanup_user(target_id)
            
            try:
                await bot.send_message(target_id, "🚫 Вы забанены администратором.", reply_markup=types.ReplyKeyboardRemove())
            except:
                pass
            
            await message.answer(f"✅ Пользователь {target_id} забанен.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return
    
    # === Разбан ===
    if "Отправь ID для разбана" in reply_text:
        try:
            target_id = int(answer)
            if target_id in banned_users:
                banned_users.remove(target_id)
                await message.answer(f"✅ Пользователь {target_id} разбанен.", reply_markup=admin_menu())
            else:
                await message.answer(f"❌ Пользователь {target_id} не в бане.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return
    
    # === Завершение диалога ===
    if "Отправь ID пользователя для завершения диалога" in reply_text:
        try:
            target_id = int(answer)
            if target_id not in pairs:
                await message.answer(f"❌ Пользователь {target_id} не в диалоге.", reply_markup=admin_menu())
                return
            
            partner = pairs[target_id]
            await cleanup_user(target_id)
            
            try:
                await bot.send_message(target_id, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
            except:
                pass
            try:
                await bot.send_message(partner, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
            except:
                pass
            
            await message.answer(f"✅ Диалог пользователя {target_id} завершён.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return

# --- Пересылка сообщений (с логированием и уведомлением админа) ---
@dp.message(F.text & ~F.text.in_([
    "🎲 Случайный собеседник", "👨 Парень", "👩 Девушка",
    "❌ Завершить чат", "⏭ Следующий", "👤 Мой пол",
    "📊 Статистика", "👁 Читать активный диалог", "📜 История диалогов",
    "🛑 Завершить диалог", "🚫 Бан", "✅ Разбан", "👤 Обычное меню"
]))
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if message.text.startswith("/"):
        return
    
    if user_id == ADMIN_ID and user_id not in pairs:
        await message.answer("Используй кнопки админ-панели.", reply_markup=admin_menu())
        return
    
    await forward_to_partner(message)

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.video)
async def handle_video(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.audio)
async def handle_audio(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.document)
async def handle_document(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.location)
async def handle_location(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

@dp.message(F.poll)
async def handle_poll(message: types.Message):
    if is_banned(message.from_user.id): return
    await forward_to_partner(message)

async def forward_to_partner(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in pairs:
        if user_id in user_gender:
            if user_id == ADMIN_ID:
                await message.answer("Ты не в диалоге.", reply_markup=admin_menu())
            else:
                await message.answer("Ты не в диалоге.", reply_markup=menu_no_chat())
        else:
            await message.answer("Сначала нажми /start")
        return
    
    partner = pairs[user_id]
    
    # Логируем сообщение
    log_message(user_id, partner, message)
    
    # Пересылаем админу (если он читает этот диалог)
    if ADMIN_ID in user_gender:
        dialogue_id = get_dialogue_id(user_id)
        if dialogue_id is not None:
            for d_id, dialogue in enumerate(dialogue_history):
                if d_id == dialogue_id:
                    user1 = dialogue["user1"]
                    user2 = dialogue["user2"]
                    # Отправляем копию админу
                    try:
                        sender_label = f"User {user_id}"
                        if message.content_type == "text":
                            await bot.send_message(ADMIN_ID, f"👁 [#{dialogue_id}] {sender_label}: {message.text}")
                        else:
                            await message.copy_to(chat_id=ADMIN_ID, caption=f"👁 [#{dialogue_id}] {sender_label}")
                    except:
                        pass
                    break
    
    # Пересылаем собеседнику
    try:
        await message.copy_to(chat_id=partner)
    except Exception as e:
        await message.answer("❌ Не удалось отправить сообщение. Возможно, собеседник заблокировал бота.")
        await cleanup_user(user_id)
        if user_id == ADMIN_ID:
            await message.answer("Выбери режим:", reply_markup=admin_menu())
        else:
            await message.answer("Выбери режим поиска:", reply_markup=menu_no_chat())

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    asyncio.run(main())