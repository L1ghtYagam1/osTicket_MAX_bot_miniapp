import random
import re
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .defaults import DEFAULT_CATEGORIES, DEFAULT_HOTELS
from .mailer import send_verification_email
from .models import AdminAuditLog, AppSettings, AppThemeSettings, Category, EmailVerification, Hotel, Ticket, TicketStatusNotification, Topic, User
from .osticket import OsTicketClient


settings = get_settings()
osticket_client = OsTicketClient()


def init_defaults(db: Session) -> None:
    if db.get(AppSettings, 1) is None:
        db.add(AppSettings(id=1))
    if db.get(AppThemeSettings, 1) is None:
        db.add(AppThemeSettings(id=1))

    if not db.scalar(select(Hotel.id).limit(1)):
        for hotel_name in DEFAULT_HOTELS:
            db.add(Hotel(name=hotel_name))

    if not db.scalar(select(Category.id).limit(1)):
        for category_data in DEFAULT_CATEGORIES:
            category = Category(
                name=category_data["name"],
                osticket_topic_id=category_data["osticket_topic_id"],
            )
            db.add(category)
            db.flush()
            for topic_name in category_data["topics"]:
                db.add(Topic(category_id=category.id, name=topic_name))

    db.commit()


def validate_email(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value))


def validate_allowed_email_domain(email: str) -> None:
    allowed_domains = settings.allowed_email_domains
    if not allowed_domains:
        return

    domain = email.rsplit("@", 1)[-1].strip().lower()
    if domain not in allowed_domains:
        allowed_list = ", ".join(allowed_domains)
        raise ValueError(f"Разрешены только рабочие почты с доменами: {allowed_list}")


def bind_user_email(db: Session, max_user_id: str, full_name: str, email: str) -> User:
    if not validate_email(email):
        raise ValueError("Некорректный email")

    validate_allowed_email_domain(email)
    user = db.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None:
        user = User(
            max_user_id=max_user_id,
            full_name=full_name,
            work_email=email,
            is_admin=max_user_id in settings.admin_max_ids,
        )
        db.add(user)
    else:
        user.full_name = full_name
        user.work_email = email
        user.is_admin = max_user_id in settings.admin_max_ids

    db.commit()
    db.refresh(user)
    return user


def request_email_code(db: Session, max_user_id: str, full_name: str, email: str) -> None:
    if not validate_email(email):
        raise ValueError("Некорректный email")

    validate_allowed_email_domain(email)
    code = f"{random.randint(100000, 999999)}"
    now = datetime.utcnow()
    expires_at = datetime.utcnow() + timedelta(minutes=settings.email_verification_ttl_minutes)
    old_codes = list(
        db.scalars(
            select(EmailVerification)
            .where(EmailVerification.max_user_id == max_user_id)
            .where(EmailVerification.email == email)
            .where(EmailVerification.consumed_at.is_(None))
        ).all()
    )
    for item in old_codes:
        item.consumed_at = now

    verification = EmailVerification(
        max_user_id=max_user_id,
        email=email,
        code=code,
        expires_at=expires_at,
        consumed_at=None,
    )
    db.add(verification)
    db.commit()
    send_verification_email(email, code)


def verify_email_code(db: Session, max_user_id: str, full_name: str, email: str, code: str) -> User:
    now = datetime.utcnow()
    verification = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.max_user_id == max_user_id)
        .where(EmailVerification.email == email)
        .where(EmailVerification.code == code)
        .where(EmailVerification.consumed_at.is_(None))
        .order_by(EmailVerification.created_at.desc())
    )
    if verification is None:
        raise ValueError("Код не найден или уже использован")
    if verification.expires_at < now:
        raise ValueError("Срок действия кода истек")

    verification.consumed_at = now
    db.commit()
    return bind_user_email(db, max_user_id, full_name, email)


def get_catalog(db: Session) -> tuple[list[Hotel], list[Category]]:
    hotels = list(db.scalars(select(Hotel).order_by(Hotel.name)).all())
    categories = list(
        db.scalars(
            select(Category)
            .options(selectinload(Category.topics))
            .order_by(Category.name)
        ).all()
    )
    return hotels, categories


def get_user_by_max_id(db: Session, max_user_id: str) -> User | None:
    user = db.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None:
        return None

    should_be_admin = max_user_id in settings.admin_max_ids
    if user.is_admin != should_be_admin:
        user.is_admin = should_be_admin
        db.commit()
        db.refresh(user)
    return user


def get_app_settings(db: Session) -> AppSettings:
    settings_row = db.get(AppSettings, 1)
    if settings_row is None:
        settings_row = AppSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def update_app_settings(
    db: Session,
    *,
    brand_name: str,
    brand_subtitle: str,
    brand_mark: str,
    brand_icon_url: str,
) -> AppSettings:
    settings_row = get_app_settings(db)
    settings_row.brand_name = brand_name
    settings_row.brand_subtitle = brand_subtitle
    settings_row.brand_mark = brand_mark
    settings_row.brand_icon_url = brand_icon_url
    db.commit()
    db.refresh(settings_row)
    return settings_row


def get_app_theme_settings(db: Session) -> AppThemeSettings:
    settings_row = db.get(AppThemeSettings, 1)
    if settings_row is None:
        settings_row = AppThemeSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def update_app_theme_settings(
    db: Session,
    *,
    background_color: str,
    card_color: str,
    accent_color: str,
    button_color: str,
) -> AppThemeSettings:
    settings_row = get_app_theme_settings(db)
    settings_row.background_color = background_color
    settings_row.card_color = card_color
    settings_row.accent_color = accent_color
    settings_row.button_color = button_color
    db.commit()
    db.refresh(settings_row)
    return settings_row


