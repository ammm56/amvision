"""SQLAlchemy Declarative Base 定义。"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 实体共享的 Declarative Base。"""
