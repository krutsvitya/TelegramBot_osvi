import os

from dotenv import load_dotenv
from aiogram.fsm.state import State, StatesGroup
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

CURATOR_CHAT_ID = int(os.getenv("CURATOR_CHAT_ID")) if os.getenv("CURATOR_CHAT_ID") else None
TEACHERS_IDS = [int(id.strip()) for id in os.getenv("TEACHERS_IDS", "").split(",")]
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class ReplyState(StatesGroup):
    waiting_for_reply = State()

class TeacherState(StatesGroup):
    waiting_for_new_teacher = State()
    waiting_for_teacher_removal = State()