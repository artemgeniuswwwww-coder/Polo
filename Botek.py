import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from collections import deque
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
pairs = {}
user_gender = {}
searching_status = {}

# Бан-лист
banned_users = set()

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- Меню ---

def menu_no_chat():
    """Меню когда пользователь НЕ в диалоге"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎲 Случайный собеседник"))
    builder.add(KeyboardButton(text="👨 Парень"))
    builder.add(KeyboardButton(text="👩 Девушка"))
    builder.row(KeyboardButton(text="👤 Мой пол"))
    return builder.as_markup(resize_keyboard=True)

def menu_in_chat():
    """Меню когда пользователь В диалоге"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Завершить чат"))
    builder.add(KeyboardButton(text="⏭ Следующий"))
    return builder.as_markup(resize_keyboard=True)

def admin_menu():
    """Меню админа"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📊 Статистика"))
    builder.add(KeyboardButton(text="🛑 Завершить диалог"))
    builder.add(KeyboardButton(text="🚫 Бан"))
    builder.add(KeyboardButton(text="✅ Разбан"))
    builder.row(KeyboardButton(text="👤 Обычное меню"))
    return builder.as_markup(resize_keyboard=True)

# --- Проверка бана ---
def is_banned(user_id):
    return user_id in banned_users

# --- Команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    # Проверка бана
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены в этом боте.")
        return
    
    # Админ
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

# --- Выбор пола при регистрации ---
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
        await message.answer("⛔ Вы забанены.")
        return
    
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Нельзя менять пол во время поиска. Сначала нажми ❌ Завершить чат")
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
        # Может быть в поиске
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
        await message.answer("Ты не в диалоге. Выбери режим поиска.", reply_markup=menu_no_chat())
        return
    
    await cleanup_user(user_id)
    await message.answer("🔄 Выбери режим поиска:", reply_markup=menu_no_chat())

# --- Логика поиска ---

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
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Завершить чат")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Завершить чат")
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
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Завершить чат")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Завершить чат")
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
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Завершить чат")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Завершить чат")
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
    pairs[user1] = user2
    pairs[user2] = user1
    for uid in [user1, user2]:
        if uid in searching_status:
            del searching_status[uid]

# ========================================================
#                 АДМИН-ПАНЕЛЬ
# ========================================================

# --- Обычное меню (выход из админки) ---
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
        await message.answer("⛔ Нет доступа.")
        return
    
    total_users = len(user_gender)
    men = sum(1 for g in user_gender.values() if g == "m")
    women = sum(1 for g in user_gender.values() if g == "f")
    active_pairs = len(pairs) // 2
    in_search = len(searching_status)
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"👨 Парней: {men}\n"
        f"👩 Девушек: {women}\n"
        f"💬 Активных диалогов: {active_pairs}\n"
        f"🔍 В поиске: {in_search}\n"
        f"🚫 Забанено: {len(banned_users)}"
    )
    await message.answer(stats_text, reply_markup=admin_menu())

# --- Завершить чужой диалог ---
@dp.message(F.text == "🛑 Завершить диалог")
async def admin_force_stop(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    
    await message.answer(
        "Отправь ID пользователя, чей диалог нужно завершить.\n"
        "ID можно узнать через форвард сообщения (@userinfobot) или в логах.",
        reply_markup=types.ForceReply()
    )

@dp.message(F.reply_to_message)
async def handle_reply_for_stop(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    # Проверяем, что это ответ на сообщение "Отправь ID пользователя..."
    if message.reply_to_message and message.reply_to_message.text and "Отправь ID пользователя" in message.reply_to_message.text:
        try:
            target_id = int(message.text.strip())
            
            if target_id in pairs:
                partner = pairs[target_id]
                # Завершаем диалог у обоих
                await cleanup_user(target_id)
                await cleanup_user(partner)
                await bot.send_message(target_id, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
                await bot.send_message(partner, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
                await message.answer(f"✅ Диалог пользователя {target_id} завершён.", reply_markup=admin_menu())
            else:
                await message.answer(f"❌ Пользователь {target_id} не в диалоге.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID. Отправь только цифры.", reply_markup=admin_menu())
    else:
        # Ответ на что-то другое — обрабатываем как обычное сообщение
        await forward_to_partner(message)

# --- Бан ---
@dp.message(F.text == "🚫 Бан")
async def admin_ban(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    
    await message.answer(
        "Отправь ID пользователя, которого нужно забанить.\n"
        "Он больше не сможет пользоваться ботом.",
        reply_markup=types.ForceReply()
    )

# --- Разбан ---
@dp.message(F.text == "✅ Разбан")
async def admin_unban(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    
    await message.answer(
        "Отправь ID пользователя, которого нужно разбанить.",
        reply_markup=types.ForceReply()
    )

# --- Обработка ответов админа (бан/разбан/завершение) ---
@dp.message(F.text, F.reply_to_message)
async def handle_admin_reply(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        # Обычный пользователь ответил на сообщение — пересылаем
        if user_id in pairs:
            await forward_to_partner(message)
        return
    
    if not message.reply_to_message or not message.reply_to_message.text:
        return
    
    reply_text = message.reply_to_message.text
    
    # Бан
    if "Отправь ID пользователя, которого нужно забанить" in reply_text:
        try:
            target_id = int(message.text.strip())
            if target_id == ADMIN_ID:
                await message.answer("❌ Нельзя забанить самого себя!", reply_markup=admin_menu())
                return
            
            banned_users.add(target_id)
            await cleanup_user(target_id)
            try:
                await bot.send_message(target_id, "🚫 Вы были забанены администратором.", reply_markup=types.ReplyKeyboardRemove())
            except:
                pass
            await message.answer(f"✅ Пользователь {target_id} забанен.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return
    
    # Разбан
    if "Отправь ID пользователя, которого нужно разбанить" in reply_text:
        try:
            target_id = int(message.text.strip())
            if target_id in banned_users:
                banned_users.remove(target_id)
                await message.answer(f"✅ Пользователь {target_id} разбанен.", reply_markup=admin_menu())
            else:
                await message.answer(f"❌ Пользователь {target_id} не в бане.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return
    
    # Завершение диалога
    if "Отправь ID пользователя, чей диалог нужно завершить" in reply_text:
        try:
            target_id = int(message.text.strip())
            if target_id in pairs:
                partner = pairs[target_id]
                await cleanup_user(target_id)
                await cleanup_user(partner)
                try:
                    await bot.send_message(target_id, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
                except:
                    pass
                try:
                    await bot.send_message(partner, "🛑 Администратор завершил ваш диалог.", reply_markup=menu_no_chat())
                except:
                    pass
                await message.answer(f"✅ Диалог пользователя {target_id} завершён.", reply_markup=admin_menu())
            else:
                await message.answer(f"❌ Пользователь {target_id} не в диалоге.", reply_markup=admin_menu())
        except ValueError:
            await message.answer("❌ Некорректный ID.", reply_markup=admin_menu())
        return

# --- Обработчики сообщений ---

@dp.message(F.text & ~F.text.in_([
    "🎲 Случайный собеседник", "👨 Парень", "👩 Девушка",
    "❌ Завершить чат", "⏭ Следующий", "👤 Мой пол",
    "📊 Статистика", "🛑 Завершить диалог", "🚫 Бан", "✅ Разбан", "👤 Обычное меню"
]))
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы забанены.")
        return
    
    if message.text.startswith("/"):
        return
    
    # Если админ — не пересылаем его сообщения (если только он не в диалоге)
    if user_id == ADMIN_ID and user_id not in pairs:
        await message.answer("Используй кнопки админ-панели или войди в диалог.", reply_markup=admin_menu())
        return
    
    await forward_to_partner(message)

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.video)
async def handle_video(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.audio)
async def handle_audio(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.document)
async def handle_document(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.location)
async def handle_location(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

@dp.message(F.poll)
async def handle_poll(message: types.Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы забанены.")
        return
    await forward_to_partner(message)

async def forward_to_partner(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in pairs:
        if user_id in user_gender:
            if user_id == ADMIN_ID:
                await message.answer("Ты не в диалоге.", reply_markup=admin_menu())
            else:
                await message.answer("Ты не в диалоге. Выбери режим поиска.", reply_markup=menu_no_chat())
        else:
            await message.answer("Сначала нажми /start")
        return
    
    partner = pairs[user_id]
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