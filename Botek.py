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
wait_any = deque()

# Пары и пол пользователей
pairs = {}
user_gender = {}

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
    builder.row(KeyboardButton(text="⏭ Следующий собеседник"))
    builder.row(KeyboardButton(text="👤 Мой пол"), KeyboardButton(text="❌ Стоп"))
    return builder.as_markup(resize_keyboard=True)

# --- Команда /start ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in user_gender:
        await cleanup_user(user_id)
        await message.answer(
            "С возвращением! Выберите режим поиска:",
            reply_markup=main_menu()
        )
        return
    
    # Первый запуск
    await message.answer(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "Сначала выберите свой пол:",
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
    
    await callback.message.edit_text(f"✅ Пол сохранён: {'парень' if gender == 'm' else 'девушка'}")
    await callback.message.answer(
        "Теперь выберите, кого искать:",
        reply_markup=main_menu()
    )
    await callback.answer()

# --- Кнопка смены пола ---
@dp.message(F.text == "👤 Мой пол")
async def change_gender_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    current = "парень" if user_gender[user_id] == "m" else "девушка"
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="👨 Парень", callback_data="change_gender_m"))
    builder.add(InlineKeyboardButton(text="👩 Девушка", callback_data="change_gender_f"))
    builder.adjust(2)
    await message.answer(f"Ваш текущий пол: {current}\nВыберите новый:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("change_gender_"))
async def change_gender(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    gender = callback.data.split("_")[2]
    
    # Очищаем старые чаты и очереди перед сменой пола
    await cleanup_user(user_id)
    
    user_gender[user_id] = gender
    await callback.message.edit_text(f"✅ Пол изменён на: {'парень' if gender == 'm' else 'девушка'}")
    await callback.message.answer("Выберите режим поиска:", reply_markup=main_menu())
    await callback.answer()

# --- Очистка состояния пользователя ---
async def cleanup_user(user_id):
    # Удаляем из очередей
    if user_id in wait_men: wait_men.remove(user_id)
    if user_id in wait_women: wait_women.remove(user_id)
    if user_id in wait_any: wait_any.remove(user_id)
    
    # Завершаем диалог
    if user_id in pairs:
        partner = pairs.pop(user_id)
        if partner in pairs and pairs[partner] == user_id:
            pairs.pop(partner)
            try:
                await bot.send_message(partner, "❌ Собеседник покинул чат.\nВыберите новый режим поиска:", reply_markup=main_menu())
            except:
                pass

# --- Кнопка Стоп ---
@dp.message(F.text == "❌ Стоп")
async def stop_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    await message.answer("✅ Диалог завершён. Выберите новый режим поиска:", reply_markup=main_menu())

# --- Кнопка Следующий собеседник ---
@dp.message(F.text == "⏭ Следующий собеседник")
async def next_partner_button(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender:
        await message.answer("Сначала нажмите /start")
        return
    
    await cleanup_user(user_id)
    await message.answer("🔄 Ищем нового собеседника... Выберите режим:", reply_markup=main_menu())

# --- Логика поиска (одинаковая для всех кнопок) ---
@dp.message(F.text == "🎲 Случайный собеседник")
async def search_any(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender: return
    
    await cleanup_user(user_id)
    
    if wait_any:
        partner = wait_any.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Собеседник найден! Общайтесь анонимно.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.", reply_markup=main_menu())
    else:
        wait_any.append(user_id)
        await message.answer("🔍 Ищу случайного собеседника... Ожидайте.", reply_markup=main_menu())

@dp.message(F.text == "👨 Мужчина")
async def search_man(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender: return
    
    await cleanup_user(user_id)
    
    if wait_men:
        partner = wait_men.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Мужчина найден! Общайтесь анонимно.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.", reply_markup=main_menu())
    else:
        wait_men.append(user_id)
        await message.answer("🔍 Ищу мужчину... Ожидайте.", reply_markup=main_menu())

@dp.message(F.text == "👩 Женщина")
async def search_woman(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_gender: return
    
    await cleanup_user(user_id)
    
    if wait_women:
        partner = wait_women.popleft()
        await connect_pair(user_id, partner)
        await message.answer("✅ Женщина найдена! Общайтесь анонимно.", reply_markup=main_menu())
        await bot.send_message(partner, "✅ Собеседник найден! Общайтесь анонимно.", reply_markup=main_menu())
    else:
        wait_women.append(user_id)
        await message.answer("🔍 Ищу женщину... Ожидайте.", reply_markup=main_menu())

async def connect_pair(user1, user2):
    pairs[user1] = user2
    pairs[user2] = user1

# --- Обработчики всех типов сообщений (пересылка) ---

# 1. Текст (исключаем кнопки меню и команды)
@dp.message(F.text & ~F.text.in_(["🎲 Случайный собеседник", "👨 Мужчина", "👩 Женщина", "❌ Стоп", "⏭ Следующий собеседник", "👤 Мой пол"]))
async def handle_text(message: types.Message):
    if message.text.startswith("/"): return  # Игнорируем команды
    await forward_to_partner(message)

# 2. Фото
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    await forward_to_partner(message)

# 3. Видео
@dp.message(F.video)
async def handle_video(message: types.Message):
    await forward_to_partner(message)

# 4. Голосовые сообщения
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await forward_to_partner(message)

# 5. Видеосообщения (кружочки)
@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    await forward_to_partner(message)

# 6. Стикеры
@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    await forward_to_partner(message)

# 7. Аудио (музыка)
@dp.message(F.audio)
async def handle_audio(message: types.Message):
    await forward_to_partner(message)

# 8. Документы/файлы
@dp.message(F.document)
async def handle_document(message: types.Message):
    await forward_to_partner(message)

# 9. Геолокация
@dp.message(F.location)
async def handle_location(message: types.Message):
    await forward_to_partner(message)

# 10. Контакты
@dp.message(F.contact)
async def handle_contact(message: types.Message):
    await forward_to_partner(message)

# 11. Опросы (если пересылают)
@dp.message(F.poll)
async def handle_poll(message: types.Message):
    await forward_to_partner(message)

# --- Универсальная функция пересылки ---
async def forward_to_partner(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in pairs:
        if user_id in user_gender:
            await message.answer("Вы не в диалоге. Используйте кнопки меню для поиска.", reply_markup=main_menu())
        else:
            await message.answer("Сначала нажмите /start")
        return
    
    partner = pairs[user_id]
    try:
        # Просто копируем сообщение собеседнику (без изменений)
        await message.copy_to(chat_id=partner)
    except Exception as e:
        await message.answer("❌ Не удалось отправить сообщение. Возможно, собеседник заблокировал бота.")
        await cleanup_user(user_id)
        await message.answer("Выберите режим поиска:", reply_markup=main_menu())

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    asyncio.run(main())