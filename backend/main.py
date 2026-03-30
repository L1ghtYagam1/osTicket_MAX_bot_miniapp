from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .max_webapp import validate_init_data
from .models import Category, Hotel, Topic, User
from .schemas import (
    AdminAuditLogOut,
    AppSettingsOut,
    AppThemeSettingsOut,
    AppThemeSettingsUpdateRequest,
    AppUiSettingsOut,
    AppUiSettingsUpdateRequest,
    AppSettingsUpdateRequest,
    BindEmailRequest,
    CatalogOut,
    CategoryCreateRequest,
    CategoryOut,
    CategoryUpdateRequest,
    HealthOut,
    HotelCreateRequest,
    HotelOut,
    HotelUpdateRequest,
    IntegrationSettingsOut,
    IntegrationSettingsUpdateRequest,
    MessageOut,
    RequestEmailCodeRequest,
    UploadedAssetOut,
    TicketCreateRequest,
    TicketDetailsOut,
    TicketStatusNotificationOut,
    TicketOut,
    TicketStatusOut,
    TopicCreateRequest,
    TopicOut,
    TopicUpdateRequest,
    UserTicketAccessItemOut,
    UserTicketAccessUpdateRequest,
    UserOut,
    UserUpdateRequest,
    VerifyEmailCodeRequest,
    WebAppSessionOut,
    WebAppSessionRequest,
)
from .services import (
    bind_user_email,
    create_category_record,
    create_hotel_record,
    create_ticket,
    create_topic_record,
    enrich_ticket_status,
    enrich_tickets_status,
    get_app_settings,
    get_app_theme_settings,
    get_app_ui_settings,
    get_integration_settings,
    get_catalog,
    get_ticket_details,
    get_user_by_max_id,
    init_defaults,
    list_user_tickets,
    list_users,
    list_audit_logs,
    list_ticket_access_items,
    list_pending_status_notifications,
    log_admin_action,
    mark_notification_sent,
    request_email_code,
    require_active_user,
    require_admin_user,
    sync_ticket_statuses,
    update_integration_settings,
    update_ticket_access_items,
    update_user,
    update_app_settings,
    update_app_theme_settings,
    update_app_ui_settings,
    verify_email_code,
)
from .session_auth import SessionPrincipal, create_session_token, verify_session_token


settings = get_settings()
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        init_defaults(db)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/app/assets", StaticFiles(directory=WEBAPP_DIR), name="webapp-assets")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


def _extract_bearer_token(authorization: str) -> str:
    if not authorization:
        raise ValueError("Authorization header is required")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise ValueError("Authorization header must use Bearer token")
    token = authorization[len(prefix):].strip()
    if not token:
        raise ValueError("Authorization token is empty")
    return token


