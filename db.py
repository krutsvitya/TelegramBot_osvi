import os
import asyncio

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from models import CuratorLog, CuratorMessage, Teacher, Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)


async def create_tables():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Таблиці успішно створено.")
    except SQLAlchemyError as e:
        print(f"Помилка при створенні таблиць: {e}")


async def init_db():
    await create_tables()


async def get_db_session():
    """Повертає асинхронну сесію для роботи з базою даних."""
    async with SessionLocal() as session:
        yield session


async def log_curator_action(request_id: str, curator_id: int, action: str):
    """Логує дію куратора у таблицю curator_logs."""
    try:
        async with SessionLocal() as session:
            log_entry = CuratorLog(
                request_id=request_id,
                curator_id=str(curator_id),
                action=action
            )
            session.add(log_entry)
            await session.commit()
            print("Дію куратора успішно залоговано.")
            return True
    except SQLAlchemyError as e:
        print(f"Помилка при логуванні дії куратора: {e}")
        return False


async def log_message(request_id: str, sender_id: int, sender_type: str, message_text: str):
    """Логує повідомлення у таблицю curator_messages."""
    try:
        async with SessionLocal() as session:
            message_entry = CuratorMessage(
                request_id=request_id,
                sender_id=str(sender_id),
                sender_type=sender_type,
                message_text=message_text
            )
            session.add(message_entry)
            await session.commit()
            print("Повідомлення успішно залоговано.")
            return True
    except SQLAlchemyError as e:
        print(f"Помилка при логуванні повідомлення: {e}")
        return False


# Функции для работы с учителями
async def get_all_teachers():
    """Получить всех активных учителей"""
    try:
        async with SessionLocal() as session:
            query = select(Teacher).where(Teacher.is_active == True)
            result = await session.execute(query)
            teachers = result.scalars().all()
            return teachers
    except SQLAlchemyError as e:
        print(f"Ошибка при получении списка учителей: {e}")
        return []


async def get_teacher_by_id(telegram_id: int):
    """Получить учителя по Telegram ID"""
    try:
        async with SessionLocal() as session:
            query = select(Teacher).where(Teacher.telegram_id == str(telegram_id))
            result = await session.execute(query)
            teacher = result.scalars().first()
            return teacher
    except SQLAlchemyError as e:
        print(f"Ошибка при получении учителя: {e}")
        return None


async def add_teacher(telegram_id: int, username: str, full_name: str):
    """Добавить нового учителя"""
    try:
        async with SessionLocal() as session:
            teacher = Teacher(
                telegram_id=str(telegram_id),
                username=username,
                full_name=full_name
            )
            session.add(teacher)
            await session.commit()
            return True
    except SQLAlchemyError as e:
        print(f"Ошибка при добавлении учителя: {e}")
        return False


async def deactivate_teacher(telegram_id: int):
    """Деактивировать учителя"""
    try:
        async with SessionLocal() as session:
            query = select(Teacher).where(Teacher.telegram_id == str(telegram_id))
            result = await session.execute(query)
            teacher = result.scalars().first()

            if teacher:
                teacher.is_active = False
                await session.commit()
                return True
            return False
    except SQLAlchemyError as e:
        print(f"Ошибка при деактивации учителя: {e}")
        return False


async def is_teacher(telegram_id: int):
    """Проверить, является ли пользователь учителем"""
    teacher = await get_teacher_by_id(telegram_id)
    return teacher is not None and teacher.is_active