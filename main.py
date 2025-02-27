from datetime import datetime
import asyncio

from aiogram import F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from zoneinfo import ZoneInfo

from config import TOKEN, TEACHERS_IDS, ADMIN_ID, CURATOR_CHAT_ID, ReplyState, TeacherState, bot, dp
from db import (
    log_curator_action, log_message, init_db,
    get_all_teachers, add_teacher, deactivate_teacher,
    is_teacher, get_teacher_by_id
)

if not TOKEN or not TEACHERS_IDS or not CURATOR_CHAT_ID:
    raise ValueError("BOT_TOKEN, TEACHERS_IDS або CURATOR_CHAT_ID не знайдено в .env файлі")

# Зберігаємо запити
requests = {}
# Track thread IDs for each request
request_threads = {}


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Привіт! Надішліть свій запит, і вчитель отримає його.")


@dp.message(Command("teachers"))
async def list_teachers(message: Message):
    """Показать список учителей (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас немає прав для виконання цієї команди.")
        return

    teachers = await get_all_teachers()

    if not teachers:
        await message.answer("Список учителів порожній.")
        return

    text = "📋 Список учителів:\n\n"
    for i, teacher in enumerate(teachers, 1):
        text += f"{i}. {teacher.full_name}"
        if teacher.username:
            text += f" (@{teacher.username})"
        text += f" - ID: {teacher.telegram_id}\n"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Додати вчителя", callback_data="add_teacher")],
            [InlineKeyboardButton(text="➖ Видалити вчителя", callback_data="remove_teacher")]
        ]
    )

    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "add_teacher")
async def add_teacher_request(callback_query: CallbackQuery, state: FSMContext):
    """Запросить данные для добавления учителя"""
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    await callback_query.answer()
    await state.set_state(TeacherState.waiting_for_new_teacher)
    await bot.send_message(
        callback_query.from_user.id,
        "Надішліть ID нового вчителя в форматі:\n1234567890, Ім'я Прізвище"
    )


@dp.callback_query(F.data == "remove_teacher")
async def remove_teacher_request(callback_query: CallbackQuery, state: FSMContext):
    """Запросить данные для удаления учителя"""
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    await callback_query.answer()
    await state.set_state(TeacherState.waiting_for_teacher_removal)
    await bot.send_message(
        callback_query.from_user.id,
        "Надішліть ID вчителя, якого потрібно видалити:"
    )


@dp.message(TeacherState.waiting_for_new_teacher)
async def process_add_teacher(message: Message, state: FSMContext):
    """Обработать добавление нового учителя"""
    if message.from_user.id != ADMIN_ID:
        return

    try:
        parts = message.text.split(',', 1)
        if len(parts) != 2:
            await message.answer("Неправильний формат. Використовуйте: ID, Ім'я Прізвище")
            return

        telegram_id = int(parts[0].strip())
        full_name = parts[1].strip()

        existing_teacher = await get_teacher_by_id(telegram_id)
        if existing_teacher:
            await message.answer(f"Учитель з ID {telegram_id} вже існує.")
            await state.clear()
            return

        success = await add_teacher(
            telegram_id=telegram_id,
            username=None,
            full_name=full_name
        )

        if success:
            if telegram_id not in TEACHERS_IDS:
                TEACHERS_IDS.append(telegram_id)

            await message.answer(f"✅ Учитель {full_name} (ID: {telegram_id}) успішно доданий.")
        else:
            await message.answer("❌ Помилка при додаванні вчителя.")

    except ValueError:
        await message.answer("Неправильний формат ID. ID повинен бути числом.")
    finally:
        await state.clear()


@dp.message(TeacherState.waiting_for_teacher_removal)
async def process_remove_teacher(message: Message, state: FSMContext):
    """Обработать удаление учителя"""
    if message.from_user.id != ADMIN_ID:
        return

    try:
        telegram_id = int(message.text.strip())

        existing_teacher = await get_teacher_by_id(telegram_id)
        if not existing_teacher:
            await message.answer(f"Учитель з ID {telegram_id} не знайдений.")
            await state.clear()
            return

        success = await deactivate_teacher(telegram_id)

        if success:
            if telegram_id in TEACHERS_IDS:
                TEACHERS_IDS.remove(telegram_id)

            await message.answer(f"✅ Учитель {existing_teacher.full_name} (ID: {telegram_id}) успішно видалений.")
        else:
            await message.answer("❌ Помилка при видаленні вчителя.")

    except ValueError:
        await message.answer("Неправильний формат ID. ID повинен бути числом.")
    finally:
        await state.clear()


@dp.message(ReplyState.waiting_for_reply)
async def process_reply(message: Message, state: FSMContext):
    """Куратор відповідає, бот пересилає відповідь студенту."""

    print(f"✅ Обробник відповіді спрацював! Отримано відповідь від куратора: '{message.text}'")

    if message.from_user.id not in TEACHERS_IDS:
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

        # Додаємо відповідь у тред
        thread_id = request_threads.get(request_id)
        if thread_id:
            await bot.send_message(
                chat_id=CURATOR_CHAT_ID,
                message_thread_id=thread_id,
                text=f"💬 Куратор @{message.from_user.username or message.from_user.full_name} відповів:\n\n{message.text}"
            )

    except Exception as e:
        print(f"❌ Помилка при надсиланні відповіді студенту: {e}")
        await message.answer(f"⚠ Помилка при надсиланні відповіді: {e}")

    await state.clear()


@dp.message()
async def handle_student_request(message: Message, state: FSMContext):
    """Обробляємо повідомлення від студента та створюємо тред у чаті кураторів."""
    print(f"⚠️ Загальний обробник повідомлень. ID: {message.from_user.id}, Текст: '{message.text}'")

    current_state = await state.get_state()
    print(f"⚠️ Поточний стан: {current_state}")

    if current_state is not None:
        print("⚠️ Є активний стан, пропускаємо загальний обробник")
        return

    student_id = message.from_user.id

    # Проверяем, что сообщение не от куратора и не пустое
    if message.from_user.id in TEACHERS_IDS or not message.text:
        return

    student_name = message.from_user.full_name
    student_username = message.from_user.username

    active_request_id = None
    for req_id, req_data in requests.items():
        if req_data["student_id"] == student_id and req_data["status"] != "Завершено":
            active_request_id = req_id
            break

    if active_request_id:
        # Додаємо повідомлення до активного запиту
        if "messages" not in requests[active_request_id]:
            requests[active_request_id]["messages"] = []

        requests[active_request_id]["messages"].append({
            "from": "student",
            "text": message.text,
            "time": message.date.isoformat()
        })

        await log_message(active_request_id, student_id, "student", message.text)

        # Додаємо повідомлення студента у відповідний тред
        thread_id = request_threads.get(active_request_id)
        if thread_id:
            # Пошук і видалення клавіатури з останнього повідомлення куратора у треді
            try:
                # Спробуємо отримати всі повідомлення в треді
                messages = await bot.get_chat_history(
                    chat_id=CURATOR_CHAT_ID,
                    message_thread_id=thread_id,
                    limit=20  # Обмежуємо пошук останніми 20 повідомленнями
                )

                # Шукаємо останнє повідомлення з кнопками
                for msg in messages:
                    if msg.reply_markup is not None:
                        # Знайдено повідомлення з кнопками, видаляємо їх
                        await bot.edit_message_reply_markup(
                            chat_id=CURATOR_CHAT_ID,
                            message_id=msg.message_id,
                            reply_markup=None
                        )
                        break
            except Exception as e:
                print(f"❌ Помилка при спробі видалити клавіатуру з попереднього повідомлення: {e}")

            # Створюємо клавіатуру в залежності від статусу запиту
            keyboard = None
            if requests[active_request_id]["status"] == "Очікує обробки":
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="Взяти в роботу", callback_data=f"take_{active_request_id}")
                        ]
                    ]
                )
            elif requests[active_request_id]["status"] == "У роботі":
                curator_id = requests[active_request_id].get("curator_id")
                if curator_id:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text="Відповісти", callback_data=f"reply_{active_request_id}"),
                                InlineKeyboardButton(text="Завершити діалог",
                                                     callback_data=f"finish_{active_request_id}")
                            ],
                            [
                                InlineKeyboardButton(text="Поставити на утримання",
                                                     callback_data=f"hold_{active_request_id}"),
                                InlineKeyboardButton(text="Переназначити",
                                                     callback_data=f"reassign_{active_request_id}")
                            ]
                        ]
                    )

            # Надсилаємо нове повідомлення з актуальними кнопками
            await bot.send_message(
                chat_id=CURATOR_CHAT_ID,
                message_thread_id=thread_id,
                text=f"📨 Нове повідомлення від студента:\n\n{message.text}",
                reply_markup=keyboard
            )

        await message.answer("✅ Ваше повідомлення додано до активного запиту.")
        return

    # Код для створення нового запиту залишається без змін...
    # Создаем новый запит
    request_id = str(message.message_id)

    await log_message(request_id, student_id, "student", message.text)

    requests[request_id] = {
        "student_id": student_id,
        "student_name": student_name,
        "student_username": student_username,
        "text": message.text,
        "status": "Очікує обробки",
        "messages": [{"from": "student", "text": message.text, "time": message.date.isoformat()}]
    }

    # Створюємо тред у чаті кураторів
    student_info = f"@{student_username}" if student_username else student_name

    # Створюємо окремий тред без отправки сообщения в общий чат
    thread_message = await bot.create_forum_topic(
        chat_id=CURATOR_CHAT_ID,
        name=f"Запит: {student_info} - {datetime.now(ZoneInfo('Europe/Kiev')).strftime('%d.%m %H:%M')}",
        icon_color=0x6FB9F0
    )

    thread_id = thread_message.message_thread_id
    request_threads[request_id] = thread_id

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Взяти в роботу", callback_data=f"take_{request_id}")]
        ]
    )

    # Відправляємо детальне повідомлення у створений тред
    await bot.send_message(
        chat_id=CURATOR_CHAT_ID,
        message_thread_id=thread_id,
        text=f"📩 **Новий запит від {student_name}**\n\n"
             f"📝 *{message.text}*\n"
             f"⏳ Статус: Очікує обробки\n\n"
             f"Будь ласка, використовуйте кнопки нижче для взаємодії з запитом:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    await message.answer("✅ Ваш запит надіслано кураторам. Очікуйте відповідь.")


@dp.callback_query(F.data.startswith("reply_"))
async def ask_for_reply(callback_query: CallbackQuery, state: FSMContext):
    """Куратор натискає 'Відповісти'."""
    curator_id = callback_query.from_user.id

    if curator_id not in TEACHERS_IDS:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    request_id = callback_query.data.split("_")[1]

    print(f"🔍 Натиснуто кнопку 'Відповісти'. request_id={request_id}, curator_id={curator_id}")

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    # Проверка, что отвечает только назначенный куратор
    assigned_curator = requests[request_id].get("curator_id")
    if assigned_curator is not None and assigned_curator != curator_id:
        await callback_query.answer("Тільки призначений куратор може відповісти на запит")
        return

    await state.update_data(request_id=request_id)
    print(f"💾 Збережено в стані: request_id={request_id}")

    await callback_query.answer()

    await state.set_state(ReplyState.waiting_for_reply)
    print("🔄 Встановлено стан: waiting_for_reply")

    # Також відправляємо повідомлення в тред
    thread_id = request_threads.get(request_id)
    if thread_id:
        await bot.send_message(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            text=f"⌨️ Куратор @{callback_query.from_user.username or callback_query.from_user.full_name} готує відповідь..."
        )


@dp.callback_query(F.data.startswith("take_"))
async def take_request(callback_query: CallbackQuery, state: FSMContext):
    """Куратор бере запит у роботу"""
    curator_id = callback_query.from_user.id

    if curator_id not in TEACHERS_IDS:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    request_id = callback_query.data.split("_")[1]

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    # Перевіряємо, чи запит вже взятий в роботу іншим куратором
    if requests[request_id]["status"] == "У роботі" and requests[request_id].get("curator_id") != curator_id:
        await callback_query.answer("Цей запит вже взятий в роботу іншим куратором")
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

    requests[request_id]["curator_username"] = callback_query.from_user.username
    requests[request_id]["curator_name"] = callback_query.from_user.full_name

    await callback_query.answer("Ви взяли запит у роботу")

    curator_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Відповісти", callback_data=f"reply_{request_id}"),
                InlineKeyboardButton(text="Завершити діалог", callback_data=f"finish_{request_id}")
            ],
            [
                InlineKeyboardButton(text="Поставити на утримання", callback_data=f"hold_{request_id}"),
                InlineKeyboardButton(text="Переназначити", callback_data=f"reassign_{request_id}")
            ]
        ]
    )

    curator_username = callback_query.from_user.username
    curator_name = callback_query.from_user.full_name

    curator_info = f"@{curator_username}" if curator_username else curator_name

    # Використовуємо callback_query.message для видалення кнопок з поточного повідомлення
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        print(f"Помилка при видаленні кнопок: {e}")

    thread_id = request_threads.get(request_id)
    if thread_id:
        # Оновлюємо повідомлення в треді
        await bot.send_message(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            text=f"🚀 Запит взято в роботу куратором {curator_info}.\n"
                 f"⏱ Час взяття в роботу: {take_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"⚡ Швидкість реакції: {reaction_str}",
            reply_markup=curator_keyboard
        )

        # Оновлюємо назву теми з додаванням імені куратора
        student_info = requests[request_id].get("student_username", requests[request_id]["student_name"])
        student_info = f"@{student_info}" if "@" not in student_info else student_info

        await bot.edit_forum_topic(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            name=f"Запит: {student_info} ➤ {curator_info}"
        )

    await bot.send_message(
        requests[request_id]["student_id"],
        f"✅ Ваш запит взято в роботу куратором. Очікуйте відповідь."
    )


@dp.callback_query(F.data.startswith("finish_"))
async def finish_request(callback_query: CallbackQuery):
    """Куратор закриває запит"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if curator_id not in TEACHERS_IDS:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    assigned_curator = requests[request_id].get("curator_id")
    if assigned_curator is not None and assigned_curator != curator_id:
        await callback_query.answer("Тільки призначений куратор може завершити діалог")
        return

    requests[request_id]["status"] = "Завершено"
    await log_curator_action(request_id, curator_id, "завершив діалог")

    curator_username = callback_query.from_user.username
    curator_name = callback_query.from_user.full_name

    if not requests[request_id].get("curator_username"):
        requests[request_id]["curator_username"] = curator_username

    if not requests[request_id].get("curator_name"):
        requests[request_id]["curator_name"] = curator_name

    curator_info = f"@{requests[request_id]['curator_username']}" if requests[request_id].get("curator_username") else \
        requests[request_id].get("curator_name", "Невідомо")

    await callback_query.answer("Запит завершено")

    # Видаляємо кнопки з поточного повідомлення
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        print(f"Помилка при видаленні кнопок: {e}")

    thread_id = request_threads.get(request_id)
    if thread_id:
        # Оновлюємо інформацію в треді
        await bot.send_message(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            text=f"✅ Запит завершено куратором {curator_info}.\n"
                 f"⏱ Час завершення: {datetime.now(ZoneInfo('Europe/Kiev')).strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=None
        )

        # Оновлюємо назву теми, додаючи [ЗАВЕРШЕНО]
        student_info = requests[request_id].get("student_username", requests[request_id]["student_name"])
        student_info = f"@{student_info}" if "@" not in student_info else student_info

        await bot.edit_forum_topic(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            name=f"[ЗАВЕРШЕНО] {student_info} ➤ {curator_info}"
        )

        # Закриваємо тему форуму, якщо така функція підтримується API
        try:
            await bot.close_forum_topic(
                chat_id=CURATOR_CHAT_ID,
                message_thread_id=thread_id
            )
        except Exception as e:
            print(f"Не вдалося закрити тему форуму: {e}")

    await bot.send_message(
        requests[request_id]["student_id"],
        f"✅ Ваш запит завершено куратором {curator_info}. Дякуємо за звернення!"
    )


