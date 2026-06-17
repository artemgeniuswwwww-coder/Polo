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
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Очереди ожидания
wait_men = deque()    # Пользователи, которые ждут мужчину
wait_women = deque()  # Пользователи, которые ждут женщину
wait_any = deque()    # Пользователи, которые ждут случайного

# Пары и пол пользователей
pairs = {}
user_gender = {}

# Статус поиска: user_id -> "searching" или None
searching_status = {}

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- Главное меню ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎲 Случайный собеседник"))
    builder.add(KeyboardButton(text="👨 Парень"))
    builder.add(KeyboardButton(text="👩 Девушка"))
    builder.row(KeyboardButton(text="⏭ Следующий"))
    builder.row(KeyboardButton(text="👤 Мой пол"), KeyboardButton(text="❌ Стоп"))
    return builder.as_markup(resize_keyboard=True)

# --- Команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in user_gender:
        await cleanup_user(user_id)
        await message.answer(
            "С возвращением!",
            reply_markup=main_menu()
        )
        return
    
    await message.answer(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "Выбери свой пол:",
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
    gender = callback.data.split("_")[2]
    user_gender[user_id] = gender
    
    await callback.message.edit_text(f"✅ Твой пол: {'парень' if gender == 'm' else 'девушка'}")
    await callback.message.answer(
        "Готово! Выбирай режим поиска:",
        reply_markup=main_menu()
    )
    await callback.answer()

# --- Кнопка смены пола ---
@dp.message(F.text == "👤 Мой пол")
async def change_gender_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    # Не даём менять пол во время поиска
    if user_id in searching_status:
        await message.answer("❌ Нельзя менять пол во время поиска. Сначала нажми ❌ Стоп")
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
    await callback.message.answer("Выбирай режим поиска:", reply_markup=main_menu())
    await callback.answer()

# --- Очистка состояния пользователя ---
async def cleanup_user(user_id):
    # Удаляем из очередей
    if user_id in wait_men: wait_men.remove(user_id)
    if user_id in wait_women: wait_women.remove(user_id)
    if user_id in wait_any: wait_any.remove(user_id)
    
    # Убираем статус поиска
    if user_id in searching_status:
        del searching_status[user_id]
    
    # Завершаем диалог
    if user_id in pairs:
        partner = pairs.pop(user_id)
        if partner in pairs and pairs[partner] == user_id:
            pairs.pop(partner)
            try:
                await bot.send_message(partner, "❌ Собеседник покинул чат.", reply_markup=main_menu())
            except:
                pass

# --- Стоп ---
@dp.message(F.text == "❌ Стоп")
async def stop_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    was_searching = user_id in searching_status
    was_in_pair = user_id in pairs
    
    await cleanup_user(user_id)
    
    if was_searching and not was_in_pair:
        await message.answer("🔍 Поиск остановлен.", reply_markup=main_menu())
    elif was_in_pair:
        await message.answer("✅ Диалог завершён.", reply_markup=main_menu())
    else:
        await message.answer("Ты не в диалоге и не в поиске.", reply_markup=main_menu())

# --- Следующий ---
@dp.message(F.text == "⏭ Следующий")
async def next_partner_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id not in pairs and user_id not in searching_status:
        await message.answer("Ты не в диалоге. Сначала выбери режим поиска.")
        return
    
    await cleanup_user(user_id)
    await message.answer("🔄 Выбери режим поиска:", reply_markup=main_menu())

# --- Логика поиска ---

@dp.message(F.text == "🎲 Случайный собеседник")
async def search_any(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    # Проверка: уже в поиске или в диалоге
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Стоп")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Стоп или ⏭ Следующий")
        return
    
    await cleanup_user(user_id)
    
    # Ищем среди ВСЕХ ожидающих (любой пол + конкретные очереди)
    # Приоритет: сначала таких же "случайных", потом из конкретных очередей
    
    partner = None
    
    # 1. Ищем среди тех, кто тоже нажал "Случайный"
    if wait_any:
        partner = wait_any.popleft()
    # 2. Ищем среди тех, кто ждёт конкретный пол
    elif user_gender[user_id] == "m" and wait_men:
        partner = wait_men.popleft()
    elif user_gender[user_id] == "f" and wait_women:
        partner = wait_women.popleft()
    # 3. Ищем среди противоположной очереди (если парень — среди ждущих женщину, и наоборот)
    elif user_gender[user_id] == "m" and wait_women:
        partner = wait_women.popleft()
    elif user_gender[user_id] == "f" and wait_men:
        partner = wait_men.popleft()
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Собеседник найден! Общайтесь.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=main_menu())
    else:
        wait_any.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу случайного собеседника...", reply_markup=main_menu())

