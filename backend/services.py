import random
import re
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .defaults import DEFAULT_CATEGORIES, DEFAULT_HOTELS
from .mailer import send_verification_email
from .models import (
    AdminAuditLog,
    AppSettings,
    AppThemeSettings,
    AppUiSettings,
    Category,
    EmailVerification,
    Hotel,
    IntegrationSettings,
    Ticket,
    TicketStatusNotification,
    Topic,
    User,
    UserTicketViewPermission,
)
from .osticket import OsTicketClient, extract_extended_thread_entries


settings = get_settings()
osticket_client = OsTicketClient()


def init_defaults(db: Session) -> None:
    if db.get(AppSettings, 1) is None:
        db.add(AppSettings(id=1))
    if db.get(AppThemeSettings, 1) is None:
        db.add(AppThemeSettings(id=1))
    if db.get(AppUiSettings, 1) is None:
        db.add(AppUiSettings(id=1))
    if db.get(IntegrationSettings, 1) is None:
        db.add(IntegrationSettings(id=1))

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
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.email_verification_ttl_minutes)
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
    now = datetime.now(timezone.utc)
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
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        # Some DB drivers may return naive datetimes even for timezone-aware columns.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
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
    if should_be_admin and not user.is_admin:
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


def get_app_ui_settings(db: Session) -> AppUiSettings:
    settings_row = db.get(AppUiSettings, 1)
    if settings_row is None:
        settings_row = AppUiSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def get_integration_settings(db: Session) -> IntegrationSettings:
    settings_row = db.get(IntegrationSettings, 1)
    if settings_row is None:
        settings_row = IntegrationSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    elif not settings_row.plugin_label or settings_row.plugin_label == "Extended osTicket API":
        settings_row.plugin_label = "API Endpoints"
        db.commit()
        db.refresh(settings_row)
    return settings_row


def is_extended_api_enabled(db: Session) -> bool:
    integration_settings = get_integration_settings(db)
    return bool(integration_settings.extended_api_enabled and settings.osticket_extended_api_url)


def update_integration_settings(
    db: Session,
    *,
    extended_api_enabled: bool,
    plugin_label: str,
) -> IntegrationSettings:
    settings_row = get_integration_settings(db)
    settings_row.extended_api_enabled = extended_api_enabled
    settings_row.plugin_label = plugin_label
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


def update_app_ui_settings(
    db: Session,
    *,
    sidebar_background: str,
    nav_item_color: str,
    nav_item_active_text_color: str,
    button_text_color: str,
    input_background: str,
    input_border_color: str,
    heading_color: str,
    muted_text_color: str,
    card_radius: str,
    button_radius: str,
    card_shadow: str,
) -> AppUiSettings:
    settings_row = get_app_ui_settings(db)
    settings_row.sidebar_background = sidebar_background
    settings_row.nav_item_color = nav_item_color
    settings_row.nav_item_active_text_color = nav_item_active_text_color
    settings_row.button_text_color = button_text_color
    settings_row.input_background = input_background
    settings_row.input_border_color = input_border_color
    settings_row.heading_color = heading_color
    settings_row.muted_text_color = muted_text_color
    settings_row.card_radius = card_radius
    settings_row.button_radius = button_radius
    settings_row.card_shadow = card_shadow
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


def list_ticket_access_items(db: Session, viewer_user_id: int) -> list[dict]:
    viewer = db.get(User, viewer_user_id)
    if viewer is None:
        raise ValueError("Пользователь не найден")

    permissions = {
        item.owner_user_id
        for item in db.scalars(
            select(UserTicketViewPermission).where(UserTicketViewPermission.viewer_user_id == viewer_user_id)
        ).all()
    }
    users = list(
        db.scalars(
            select(User)
            .where(User.id != viewer_user_id)
            .order_by(User.full_name.asc(), User.work_email.asc())
        ).all()
    )
    return [
        {
            "user_id": item.id,
            "max_user_id": item.max_user_id,
            "full_name": item.full_name or "",
            "work_email": item.work_email or "",
            "can_view": item.id in permissions,
        }
        for item in users
    ]


def update_ticket_access_items(db: Session, viewer_user_id: int, owner_user_ids: list[int]) -> list[dict]:
    viewer = db.get(User, viewer_user_id)
    if viewer is None:
        raise ValueError("Пользователь не найден")

    sanitized_ids = sorted({item for item in owner_user_ids if item and item != viewer_user_id})
    owners = list(db.scalars(select(User).where(User.id.in_(sanitized_ids))).all()) if sanitized_ids else []
    owner_ids_found = {item.id for item in owners}
    missing = [str(item) for item in sanitized_ids if item not in owner_ids_found]
    if missing:
        raise ValueError(f"Не найдены пользователи для доступа: {', '.join(missing)}")

    existing = list(
        db.scalars(
            select(UserTicketViewPermission).where(UserTicketViewPermission.viewer_user_id == viewer_user_id)
        ).all()
    )
    for item in existing:
        db.delete(item)

    for owner_id in sanitized_ids:
        db.add(UserTicketViewPermission(viewer_user_id=viewer_user_id, owner_user_id=owner_id))

    db.commit()
    return list_ticket_access_items(db, viewer_user_id)


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

    dedup_from = datetime.now(timezone.utc) - timedelta(seconds=settings.ticket_dedup_seconds)
    recent_ticket = db.scalar(
        select(Ticket)
        .options(selectinload(Ticket.user))
        .where(Ticket.user_id == user.id)
        .where(Ticket.hotel_id == hotel.id)
        .where(Ticket.category_id == category.id)
        .where(Ticket.topic_id == topic.id)
        .where(Ticket.description == description)
        .where(Ticket.created_at >= dedup_from)
        .order_by(Ticket.created_at.desc())
    )
    if recent_ticket is not None:
        recent_ticket.owner_max_user_id = user.max_user_id  # type: ignore[attr-defined]
        recent_ticket.owner_full_name = user.full_name or user.work_email  # type: ignore[attr-defined]
        recent_ticket.owner_work_email = user.work_email  # type: ignore[attr-defined]
        recent_ticket.is_shared = False  # type: ignore[attr-defined]
        return recent_ticket

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
    ticket.owner_max_user_id = user.max_user_id  # type: ignore[attr-defined]
    ticket.owner_full_name = user.full_name or user.work_email  # type: ignore[attr-defined]
    ticket.owner_work_email = user.work_email  # type: ignore[attr-defined]
    ticket.is_shared = False  # type: ignore[attr-defined]
    return ticket


