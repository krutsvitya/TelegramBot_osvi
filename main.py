from datetime import datetime
import asyncio

from aiogram import F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from zoneinfo import ZoneInfo

from config import TOKEN, TEACHER_ID, ReplyState, bot, dp
from db import log_curator_action, log_message, init_db

if not TOKEN or not TEACHER_ID:
    raise ValueError("BOT_TOKEN або TEACHER_ID не знайдено в .env файлі")

# Зберігаємо запити (для тесту)
requests = {}

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Привіт! Надішліть свій запит, і вчитель отримає його.")


@dp.message(ReplyState.waiting_for_reply)
async def process_reply(message: Message, state: FSMContext):
    """Куратор відповідає, бот пересилає відповідь студенту."""

    print(f"✅ Обробник відповіді спрацював! Отримано відповідь від куратора: '{message.text}'")

    if message.from_user.id != TEACHER_ID:
        print("❌ Не куратор пише повідомлення в режимі відповіді! Ігноруємо.")
        return

    data = await state.get_data()
    print(f"📝 Дані стану: {data}")

    request_id = data.get("request_id")
    if not request_id or request_id not in requests:
        await message.answer("⚠ Помилка: Запит не знайдено.")
        await state.clear()
        return

    curator_id = message.from_user.id
    await log_message(request_id, curator_id, "curator", message.text)

    student_id = requests[request_id]["student_id"]
    print(f"📊 Надсилаємо відповідь студенту з ID: {student_id}")

    try:
        await bot.send_message(
            chat_id=student_id,
            text=f"📩 Відповідь від куратора:\n\n{message.text}"
        )
        print(f"✅ Відповідь успішно надіслано студенту {student_id}")

        if requests[request_id]["status"] != "У роботі":
            requests[request_id]["status"] = "У роботі"
            requests[request_id]["curator_id"] = message.from_user.id

        if "messages" not in requests[request_id]:
            requests[request_id]["messages"] = []

        requests[request_id]["messages"].append({
            "from": "curator",
            "text": message.text,
            "time": message.date.isoformat()
        })

        await message.answer("✅ Відповідь надіслано студенту.")
    except Exception as e:
        print(f"❌ Помилка при надсиланні відповіді студенту: {e}")
        await message.answer(f"⚠ Помилка при надсиланні відповіді: {e}")

    await state.clear()