@dp.message(F.text == "👨 Парень")
async def search_man(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Стоп")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Стоп или ⏭ Следующий")
        return
    
    await cleanup_user(user_id)
    
    partner = None
    
    # Ищем среди всех, кто может подойти
    # 1. Те, кто нажал "Случайный" и подходит по полу
    for waiting_user in list(wait_any):
        if user_gender.get(waiting_user) == "m":
            wait_any.remove(waiting_user)
            partner = waiting_user
            break
    
    # 2. Те, кто конкретно ждёт парня
    if not partner and wait_men:
        partner = wait_men.popleft()
    
    # 3. Девушки, которые ждут случайного (любого пола)
    if not partner:
        for waiting_user in list(wait_any):
            if user_gender.get(waiting_user) == "f":
                wait_any.remove(waiting_user)
                partner = waiting_user
                break
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Парень найден! Общайтесь.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=main_menu())
    else:
        wait_men.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу парня...", reply_markup=main_menu())

@dp.message(F.text == "👩 Девушка")
async def search_woman(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажми /start")
        return
    
    if user_id in searching_status:
        await message.answer("❌ Ты уже в поиске! Дождись или нажми ❌ Стоп")
        return
    if user_id in pairs:
        await message.answer("❌ Ты уже в диалоге! Сначала нажми ❌ Стоп или ⏭ Следующий")
        return
    
    await cleanup_user(user_id)
    
    partner = None
    
    # Ищем среди всех, кто может подойти
    # 1. Те, кто нажал "Случайный" и подходит по полу
    for waiting_user in list(wait_any):
        if user_gender.get(waiting_user) == "f":
            wait_any.remove(waiting_user)
            partner = waiting_user
            break
    
    # 2. Те, кто конкретно ждёт девушку
    if not partner and wait_women:
        partner = wait_women.popleft()
    
    # 3. Парни, которые ждут случайного (любого пола)
    if not partner:
        for waiting_user in list(wait_any):
            if user_gender.get(waiting_user) == "m":
                wait_any.remove(waiting_user)
                partner = waiting_user
                break
    
    if partner:
        await connect_pair(user_id, partner)
        await message.answer("✅ Девушка найдена! Общайтесь.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь.", reply_markup=main_menu())
    else:
        wait_women.append(user_id)
        searching_status[user_id] = "searching"
        await message.answer("🔍 Ищу девушку...", reply_markup=main_menu())

async def connect_pair(user1, user2):
    pairs[user1] = user2
    pairs[user2] = user1
    # Убираем статус поиска
    for uid in [user1, user2]:
        if uid in searching_status:
            del searching_status[uid]

# --- Обработчики всех типов сообщений ---

@dp.message(F.text & ~F.text.in_(["🎲 Случайный собеседник", "👨 Парень", "👩 Девушка", "❌ Стоп", "⏭ Следующий", "👤 Мой пол"]))
async def handle_text(message: types.Message):
    if message.text.startswith("/"): return
    await forward_to_partner(message)

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.video)
async def handle_video(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.audio)
async def handle_audio(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.document)
async def handle_document(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.location)
async def handle_location(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    await forward_to_partner(message)

@dp.message(F.poll)
async def handle_poll(message: types.Message):
    await forward_to_partner(message)

async def forward_to_partner(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in pairs:
        if user_id in user_gender:
            await message.answer("Ты не в диалоге. Выбери режим поиска.", reply_markup=main_menu())
        else:
            await message.answer("Сначала нажми /start")
        return
    
    partner = pairs[user_id]
    try:
        await message.copy_to(chat_id=partner)
    except Exception as e:
        await message.answer("❌ Не удалось отправить сообщение. Возможно, собеседник заблокировал бота.")
        await cleanup_user(user_id)
        await message.answer("Выбери режим поиска:", reply_markup=main_menu())

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    asyncio.run(main())