def require_session_principal(
    authorization: str = Header(default="", alias="Authorization"),
) -> SessionPrincipal:
    try:
        token = _extract_bearer_token(authorization)
        return verify_session_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_current_user(
    principal: SessionPrincipal = Depends(require_session_principal),
    db: Session = Depends(get_db),
) -> User:
    try:
        return require_active_user(db, principal.max_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_admin(
    principal: SessionPrincipal = Depends(require_session_principal),
    db: Session = Depends(get_db),
) -> User:
    try:
        return require_admin_user(db, principal.max_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def require_internal_token(
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> str:
    if not settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API token is not configured")
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal API token")
    return x_internal_token


def bind_if_known(db: Session, max_user_id: str):
    if not max_user_id:
        return None
    return get_user_by_max_id(db, max_user_id)


@app.get("/api/v1/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok")


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/app")


@app.get("/app")
async def webapp_index() -> FileResponse:
    return FileResponse(WEBAPP_DIR / "index.html")


@app.post("/api/v1/auth/bind-email", response_model=UserOut)
async def bind_email(payload: BindEmailRequest, db: Session = Depends(get_db)) -> UserOut:
    try:
        user = bind_user_email(db, payload.max_user_id, payload.full_name, str(payload.email))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserOut.model_validate(user)


@app.post("/api/v1/auth/request-email-code", response_model=MessageOut)
async def request_email_code_endpoint(payload: RequestEmailCodeRequest, db: Session = Depends(get_db)) -> MessageOut:
    try:
        request_email_code(db, payload.max_user_id, payload.full_name, str(payload.email))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageOut(message="Код подтверждения отправлен")


@app.post("/api/v1/auth/verify-email-code", response_model=UserOut)
async def verify_email_code_endpoint(payload: VerifyEmailCodeRequest, db: Session = Depends(get_db)) -> UserOut:
    try:
        user = verify_email_code(db, payload.max_user_id, payload.full_name, str(payload.email), payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserOut.model_validate(user)


@app.post("/api/v1/auth/webapp-session", response_model=WebAppSessionOut)
async def webapp_session_endpoint(payload: WebAppSessionRequest) -> WebAppSessionOut:
    try:
        webapp_user = validate_init_data(payload.init_data, bot_token=settings.max_bot_token)
        access_token = create_session_token(max_user_id=webapp_user.max_user_id, full_name=webapp_user.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WebAppSessionOut(
        max_user_id=webapp_user.max_user_id,
        full_name=webapp_user.full_name,
        init_data_validated=True,
        access_token=access_token,
    )


@app.get("/api/v1/auth/me", response_model=UserOut)
async def auth_me(current_user: User = Depends(require_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@app.get("/api/v1/users/by-max/{max_user_id}", response_model=UserOut)
async def get_user_by_max(max_user_id: str, db: Session = Depends(get_db)) -> UserOut:
    user = bind_if_known(db, max_user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserOut.model_validate(user)


@app.get("/api/v1/catalog", response_model=CatalogOut)
async def catalog(db: Session = Depends(get_db)) -> CatalogOut:
    hotels, categories = get_catalog(db)
    return CatalogOut(
        hotels=[HotelOut.model_validate(item) for item in hotels],
        categories=[CategoryOut.model_validate(item) for item in categories],
    )


@app.get("/api/v1/app-settings", response_model=AppSettingsOut)
async def app_settings(db: Session = Depends(get_db)) -> AppSettingsOut:
    return AppSettingsOut.model_validate(get_app_settings(db))


@app.get("/api/v1/app-theme-settings", response_model=AppThemeSettingsOut)
async def app_theme_settings(db: Session = Depends(get_db)) -> AppThemeSettingsOut:
    return AppThemeSettingsOut.model_validate(get_app_theme_settings(db))


@app.get("/api/v1/app-ui-settings", response_model=AppUiSettingsOut)
async def app_ui_settings(db: Session = Depends(get_db)) -> AppUiSettingsOut:
    return AppUiSettingsOut.model_validate(get_app_ui_settings(db))


@app.get("/api/v1/integration-settings", response_model=IntegrationSettingsOut)
async def integration_settings(db: Session = Depends(get_db)) -> IntegrationSettingsOut:
    return IntegrationSettingsOut.model_validate(get_integration_settings(db))


@app.post("/api/v1/tickets", response_model=TicketOut)
async def create_ticket_endpoint(payload: TicketCreateRequest, db: Session = Depends(get_db)) -> TicketOut:
    try:
        ticket = await create_ticket(
            db,
            max_user_id=payload.max_user_id,
            hotel_id=payload.hotel_id,
            category_id=payload.category_id,
            topic_id=payload.topic_id,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    ticket = await enrich_ticket_status(db, ticket)
    return TicketOut.model_validate(ticket)


@app.get("/api/v1/tickets", response_model=list[TicketOut])
async def list_tickets(max_user_id: str, db: Session = Depends(get_db)) -> list[TicketOut]:
    tickets = await enrich_tickets_status(db, list_user_tickets(db, max_user_id))
    return [TicketOut.model_validate(item) for item in tickets]


@app.get("/api/v1/tickets/{external_id}", response_model=TicketDetailsOut)
async def get_ticket_details_endpoint(external_id: str, max_user_id: str, db: Session = Depends(get_db)) -> TicketDetailsOut:
    try:
        details = await get_ticket_details(db, max_user_id, external_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TicketDetailsOut.model_validate(details)


@app.get("/api/v1/tickets/{external_id}/status", response_model=TicketStatusOut)
async def get_ticket_status(external_id: str, max_user_id: str, db: Session = Depends(get_db)) -> TicketStatusOut:
    tickets = list_user_tickets(db, max_user_id)
    ticket = next((item for item in tickets if item.external_id == external_id), None)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    ticket = await enrich_ticket_status(db, ticket)
    return TicketStatusOut(external_id=ticket.external_id, status=ticket.current_status)


@app.get("/api/v1/admin/hotels", response_model=list[HotelOut], dependencies=[Depends(require_admin)])
async def admin_hotels(db: Session = Depends(get_db)) -> list[HotelOut]:
    hotels = list(db.scalars(select(Hotel).order_by(Hotel.name)).all())
    return [HotelOut.model_validate(item) for item in hotels]


@app.post("/api/v1/admin/hotels", response_model=HotelOut)
async def create_hotel(payload: HotelCreateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> HotelOut:
    try:
        hotel = create_hotel_record(db, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="create",
        entity_type="hotel",
        entity_id=str(hotel.id),
        details={"name": hotel.name},
    )
    return HotelOut.model_validate(hotel)


@app.put("/api/v1/admin/hotels/{hotel_id}", response_model=HotelOut)
async def update_hotel(hotel_id: int, payload: HotelUpdateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> HotelOut:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    hotel.name = payload.name
    hotel.is_active = payload.is_active
    db.commit()
    db.refresh(hotel)
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="hotel",
        entity_id=str(hotel.id),
        details={"name": hotel.name, "is_active": hotel.is_active},
    )
    return HotelOut.model_validate(hotel)


@app.get("/api/v1/admin/categories", response_model=list[CategoryOut], dependencies=[Depends(require_admin)])
async def admin_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    categories = list(
        db.scalars(
            select(Category)
            .options(selectinload(Category.topics))
            .order_by(Category.name)
        ).all()
    )
    return [CategoryOut.model_validate(item) for item in categories]


@app.post("/api/v1/admin/categories", response_model=CategoryOut)
async def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> CategoryOut:
    try:
        category = create_category_record(db, payload.name, payload.osticket_topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="create",
        entity_type="category",
        entity_id=str(category.id),
        details={"name": category.name, "osticket_topic_id": category.osticket_topic_id},
    )
    return CategoryOut.model_validate(category)


@app.put("/api/v1/admin/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, payload: CategoryUpdateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> CategoryOut:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.name = payload.name
    category.osticket_topic_id = payload.osticket_topic_id
    category.is_active = payload.is_active
    db.commit()
    db.refresh(category)
    db.refresh(category, attribute_names=["topics"])
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="category",
        entity_id=str(category.id),
        details={"name": category.name, "osticket_topic_id": category.osticket_topic_id, "is_active": category.is_active},
    )
    return CategoryOut.model_validate(category)


@app.get("/api/v1/admin/topics", response_model=list[TopicOut], dependencies=[Depends(require_admin)])
async def admin_topics(db: Session = Depends(get_db)) -> list[TopicOut]:
    topics = list(db.scalars(select(Topic).order_by(Topic.name)).all())
    return [TopicOut.model_validate(item) for item in topics]


@app.post("/api/v1/admin/topics", response_model=TopicOut)
async def create_topic(payload: TopicCreateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> TopicOut:
    try:
        topic = create_topic_record(db, payload.category_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="create",
        entity_type="topic",
        entity_id=str(topic.id),
        details={"name": topic.name, "category_id": topic.category_id},
    )
    return TopicOut.model_validate(topic)


@app.put("/api/v1/admin/topics/{topic_id}", response_model=TopicOut)
async def update_topic(topic_id: int, payload: TopicUpdateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> TopicOut:
    topic = db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    category = db.get(Category, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    topic.category_id = payload.category_id
    topic.name = payload.name
    topic.is_active = payload.is_active
    db.commit()
    db.refresh(topic)
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="topic",
        entity_id=str(topic.id),
        details={"name": topic.name, "category_id": topic.category_id, "is_active": topic.is_active},
    )
    return TopicOut.model_validate(topic)


@app.get("/api/v1/admin/users", response_model=list[UserOut], dependencies=[Depends(require_admin)])
async def admin_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(item) for item in list_users(db)]


@app.put("/api/v1/admin/users/{user_id}", response_model=UserOut)
async def admin_update_user(user_id: int, payload: UserUpdateRequest, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> UserOut:
    try:
        user = update_user(
            db,
            user_id,
            full_name=payload.full_name,
            is_admin=payload.is_admin,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="user",
        entity_id=str(user.id),
        details={"full_name": user.full_name, "is_admin": user.is_admin, "is_active": user.is_active},
    )
    return UserOut.model_validate(user)


@app.get("/api/v1/admin/audit-logs", response_model=list[AdminAuditLogOut], dependencies=[Depends(require_admin)])
async def admin_audit_logs(db: Session = Depends(get_db)) -> list[AdminAuditLogOut]:
    return [AdminAuditLogOut.model_validate(item) for item in list_audit_logs(db)]


@app.put("/api/v1/admin/app-settings", response_model=AppSettingsOut)
async def admin_update_app_settings(
    payload: AppSettingsUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> AppSettingsOut:
    settings_row = update_app_settings(
        db,
        brand_name=payload.brand_name,
        brand_subtitle=payload.brand_subtitle,
        brand_mark=payload.brand_mark,
        brand_icon_url=payload.brand_icon_url,
    )
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="app_settings",
        entity_id=str(settings_row.id),
        details={
            "brand_name": settings_row.brand_name,
            "brand_subtitle": settings_row.brand_subtitle,
            "brand_mark": settings_row.brand_mark,
            "brand_icon_url": settings_row.brand_icon_url,
        },
    )
    return AppSettingsOut.model_validate(settings_row)


@app.post("/api/v1/admin/upload-icon", response_model=UploadedAssetOut)
async def admin_upload_icon(
    file: UploadFile = File(...),
    admin_user: User = Depends(require_admin),
) -> UploadedAssetOut:
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/svg+xml"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только PNG, JPG, WEBP и SVG")

    original_name = file.filename or "icon"
    extension = Path(original_name).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        extension = ".png"

    file_name = f"brand-icon-{uuid4().hex}{extension}"
    target_path = UPLOADS_DIR / file_name
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(payload) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 5 МБ")
    target_path.write_bytes(payload)
    return UploadedAssetOut(url=f"/uploads/{file_name}", filename=file_name)


@app.put("/api/v1/admin/app-theme-settings", response_model=AppThemeSettingsOut)
async def admin_update_app_theme_settings(
    payload: AppThemeSettingsUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> AppThemeSettingsOut:
    settings_row = update_app_theme_settings(
        db,
        background_color=payload.background_color,
        card_color=payload.card_color,
        accent_color=payload.accent_color,
        button_color=payload.button_color,
    )
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="app_theme_settings",
        entity_id=str(settings_row.id),
        details={
            "background_color": settings_row.background_color,
            "card_color": settings_row.card_color,
            "accent_color": settings_row.accent_color,
            "button_color": settings_row.button_color,
        },
    )
    return AppThemeSettingsOut.model_validate(settings_row)


@app.put("/api/v1/admin/app-ui-settings", response_model=AppUiSettingsOut)
async def admin_update_app_ui_settings(
    payload: AppUiSettingsUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> AppUiSettingsOut:
    settings_row = update_app_ui_settings(
        db,
        sidebar_background=payload.sidebar_background,
        nav_item_color=payload.nav_item_color,
        nav_item_active_text_color=payload.nav_item_active_text_color,
        button_text_color=payload.button_text_color,
        input_background=payload.input_background,
        input_border_color=payload.input_border_color,
        heading_color=payload.heading_color,
        muted_text_color=payload.muted_text_color,
        card_radius=payload.card_radius,
        button_radius=payload.button_radius,
        card_shadow=payload.card_shadow,
    )
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="app_ui_settings",
        entity_id=str(settings_row.id),
        details={
            "sidebar_background": settings_row.sidebar_background,
            "nav_item_color": settings_row.nav_item_color,
            "nav_item_active_text_color": settings_row.nav_item_active_text_color,
            "button_text_color": settings_row.button_text_color,
            "input_background": settings_row.input_background,
            "input_border_color": settings_row.input_border_color,
            "heading_color": settings_row.heading_color,
            "muted_text_color": settings_row.muted_text_color,
            "card_radius": settings_row.card_radius,
            "button_radius": settings_row.button_radius,
            "card_shadow": settings_row.card_shadow,
        },
    )
    return AppUiSettingsOut.model_validate(settings_row)


@app.put("/api/v1/admin/integration-settings", response_model=IntegrationSettingsOut)
async def admin_update_integration_settings(
    payload: IntegrationSettingsUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> IntegrationSettingsOut:
    settings_row = update_integration_settings(
        db,
        extended_api_enabled=payload.extended_api_enabled,
        plugin_label=payload.plugin_label,
    )
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="integration_settings",
        entity_id=str(settings_row.id),
        details={
            "extended_api_enabled": settings_row.extended_api_enabled,
            "plugin_label": settings_row.plugin_label,
        },
    )
    return IntegrationSettingsOut.model_validate(settings_row)


@app.get("/api/v1/admin/users/{user_id}/ticket-access", response_model=list[UserTicketAccessItemOut])
async def admin_user_ticket_access(user_id: int, db: Session = Depends(get_db), admin_user: User = Depends(require_admin)) -> list[UserTicketAccessItemOut]:
    try:
        items = list_ticket_access_items(db, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [UserTicketAccessItemOut(**item) for item in items]


@app.put("/api/v1/admin/users/{user_id}/ticket-access", response_model=list[UserTicketAccessItemOut])
async def admin_update_user_ticket_access(
    user_id: int,
    payload: UserTicketAccessUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> list[UserTicketAccessItemOut]:
    try:
        items = update_ticket_access_items(db, user_id, payload.owner_user_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        db,
        actor_user_id=admin_user.id,
        action="update",
        entity_type="user_ticket_access",
        entity_id=str(user_id),
        details={"owner_user_ids": payload.owner_user_ids},
    )
    return [UserTicketAccessItemOut(**item) for item in items]


@app.post("/api/v1/internal/ticket-status-sync", response_model=list[TicketStatusNotificationOut], dependencies=[Depends(require_internal_token)])
async def internal_ticket_status_sync(db: Session = Depends(get_db)) -> list[TicketStatusNotificationOut]:
    await sync_ticket_statuses(db)
    notifications = list_pending_status_notifications(db)
    result: list[TicketStatusNotificationOut] = []
    for item in notifications:
        ticket = item.ticket
        user = ticket.user
        result.append(
            TicketStatusNotificationOut(
                id=item.id,
                ticket_id=item.ticket_id,
                max_user_id=user.max_user_id,
                external_id=ticket.external_id,
                subject=ticket.subject,
                previous_status=item.previous_status,
                new_status=item.new_status,
                created_at=item.created_at,
            )
        )
    return result


@app.post("/api/v1/internal/ticket-status-notifications/{notification_id}/sent", response_model=MessageOut, dependencies=[Depends(require_internal_token)])
async def mark_ticket_status_notification_sent(notification_id: int, db: Session = Depends(get_db)) -> MessageOut:
    try:
        mark_notification_sent(db, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MessageOut(message="Notification marked as sent")