def require_active_user(db: Session, max_user_id: str) -> User:
    user = get_user_by_max_id(db, max_user_id)
    if user is None:
        raise ValueError("Пользователь не зарегистрирован")
    if not user.is_active:
        raise ValueError("Пользователь отключен")
    return user


def require_admin_user(db: Session, max_user_id: str) -> User:
    user = require_active_user(db, max_user_id)
    if not user.is_admin:
        raise ValueError("Admin access required")
    return user


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())).all())


def list_audit_logs(db: Session) -> list[AdminAuditLog]:
    return list(db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())).all())


def update_user(db: Session, user_id: int, *, full_name: str, is_admin: bool, is_active: bool) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    user.full_name = full_name
    user.is_admin = is_admin
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def log_admin_action(
    db: Session,
    *,
    actor_user_id: int,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict,
) -> AdminAuditLog:
    log = AdminAuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details, ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


async def create_ticket(
    db: Session,
    *,
    max_user_id: str,
    hotel_id: int,
    category_id: int,
    topic_id: int,
    description: str,
) -> Ticket:
    user = require_active_user(db, max_user_id)

    hotel = db.get(Hotel, hotel_id)
    category = db.get(Category, category_id)
    topic = db.get(Topic, topic_id)

    if hotel is None or not hotel.is_active:
        raise ValueError("Отель не найден")
    if category is None or not category.is_active:
        raise ValueError("Категория не найдена")
    if topic is None or not topic.is_active:
        raise ValueError("Тема не найдена")
    if topic.category_id != category.id:
        raise ValueError("Тема не принадлежит выбранной категории")

    external_id = await osticket_client.create_ticket(
        full_name=user.full_name or user.work_email,
        email=user.work_email,
        subject=topic.name,
        description=description,
        hotel_name=hotel.name,
        osticket_topic_id=category.osticket_topic_id,
    )

    ticket = Ticket(
        external_id=external_id,
        user_id=user.id,
        hotel_id=hotel.id,
        category_id=category.id,
        topic_id=topic.id,
        subject=topic.name,
        description=description,
        status="created",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def list_user_tickets(db: Session, max_user_id: str) -> list[Ticket]:
    try:
        user = require_active_user(db, max_user_id)
    except ValueError:
        return []
    return list(
        db.scalars(
            select(Ticket)
            .where(Ticket.user_id == user.id)
            .order_by(Ticket.created_at.desc())
        ).all()
    )


async def enrich_ticket_status(ticket: Ticket) -> Ticket:
    if settings.osticket_status_api_url:
        try:
            current_status = await osticket_client.get_ticket_status(ticket.external_id)
            ticket.status = current_status
        except Exception:
            current_status = ticket.status
        ticket.current_status = current_status  # type: ignore[attr-defined]
        return ticket

    ticket.current_status = ticket.status  # type: ignore[attr-defined]
    return ticket


async def enrich_tickets_status(tickets: list[Ticket]) -> list[Ticket]:
    enriched: list[Ticket] = []
    for ticket in tickets:
        enriched.append(await enrich_ticket_status(ticket))
    return enriched


async def sync_ticket_statuses(db: Session) -> list[TicketStatusNotification]:
    notifications: list[TicketStatusNotification] = []
    tickets = list(db.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all())
    for ticket in tickets:
        previous_status = ticket.status
        try:
            current_status = await osticket_client.get_ticket_status(ticket.external_id)
        except Exception:
            continue
        if not current_status or current_status == previous_status:
            continue

        ticket.status = current_status
        db.add(ticket)

        existing = db.scalar(
            select(TicketStatusNotification)
            .where(TicketStatusNotification.ticket_id == ticket.id)
            .where(TicketStatusNotification.new_status == current_status)
        )
        if existing is not None:
            continue

        notification = TicketStatusNotification(
            ticket_id=ticket.id,
            previous_status=previous_status,
            new_status=current_status,
            notified_at=None,
        )
        db.add(notification)
        notifications.append(notification)

    db.commit()
    for notification in notifications:
        db.refresh(notification)
    return notifications


def list_pending_status_notifications(db: Session) -> list[TicketStatusNotification]:
    return list(
        db.scalars(
            select(TicketStatusNotification)
            .options(selectinload(TicketStatusNotification.ticket).selectinload(Ticket.user))
            .where(TicketStatusNotification.notified_at.is_(None))
            .order_by(TicketStatusNotification.created_at.asc())
        ).all()
    )


def mark_notification_sent(db: Session, notification_id: int) -> None:
    notification = db.get(TicketStatusNotification, notification_id)
    if notification is None:
        raise ValueError("Уведомление не найдено")
    notification.notified_at = datetime.utcnow()
    db.commit()


def create_hotel_record(db: Session, name: str) -> Hotel:
    hotel = Hotel(name=name)
    db.add(hotel)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Отель с таким названием уже существует") from exc
    db.refresh(hotel)
    return hotel


def create_category_record(db: Session, name: str, osticket_topic_id: int) -> Category:
    category = Category(name=name, osticket_topic_id=osticket_topic_id)
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Категория с таким названием уже существует") from exc
    db.refresh(category)
    db.refresh(category, attribute_names=["topics"])
    return category


def create_topic_record(db: Session, category_id: int, name: str) -> Topic:
    category = db.get(Category, category_id)
    if category is None:
        raise ValueError("Категория не найдена")
    topic = Topic(category_id=category_id, name=name)
    db.add(topic)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Тема с таким названием уже существует в категории") from exc
    db.refresh(topic)
    return topic
