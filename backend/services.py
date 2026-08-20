import asyncio
import logging
import re
import json
import secrets
from datetime import datetime, timedelta, timezone
from time import monotonic

from sqlalchemy import func, select
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
from .osticket import (
    OsTicketClient,
    extract_extended_thread_entries,
    is_terminal_status,
    normalize_status,
)


logger = logging.getLogger(__name__)
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

    # work_email уникален в БД: без этой проверки повторная привязка чужой почты
    # выпадала наружу как IntegrityError и превращалась в HTTP 500.
    email_owner = db.scalar(select(User).where(func.lower(User.work_email) == email.lower()))
    if email_owner is not None and email_owner.max_user_id != max_user_id:
        raise ValueError("Эта почта уже привязана к другому аккаунту MAX")

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

    try:
        db.commit()
    except IntegrityError as exc:
        # Гонка между двумя параллельными подтверждениями одной почты.
        db.rollback()
        raise ValueError("Эта почта уже привязана к другому аккаунту MAX") from exc
    db.refresh(user)
    return user


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite отдаёт naive datetime — приводим к UTC, чтобы сравнения не падали."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enforce_email_code_rate_limit(db: Session, max_user_id: str, email: str, now: datetime) -> None:
    """Не даёт превратить отправку кода в спам-рассыльщик по чужим адресам."""
    recent = list(
        db.scalars(
            select(EmailVerification)
            .where(EmailVerification.max_user_id == max_user_id)
            .where(EmailVerification.email == email)
            .order_by(EmailVerification.created_at.desc())
            .limit(settings.email_code_max_per_hour)
        ).all()
    )
    if not recent:
        return

    last_created = _as_utc(recent[0].created_at)
    if last_created is not None:
        elapsed = (now - last_created).total_seconds()
        if elapsed < settings.email_code_resend_interval_seconds:
            wait_seconds = int(settings.email_code_resend_interval_seconds - elapsed) + 1
            raise ValueError(f"Новый код можно запросить через {wait_seconds} сек.")

    hour_ago = now - timedelta(hours=1)
    in_last_hour = sum(1 for item in recent if (_as_utc(item.created_at) or now) >= hour_ago)
    if in_last_hour >= settings.email_code_max_per_hour:
        raise ValueError("Слишком много запросов кода. Попробуйте через час.")


def request_email_code(db: Session, max_user_id: str, full_name: str, email: str) -> None:
    if not validate_email(email):
        raise ValueError("Некорректный email")

    validate_allowed_email_domain(email)
    now = datetime.now(timezone.utc)
    enforce_email_code_rate_limit(db, max_user_id, email, now)
    code = f"{secrets.randbelow(900000) + 100000}"
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
    # Берём последний активный код пользователя, а не «код, совпавший с введённым»:
    # только так можно посчитать неудачные попытки и оборвать перебор.
    verification = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.max_user_id == max_user_id)
        .where(EmailVerification.email == email)
        .where(EmailVerification.consumed_at.is_(None))
        .order_by(EmailVerification.created_at.desc())
    )
    if verification is None:
        raise ValueError("Код не найден или уже использован")

    expires_at = _as_utc(verification.expires_at)
    if expires_at is not None and expires_at < now:
        verification.consumed_at = now
        db.commit()
        raise ValueError("Срок действия кода истек")

    if not secrets.compare_digest(str(verification.code), str(code).strip()):
        verification.attempts = (verification.attempts or 0) + 1
        attempts_left = settings.email_code_max_attempts - verification.attempts
        if attempts_left <= 0:
            # Код сожжён — дальнейший перебор бессмыслен, нужен новый запрос.
            verification.consumed_at = now
            db.commit()
            raise ValueError("Слишком много неверных попыток. Запросите новый код.")
        db.commit()
        raise ValueError(f"Неверный код. Осталось попыток: {attempts_left}")

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
        _set_ticket_view_fields(recent_ticket, viewer_user_id=user.id)
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
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Заявка в osTicket уже создана — её номер обязан попасть в лог, иначе она потеряна.
        logger.exception(
            "Заявка %s создана в osTicket, но не сохранена в БД (пользователь %s)",
            external_id,
            user.max_user_id,
        )
        raise RuntimeError(f"Заявка создана в osTicket (№{external_id}), но не сохранена локально")
    db.refresh(ticket)
    _set_ticket_view_fields(ticket, viewer_user_id=user.id)
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
        _set_ticket_view_fields(ticket, viewer_user_id=user.id)
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
        except Exception as exc:
            # Переписка — необязательная часть карточки: показываем заявку без неё,
            # но причина должна быть видна в логах, а не проглочена.
            logger.warning("Не удалось получить переписку по заявке %s: %s", ticket.external_id, exc)

    return details


def _set_ticket_view_fields(ticket: Ticket, *, viewer_user_id: int | None = None) -> None:
    """Проставляет вычисляемые поля, которых нет в таблице, но которые ждёт схема ответа."""
    owner = ticket.user
    ticket.owner_max_user_id = owner.max_user_id if owner else ""  # type: ignore[attr-defined]
    ticket.owner_full_name = (owner.full_name or owner.work_email) if owner else ""  # type: ignore[attr-defined]
    ticket.owner_work_email = owner.work_email if owner else ""  # type: ignore[attr-defined]
    if viewer_user_id is not None:
        ticket.is_shared = ticket.user_id != viewer_user_id  # type: ignore[attr-defined]
    elif not hasattr(ticket, "is_shared"):
        ticket.is_shared = False  # type: ignore[attr-defined]


