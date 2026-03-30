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
    audit_logs: Mapped[list["AdminAuditLog"]] = relationship(back_populates="actor")
    view_permissions_given: Mapped[list["UserTicketViewPermission"]] = relationship(
        foreign_keys="UserTicketViewPermission.owner_user_id",
        back_populates="owner",
    )
    view_permissions_received: Mapped[list["UserTicketViewPermission"]] = relationship(
        foreign_keys="UserTicketViewPermission.viewer_user_id",
        back_populates="viewer",
    )


class AppSettings(Base, TimestampMixin):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(255), default="MAX Support")
    brand_subtitle: Mapped[str] = mapped_column(String(255), default="osTicket 1.18.1")
    brand_mark: Mapped[str] = mapped_column(String(16), default="MS")
    brand_icon_url: Mapped[str] = mapped_column(String(1000), default="")


class AppThemeSettings(Base, TimestampMixin):
    __tablename__ = "app_theme_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    background_color: Mapped[str] = mapped_column(String(32), default="#f4efe7")
    card_color: Mapped[str] = mapped_column(String(32), default="#fffaf2")
    accent_color: Mapped[str] = mapped_column(String(32), default="#0e7a6d")
    button_color: Mapped[str] = mapped_column(String(32), default="#169c8b")


class AppUiSettings(Base, TimestampMixin):
    __tablename__ = "app_ui_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sidebar_background: Mapped[str] = mapped_column(String(32), default="rgba(255, 250, 242, 0.92)")
    nav_item_color: Mapped[str] = mapped_column(String(32), default="#ece1d1")
    nav_item_active_text_color: Mapped[str] = mapped_column(String(32), default="#ffffff")
    button_text_color: Mapped[str] = mapped_column(String(32), default="#ffffff")
    input_background: Mapped[str] = mapped_column(String(32), default="#fffdf9")
    input_border_color: Mapped[str] = mapped_column(String(32), default="#d6c8b7")
    heading_color: Mapped[str] = mapped_column(String(32), default="#1f2a2e")
    muted_text_color: Mapped[str] = mapped_column(String(32), default="#5e6c70")
    card_radius: Mapped[str] = mapped_column(String(16), default="20px")
    button_radius: Mapped[str] = mapped_column(String(16), default="14px")
    card_shadow: Mapped[str] = mapped_column(String(255), default="0 18px 40px rgba(34, 32, 24, 0.08)")


class IntegrationSettings(Base, TimestampMixin):
    __tablename__ = "integration_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extended_api_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    plugin_label: Mapped[str] = mapped_column(String(255), default="API Endpoints")


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
    notifications: Mapped[list["TicketStatusNotification"]] = relationship(back_populates="ticket")


class UserTicketViewPermission(Base, TimestampMixin):
    __tablename__ = "user_ticket_view_permissions"
    __table_args__ = (UniqueConstraint("viewer_user_id", "owner_user_id", name="uq_viewer_owner_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    viewer: Mapped["User"] = relationship(
        foreign_keys=[viewer_user_id],
        back_populates="view_permissions_received",
    )
    owner: Mapped["User"] = relationship(
        foreign_keys=[owner_user_id],
        back_populates="view_permissions_given",
    )


class EmailVerification(Base, TimestampMixin):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_user_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditLog(Base, TimestampMixin):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")

    actor: Mapped["User"] = relationship(back_populates="audit_logs")


class TicketStatusNotification(Base, TimestampMixin):
    __tablename__ = "ticket_status_notifications"
    __table_args__ = (UniqueConstraint("ticket_id", "new_status", name="uq_ticket_status_notification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    previous_status: Mapped[str] = mapped_column(String(64))
    new_status: Mapped[str] = mapped_column(String(64))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="notifications")