def list_user_tickets(db: Session, max_user_id: str) -> list[Ticket]:
    try:
        user = require_active_user(db, max_user_id)
    except ValueError:
        return []

    shared_owner_ids = list(
        db.scalars(
            select(UserTicketViewPermission.owner_user_id).where(UserTicketViewPermission.viewer_user_id == user.id)
        ).all()
    )
    accessible_ids = [user.id, *shared_owner_ids]
    tickets = list(
        db.scalars(
            select(Ticket)
            .options(selectinload(Ticket.user))
            .where(Ticket.user_id.in_(accessible_ids))
            .order_by(Ticket.created_at.desc())
        ).all()
    )
    for ticket in tickets:
        ticket.owner_max_user_id = ticket.user.max_user_id  # type: ignore[attr-defined]
        ticket.owner_full_name = ticket.user.full_name or ticket.user.work_email  # type: ignore[attr-defined]
        ticket.owner_work_email = ticket.user.work_email  # type: ignore[attr-defined]
        ticket.is_shared = ticket.user_id != user.id  # type: ignore[attr-defined]
    return tickets


def get_user_ticket(db: Session, max_user_id: str, external_id: str) -> Ticket:
    ticket = next((item for item in list_user_tickets(db, max_user_id) if item.external_id == external_id), None)
    if ticket is None:
        raise ValueError("Ticket not found")
    return ticket


async def get_ticket_details(db: Session, max_user_id: str, external_id: str) -> dict:
    ticket = await enrich_ticket_status(db, get_user_ticket(db, max_user_id, external_id))
    details = {
        "id": ticket.id,
        "external_id": ticket.external_id,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "current_status": ticket.current_status,
        "owner_max_user_id": ticket.owner_max_user_id,
        "owner_full_name": ticket.owner_full_name,
        "owner_work_email": ticket.owner_work_email,
        "is_shared": ticket.is_shared,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "thread": [],
    }

    if is_extended_api_enabled(db):
        try:
            extended = await osticket_client.get_extended_ticket_details(ticket.external_id)
            details["subject"] = str(extended.get("subject") or extended.get("title") or details["subject"])
            details["thread"] = extract_extended_thread_entries(extended)
        except Exception:
            pass

    return details


async def enrich_ticket_status(db: Session, ticket: Ticket) -> Ticket:
    if settings.osticket_status_api_url or is_extended_api_enabled(db):
        try:
            current_status = await osticket_client.get_ticket_status(
                ticket.external_id,
                use_extended_api=is_extended_api_enabled(db),
            )
            ticket.status = current_status
        except Exception:
            current_status = ticket.status
        ticket.current_status = current_status  # type: ignore[attr-defined]
        if not hasattr(ticket, "owner_max_user_id"):
            ticket.owner_max_user_id = ticket.user.max_user_id if ticket.user else ""  # type: ignore[attr-defined]
            ticket.owner_full_name = (ticket.user.full_name or ticket.user.work_email) if ticket.user else ""  # type: ignore[attr-defined]
            ticket.owner_work_email = ticket.user.work_email if ticket.user else ""  # type: ignore[attr-defined]
            ticket.is_shared = False  # type: ignore[attr-defined]
        return ticket

    ticket.current_status = ticket.status  # type: ignore[attr-defined]
    if not hasattr(ticket, "owner_max_user_id"):
        ticket.owner_max_user_id = ticket.user.max_user_id if ticket.user else ""  # type: ignore[attr-defined]
        ticket.owner_full_name = (ticket.user.full_name or ticket.user.work_email) if ticket.user else ""  # type: ignore[attr-defined]
        ticket.owner_work_email = ticket.user.work_email if ticket.user else ""  # type: ignore[attr-defined]
        ticket.is_shared = False  # type: ignore[attr-defined]
    return ticket


async def enrich_tickets_status(db: Session, tickets: list[Ticket]) -> list[Ticket]:
    enriched: list[Ticket] = []
    for ticket in tickets:
        enriched.append(await enrich_ticket_status(db, ticket))
    return enriched


async def sync_ticket_statuses(db: Session) -> list[TicketStatusNotification]:
    notifications: list[TicketStatusNotification] = []
    tickets = list(db.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all())
    use_extended_api = is_extended_api_enabled(db)
    for ticket in tickets:
        previous_status = ticket.status
        try:
            current_status = await osticket_client.get_ticket_status(ticket.external_id, use_extended_api=use_extended_api)
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
    notification.notified_at = datetime.now(timezone.utc)
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
