import os

from dotenv import load_dotenv
from aiogram.fsm.state import State, StatesGroup
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = int(os.getenv("TEACHER_ID"))

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class ReplyState(StatesGroup):
    waiting_for_reply = State()