# Короткоживущий кэш статусов: список заявок и уведомления обращаются к одним и тем же
# номерам, а osTicket не меняет статус несколько раз в секунду.
_status_cache: dict[str, tuple[float, str]] = {}


def _cached_status(external_id: str) -> str | None:
    ttl = settings.ticket_status_cache_ttl_seconds
    if ttl <= 0:
        return None
    entry = _status_cache.get(external_id)
    if entry is None:
        return None
    stored_at, status = entry
    if monotonic() - stored_at > ttl:
        _status_cache.pop(external_id, None)
        return None
    return status


def _store_status(external_id: str, status: str) -> None:
    if settings.ticket_status_cache_ttl_seconds > 0 and status:
        _status_cache[external_id] = (monotonic(), status)


def invalidate_status_cache(external_id: str | None = None) -> None:
    if external_id is None:
        _status_cache.clear()
    else:
        _status_cache.pop(external_id, None)


def status_source_available(db: Session) -> bool:
    return bool(settings.osticket_status_api_url or is_extended_api_enabled(db))


async def _fetch_status(
    external_id: str,
    *,
    use_extended_api: bool,
    semaphore: asyncio.Semaphore,
    use_cache: bool = True,
) -> str | None:
    """Возвращает нормализованный статус заявки либо None, если osTicket недоступен."""
    if use_cache:
        cached = _cached_status(external_id)
        if cached is not None:
            return cached

    async with semaphore:
        try:
            raw_status = await osticket_client.get_ticket_status(
                external_id,
                use_extended_api=use_extended_api,
            )
        except Exception as exc:
            # Раньше ошибка гасилась молча — статус «залипал», и понять почему было нельзя.
            logger.warning("Не удалось получить статус заявки %s из osTicket: %s", external_id, exc)
            return None

    status = normalize_status(raw_status)
    if status:
        _store_status(external_id, status)
    return status or None


async def fetch_statuses(
    tickets: list[Ticket],
    *,
    use_extended_api: bool,
    use_cache: bool = True,
) -> list[str | None]:
    """Опрашивает статусы параллельно с ограничением по числу соединений.

    Последовательный обход стоил (число заявок x сетевая задержка) и на десятках
    заявок гарантированно упирался в таймаут запроса.
    """
    if not tickets:
        return []
    semaphore = asyncio.Semaphore(max(1, settings.ticket_status_fetch_concurrency))
    return list(
        await asyncio.gather(
            *(
                _fetch_status(
                    ticket.external_id,
                    use_extended_api=use_extended_api,
                    semaphore=semaphore,
                    use_cache=use_cache,
                )
                for ticket in tickets
            )
        )
    )


async def enrich_tickets_status(db: Session, tickets: list[Ticket]) -> list[Ticket]:
    if not tickets:
        return []

    if not status_source_available(db):
        for ticket in tickets:
            ticket.current_status = ticket.status  # type: ignore[attr-defined]
            _set_ticket_view_fields(ticket)
        return tickets

    use_extended_api = is_extended_api_enabled(db)
    statuses = await fetch_statuses(tickets, use_extended_api=use_extended_api)

    changed = False
    for ticket, status in zip(tickets, statuses):
        if status and status != ticket.status:
            ticket.status = status
            changed = True

    if changed:
        try:
            db.commit()
        except Exception:
            logger.exception("Не удалось сохранить обновлённые статусы заявок")
            db.rollback()

    for ticket in tickets:
        ticket.current_status = ticket.status  # type: ignore[attr-defined]
        _set_ticket_view_fields(ticket)
    return tickets


async def enrich_ticket_status(db: Session, ticket: Ticket) -> Ticket:
    enriched = await enrich_tickets_status(db, [ticket])
    return enriched[0]


async def sync_ticket_statuses(db: Session) -> list[TicketStatusNotification]:
    if not status_source_available(db):
        return []

    # Закрытые и архивные заявки статус больше не меняют — не опрашиваем их повторно.
    candidates = [
        ticket
        for ticket in db.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()
        if not is_terminal_status(ticket.status)
    ]
    if not candidates:
        return []

    use_extended_api = is_extended_api_enabled(db)
    # Синхронизация должна видеть свежие данные, а не собственный кэш списка заявок.
    statuses = await fetch_statuses(candidates, use_extended_api=use_extended_api, use_cache=False)

    notifications: list[TicketStatusNotification] = []
    for ticket, current_status in zip(candidates, statuses):
        previous_status = ticket.status
        if not current_status or current_status == previous_status:
            continue

        ticket.status = current_status
        db.add(ticket)

        # Повторный цикл «закрыта -> переоткрыта -> закрыта» должен уведомлять снова,
        # поэтому подавляем только ещё не отправленный дубликат того же перехода.
        pending_duplicate = db.scalar(
            select(TicketStatusNotification)
            .where(TicketStatusNotification.ticket_id == ticket.id)
            .where(TicketStatusNotification.new_status == current_status)
            .where(TicketStatusNotification.notified_at.is_(None))
        )
        if pending_duplicate is not None:
            continue

        notification = TicketStatusNotification(
            ticket_id=ticket.id,
            previous_status=previous_status,
            new_status=current_status,
            notified_at=None,
        )
        db.add(notification)
        notifications.append(notification)

    try:
        db.commit()
    except Exception:
        logger.exception("Не удалось сохранить результаты синхронизации статусов")
        db.rollback()
        return []

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
