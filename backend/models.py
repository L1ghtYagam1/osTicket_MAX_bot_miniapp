from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    work_email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user")


class Hotel(Base, TimestampMixin):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    osticket_topic_id: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    topics: Mapped[list["Topic"]] = relationship(back_populates="category")


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_topics_category_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped["Category"] = relationship(back_populates="topics")


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="created")

    user: Mapped["User"] = relationship(back_populates="tickets")


class EmailVerification(Base, TimestampMixin):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_user_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
