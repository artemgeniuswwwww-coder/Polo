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
wait_men = deque()
wait_women = deque()
wait_any = deque()  # Очередь для "случайного собеседника" (без учёта пола)

# Текущие пары: {user_id: partner_id}
pairs = {}

# Пол пользователя: {user_id: "m"/"f"/None}
user_gender = {}

# Флаг первого запуска: {user_id: True/False}
first_time = set()

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
    builder.add(KeyboardButton(text="👨 Мужчина"))
    builder.add(KeyboardButton(text="👩 Женщина"))
    builder.add(KeyboardButton(text="❌ Стоп"))
    builder.add(KeyboardButton(text="⏭ Следующий собеседник"))
    builder.adjust(1, 2, 2)  # Первый ряд — 1 кнопка, второй — 2, третий — 2
    return builder.as_markup(resize_keyboard=True)

# --- Команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    # Если пользователь уже был — сразу показываем меню
    if user_id in user_gender:
        # Очищаем старые связи
        await cleanup_user(user_id)
        await message.answer(
            "С возвращением! Выберите режим поиска:",
            reply_markup=main_menu()
        )
        return
    
    # Первый запуск — просим выбрать пол
    await message.answer(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Администратор технически имеет доступ к логам сервера. "
        "Не передавайте личные данные.\n\n"
        "Сначала выберите свой пол (это нужно только один раз):",
        reply_markup=gender_select_keyboard()
    )

# --- Клавиатура выбора пола (только для первого раза) ---
def gender_select_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="👨 Я парень", callback_data="first_gender_m"))
    builder.add(InlineKeyboardButton(text="👩 Я девушка", callback_data="first_gender_f"))
    builder.adjust(2)
    return builder.as_markup()

# --- Сохранение пола при первом запуске ---
@dp.callback_query(F.data.startswith("first_gender_"))
async def save_first_gender(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    gender = callback.data.split("_")[2]  # m или f
    user_gender[user_id] = gender
    
    await callback.message.edit_text(f"✅ Пол сохранён: {'парень' if gender == 'm' else 'девушка'}")
    await callback.message.answer(
        "Теперь выберите, кого искать:",
        reply_markup=main_menu()
    )
    await callback.answer()

# --- Очистка состояния пользователя ---
async def cleanup_user(user_id):
    """Убирает пользователя из очередей и завершает диалог"""
    # Удаляем из очередей
    if user_id in wait_men:
        wait_men.remove(user_id)
    if user_id in wait_women:
        wait_women.remove(user_id)
    if user_id in wait_any:
        wait_any.remove(user_id)
    
    # Завершаем диалог
    if user_id in pairs:
        partner = pairs.pop(user_id)
        if partner in pairs and pairs[partner] == user_id:
            pairs.pop(partner)
            try:
                await bot.send_message(partner, "❌ Собеседник покинул чат.\nВыберите новый режим поиска:", reply_markup=main_menu())
            except:
                pass

# --- Завершение диалога (кнопка Стоп) ---
@dp.message(F.text == "❌ Стоп")
async def stop_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    await message.answer("✅ Диалог завершён. Выберите новый режим поиска:", reply_markup=main_menu())

# --- Следующий собеседник (завершает текущий диалог и ищет нового) ---
@dp.message(F.text == "⏭ Следующий собеседник")
async def next_partner_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    # Сбрасываем текущий диалог
    await cleanup_user(user_id)
    await message.answer("🔄 Ищем нового собеседника... Выберите режим:", reply_markup=main_menu())

# --- Обработка кнопок поиска ---
@dp.message(F.text == "🎲 Случайный собеседник")
async def search_any(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    
    # Если кто-то уже ждёт "случайного"
    if wait_any:
        partner = wait_any.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Собеседник найден! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
    else:
        wait_any.append(user_id)
        await message.answer("🔍 Ищу случайного собеседника... Ожидайте.", reply_markup=main_menu())

@dp.message(F.text == "👨 Мужчина")
async def search_man(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    
    # Ищем в очереди мужчин (тех, кто сам выбрал роль "мужчина" и хочет общаться)
    if wait_men:
        partner = wait_men.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Мужчина найден! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
    else:
        wait_men.append(user_id)
        await message.answer("🔍 Ищу мужчину... Ожидайте.", reply_markup=main_menu())

@dp.message(F.text == "👩 Женщина")
async def search_woman(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    
    if wait_women:
        partner = wait_women.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Женщина найдена! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.\nДля завершения нажмите ❌ Стоп", reply_markup=main_menu())
    else:
        wait_women.append(user_id)
        await message.answer("🔍 Ищу женщину... Ожидайте.", reply_markup=main_menu())

# --- Соединение пары ---
async def connect_pair(user1, user2):
    pairs[user1] = user2
    pairs[user2] = user1

# --- Пересылка сообщений ---
@dp.message(F.text & ~F.text.startswith("/") & ~F.text.in_(["🎲 Случайный собеседник", "👨 Мужчина", "👩 Женщина", "❌ Стоп", "⏭ Следующий собеседник"]))
async def chat_message(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pairs:
        # Если не в диалоге и пол уже выбран — напоминаем про меню
        if user_id in user_gender:
            await message.answer("Вы не в диалоге. Используйте кнопки меню для поиска.", reply_markup=main_menu())
        else:
            await message.answer("Сначала нажмите /start")
        return
    
    partner = pairs[user_id]
    try:
        await bot.send_message(partner, f"💬 {message.text}")
    except Exception as e:
        await message.answer("❌ Не удалось отправить сообщение. Возможно, собеседник заблокировал бота.")
        await cleanup_user(user_id)
        await message.answer("Выберите режим поиска:", reply_markup=main_menu())

# --- Команда /stop (для совместимости) ---
@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    await stop_button(message)

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    asyncio.run(main())