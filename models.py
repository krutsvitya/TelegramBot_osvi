from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class CuratorLog(Base):
    __tablename__ = 'curator_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(50), nullable=False)
    curator_id = Column(String(30), nullable=False)
    action = Column(String(50), nullable=False)
    action_time = Column(DateTime, default=datetime.utcnow)


class CuratorMessage(Base):
    __tablename__ = 'curator_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(50), nullable=False)
    sender_id = Column(String(30), nullable=False)
    sender_type = Column(String(20), nullable=False)  # "student" або "curator"
    message_text = Column(Text, nullable=False)
    message_time = Column(DateTime, default=datetime.utcnow)