@dp.message()
async def handle_student_request(message: Message, state: FSMContext):
    """Обробляємо повідомлення від студента та надсилаємо його куратору."""
    print(f"⚠️ Загальний обробник повідомлень. ID: {message.from_user.id}, Текст: '{message.text}'")

    current_state = await state.get_state()
    print(f"⚠️ Поточний стан: {current_state}")

    if current_state is not None:
        print("⚠️ Є активний стан, пропускаємо загальний обробник")
        return

    student_id = message.from_user.id

    if message.from_user.id == TEACHER_ID:
        return

    student_name = message.from_user.full_name

    active_request_id = None
    for req_id, req_data in requests.items():
        if req_data["student_id"] == student_id and req_data["status"] != "Завершено":
            active_request_id = req_id
            break

    if active_request_id:
        curator_id = requests[active_request_id].get("curator_id")

        recipient_id = curator_id if curator_id else TEACHER_ID
        request_id = str(message.message_id)
        curator_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Відповісти", callback_data=f"reply_{active_request_id}")],
                [InlineKeyboardButton(text="Завершити діалог", callback_data=f"finish_{active_request_id}")],
                [InlineKeyboardButton(text="Поставити на утримання", callback_data=f"hold_{active_request_id}")]
            ]
        )

        await bot.send_message(
            recipient_id,
            f"📩 **Нове повідомлення від {student_name}**\n\n"
            f"📝 *{message.text}*\n"
            f"🔄 Статус: {requests[active_request_id]['status']}",
            reply_markup=curator_keyboard,
            parse_mode="Markdown"
        )

        await message.answer("✅ Ваше повідомлення додано до активного запиту.")
        return

    request_id = str(message.message_id)

    await log_message(request_id, student_id, "student", message.text)

    requests[request_id] = {
        "student_id": student_id,
        "student_name": student_name,
        "text": message.text,
        "status": "Очікує обробки",
        "curator_id": None,
        "messages": [{"from": "student", "text": message.text, "time": message.date.isoformat()}]
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Взяти в роботу", callback_data=f"take_{request_id}")],
            [InlineKeyboardButton(text="Завершити діалог", callback_data=f"finish_{request_id}")],
            [InlineKeyboardButton(text="Переназначити куратора", callback_data=f"reassign_{request_id}")],
            [InlineKeyboardButton(text="Поставити на утримання", callback_data=f"hold_{request_id}")]
        ]
    )

    await bot.send_message(
        TEACHER_ID,
        f"📩 **Новий запит від {student_name}**\n\n"
        f"📝 *{message.text}*\n"
        f"⏳ Статус: Очікує обробки",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    await message.answer("✅ Ваш запит надіслано куратору. Очікуйте відповідь.")


@dp.callback_query(F.data.startswith("reply_"))
async def ask_for_reply(callback_query: CallbackQuery, state: FSMContext):
    """Куратор натискає 'Відповісти'."""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    print(f"🔍 Натиснуто кнопку 'Відповісти'. request_id={request_id}, curator_id={curator_id}")

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    await state.update_data(request_id=request_id)
    print(f"💾 Збережено в стані: request_id={request_id}")

    await callback_query.answer()

    await state.set_state(ReplyState.waiting_for_reply)
    print("🔄 Встановлено стан: waiting_for_reply")

    await bot.send_message(
        curator_id,
        "Напишіть вашу відповідь для студента:"
    )


@dp.callback_query(F.data.startswith("take_"))
async def take_request(callback_query: CallbackQuery, state: FSMContext):
    """Куратор бере запит у роботу"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    take_time = datetime.now(ZoneInfo("Europe/Kiev"))
    request_time = datetime.fromisoformat(requests[request_id]["messages"][0]["time"]).astimezone(
        ZoneInfo("Europe/Kiev"))
    reaction_time = take_time - request_time

    reaction_seconds = int(reaction_time.total_seconds())
    print(f"Секунди реакції: {reaction_seconds}")

    await log_curator_action(request_id, curator_id, "взяв у роботу")

    if reaction_seconds < 60:
        reaction_str = "1 хвилина"
    elif reaction_seconds < 3600:
        reaction_minutes = reaction_seconds // 60
        reaction_str = f"{reaction_minutes} хвилин"
    else:
        reaction_hours = reaction_seconds // 3600
        remaining_seconds = reaction_seconds % 3600
        reaction_minutes = remaining_seconds // 60
        reaction_str = f"{reaction_hours} година {reaction_minutes} хвилин"

    requests[request_id]["reaction_time"] = reaction_str

    requests[request_id]["status"] = "У роботі"
    requests[request_id]["curator_id"] = curator_id

    await callback_query.answer("Ви взяли запит у роботу")
    await log_message(request_id, callback_query.from_user.id, "curator", callback_query.message.text)

    curator_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Відповісти", callback_data=f"reply_{request_id}")],
            [InlineKeyboardButton(text="Завершити діалог", callback_data=f"finish_{request_id}")],
            [InlineKeyboardButton(text="Поставити на утримання", callback_data=f"hold_{request_id}")]
        ]
    )

    curator_name = callback_query.from_user.full_name

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=f"📩 **Запит від {requests[request_id].get('student_name', 'студента')}**\n\n"
             f"📝 *{requests[request_id]['text']}*\n"
             f"🔄 Статус: У роботі\n"
             f"👨‍💼 Куратор: {curator_name}\n"
             f"⏱ Час взяття в роботу: {take_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
             f"⚡ Швидкість реакції: {reaction_str}",
        reply_markup=curator_keyboard,
        parse_mode="Markdown"
    )

    await bot.send_message(
        requests[request_id]["student_id"],
        f"✅ Ваш запит взято у роботу. Куратор: {curator_name}"
    )


@dp.callback_query(F.data.startswith("finish_"))
async def finish_request(callback_query: CallbackQuery):
    """Завершити діалог"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    if requests[request_id].get("curator_id") != curator_id:
        await callback_query.answer("Тільки куратор, який взяв запит, може його завершити")
        return

    requests[request_id]["status"] = "Завершено"

    await callback_query.answer("Діалог завершено")

    await log_curator_action(request_id, curator_id, "Завершив діалог")

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=f"📩 **Запит від {requests[request_id].get('student_name', 'студента')}**\n\n"
             f"📝 *{requests[request_id]['text']}*\n"
             f"✅ Статус: Завершено\n"
             f"👨‍💼 Куратор: {callback_query.from_user.full_name}",
        parse_mode="Markdown"
    )

    await bot.send_message(
        requests[request_id]["student_id"],
        "✅ Ваш запит було закрито. Дякуємо за звернення!"
    )


@dp.callback_query(F.data.startswith("reassign_"))
async def reassign_request(callback_query: CallbackQuery, state: FSMContext):
    """Переназначити куратора"""
    request_id = callback_query.data.split("_")[1]

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return
    curator_id = callback_query.from_user.id
    # Тут треба додати логіку вибору нового куратора
    await log_curator_action(request_id, curator_id, "Переназначено куратора")
    await callback_query.answer("Функція переназначення куратора у розробці")


@dp.callback_query(F.data.startswith("hold_"))
async def hold_request(callback_query: CallbackQuery):
    """Поставити запит на утримання"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    requests[request_id]["status"] = "Очікує"

    await callback_query.answer("Запит поставлено на утримання")
    await log_curator_action(request_id, curator_id, "Поставлено запит на утримання")

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=f"📩 **Запит від {requests[request_id].get('student_name', 'студента')}**\n\n"
             f"📝 *{requests[request_id]['text']}*\n"
             f"⏳ Статус: Очікує\n"
             f"👨‍💼 Куратор: {callback_query.from_user.full_name}",
        reply_markup=callback_query.message.reply_markup,
        parse_mode="Markdown"
    )

    await bot.send_message(
        requests[request_id]["student_id"],
        "⏳ Куратори зараз не поруч. Ваш запит поставлено на утримання."
    )


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())