@dp.callback_query(F.data.startswith("hold_"))
async def hold_request(callback_query: CallbackQuery):
    """Куратор ставить запит на утримання"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if curator_id not in TEACHERS_IDS:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    if requests[request_id].get("curator_id") != curator_id and requests[request_id].get("curator_id") is not None:
        await callback_query.answer("Тільки призначений куратор може поставити запит на утримання")
        return

    if requests[request_id].get("status") == "У роботі":
        requests[request_id]["status"] = "Очікує"
        assigned_curator = curator_id
    else:
        requests[request_id]["curator_id"] = curator_id
        requests[request_id]["curator_username"] = callback_query.from_user.username
        requests[request_id]["curator_name"] = callback_query.from_user.full_name
        requests[request_id]["status"] = "Очікує"
        assigned_curator = curator_id

    await log_curator_action(request_id, curator_id, "поставив на утримання")
    await callback_query.answer("Запит поставлено на утримання")

    curator_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Відповісти", callback_data=f"reply_{request_id}"),
                InlineKeyboardButton(text="Завершити діалог", callback_data=f"finish_{request_id}")
            ],
            [
                InlineKeyboardButton(text="Взяти в роботу", callback_data=f"take_{request_id}"),
                InlineKeyboardButton(text="Переназначити", callback_data=f"reassign_{request_id}")
            ]
        ]
    )

    curator_info = f"@{callback_query.from_user.username}" if callback_query.from_user.username else callback_query.from_user.full_name

    # Видаляємо кнопки з поточного повідомлення
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        print(f"Помилка при видаленні кнопок: {e}")

    thread_id = request_threads.get(request_id)
    if thread_id:
        # Оновлюємо інформацію в треді
        await bot.send_message(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            text=f"⏸ Запит поставлено на утримання куратором {curator_info}.\n"
                 f"⏱ Час: {datetime.now(ZoneInfo('Europe/Kiev')).strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=curator_keyboard
        )

        # Оновлюємо назву теми, додаючи [НА УТРИМАННІ]
        student_info = requests[request_id].get("student_username", requests[request_id]["student_name"])
        student_info = f"@{student_info}" if "@" not in student_info else student_info

        await bot.edit_forum_topic(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            name=f"[НА УТРИМАННІ] {student_info} ➤ {curator_info}"
        )

    await bot.send_message(
        requests[request_id]["student_id"],
        "⏳ Ваш запит поставлено на утримання. Куратор повернеться до вас пізніше."
    )


@dp.callback_query(F.data.startswith("reassign_"))
async def reassign_request(callback_query: CallbackQuery):
    """Переназначити куратора для запиту"""
    curator_id = callback_query.from_user.id
    request_id = callback_query.data.split("_")[1]

    if curator_id not in TEACHERS_IDS:
        await callback_query.answer("У вас немає прав для виконання цієї дії.")
        return

    if request_id not in requests:
        await callback_query.answer("Запит не знайдено")
        return

    # Проверяем, что переназначить куратора может только текущий назначенный куратор
    assigned_curator = requests[request_id].get("curator_id")
    if assigned_curator != curator_id:
        await callback_query.answer("Тільки призначений куратор може переназначити запит")
        return

    prev_curator = requests[request_id].get("curator_id")
    prev_curator_info = None
    if prev_curator:
        prev_curator_info = f"@{requests[request_id].get('curator_username')}" if requests[request_id].get(
            "curator_username") else requests[request_id].get("curator_name", "Невідомо")

    requests[request_id]["curator_id"] = None
    requests[request_id]["status"] = "Очікує обробки"

    await log_curator_action(request_id, curator_id, "переназначив запит")
    await callback_query.answer("Запит доступний для інших кураторів")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Взяти в роботу", callback_data=f"take_{request_id}")],
        ]
    )

    # Видаляємо кнопки з поточного повідомлення
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        print(f"Помилка при видаленні кнопок: {e}")

    thread_id = request_threads.get(request_id)
    if thread_id:
        # Оновлюємо інформацію в треді
        reassign_text = f"🔄 Запит переназначено куратором @{callback_query.from_user.username or callback_query.from_user.full_name}."
        if prev_curator_info:
            reassign_text += f"\nПопередній куратор: {prev_curator_info}"

        await bot.send_message(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            text=f"{reassign_text}\n⏱ Час: {datetime.now(ZoneInfo('Europe/Kiev')).strftime('%Y-%m-%d %H:%M:%S')}\n\nЗапит доступний для взяття в роботу:",
            reply_markup=keyboard
        )

        # Оновлюємо назву теми
        student_info = requests[request_id].get("student_username", requests[request_id]["student_name"])
        student_info = f"@{student_info}" if "@" not in student_info else student_info

        await bot.edit_forum_topic(
            chat_id=CURATOR_CHAT_ID,
            message_thread_id=thread_id,
            name=f"[ДОСТУПНИЙ] Запит: {student_info}"
        )

    await bot.send_message(
        requests[request_id]["student_id"],
        "🔄 Ваш запит переназначено. Очікуйте, інший куратор прийме його в роботу."
    )


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
