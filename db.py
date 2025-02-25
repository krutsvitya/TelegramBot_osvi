import os
import asyncio

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from models import CuratorLog, CuratorMessage, Base

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