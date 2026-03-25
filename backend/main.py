from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import Category, Hotel, Topic
from .schemas import (
    BindEmailRequest,
    CatalogOut,
    CategoryCreateRequest,
    CategoryOut,
    CategoryUpdateRequest,
    HealthOut,
    HotelCreateRequest,
    HotelOut,
    HotelUpdateRequest,
    MessageOut,
    RequestEmailCodeRequest,
    TicketCreateRequest,
    TicketOut,
    TicketStatusOut,
    TopicCreateRequest,
    TopicOut,
    TopicUpdateRequest,
    UserOut,
    UserUpdateRequest,
    VerifyEmailCodeRequest,
)
from .services import (
    bind_user_email,
    create_ticket,
    create_category_record,
    create_hotel_record,
    create_topic_record,
    enrich_ticket_status,
    enrich_tickets_status,
    get_catalog,
    get_user_by_max_id,
    init_defaults,
    list_users,
    list_user_tickets,
    request_email_code,
    require_admin_user,
    update_user,
    verify_email_code,
)


settings = get_settings()
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


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


def require_admin(
    x_max_user_id: str = Header(default="", alias="X-Max-User-Id"),
    db: Session = Depends(get_db),
) -> str:
    try:
        require_admin_user(db, x_max_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return x_max_user_id


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
    ticket = await enrich_ticket_status(ticket)
    return TicketOut.model_validate(ticket)


@app.get("/api/v1/tickets", response_model=list[TicketOut])
async def list_tickets(max_user_id: str, db: Session = Depends(get_db)) -> list[TicketOut]:
    tickets = await enrich_tickets_status(list_user_tickets(db, max_user_id))
    return [TicketOut.model_validate(item) for item in tickets]


@app.get("/api/v1/tickets/{external_id}/status", response_model=TicketStatusOut)
async def get_ticket_status(external_id: str, max_user_id: str, db: Session = Depends(get_db)) -> TicketStatusOut:
    tickets = list_user_tickets(db, max_user_id)
    ticket = next((item for item in tickets if item.external_id == external_id), None)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    ticket = await enrich_ticket_status(ticket)
    return TicketStatusOut(external_id=ticket.external_id, status=ticket.current_status)


@app.get("/api/v1/admin/hotels", response_model=list[HotelOut], dependencies=[Depends(require_admin)])
async def admin_hotels(db: Session = Depends(get_db)) -> list[HotelOut]:
    hotels = list(db.scalars(select(Hotel).order_by(Hotel.name)).all())
    return [HotelOut.model_validate(item) for item in hotels]


@app.post("/api/v1/admin/hotels", response_model=HotelOut, dependencies=[Depends(require_admin)])
async def create_hotel(payload: HotelCreateRequest, db: Session = Depends(get_db)) -> HotelOut:
    try:
        hotel = create_hotel_record(db, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return HotelOut.model_validate(hotel)


@app.put("/api/v1/admin/hotels/{hotel_id}", response_model=HotelOut, dependencies=[Depends(require_admin)])
async def update_hotel(hotel_id: int, payload: HotelUpdateRequest, db: Session = Depends(get_db)) -> HotelOut:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    hotel.name = payload.name
    hotel.is_active = payload.is_active
    db.commit()
    db.refresh(hotel)
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


@app.post("/api/v1/admin/categories", response_model=CategoryOut, dependencies=[Depends(require_admin)])
async def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db)) -> CategoryOut:
    try:
        category = create_category_record(db, payload.name, payload.osticket_topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CategoryOut.model_validate(category)


@app.put("/api/v1/admin/categories/{category_id}", response_model=CategoryOut, dependencies=[Depends(require_admin)])
async def update_category(category_id: int, payload: CategoryUpdateRequest, db: Session = Depends(get_db)) -> CategoryOut:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.name = payload.name
    category.osticket_topic_id = payload.osticket_topic_id
    category.is_active = payload.is_active
    db.commit()
    db.refresh(category)
    db.refresh(category, attribute_names=["topics"])
    return CategoryOut.model_validate(category)


@app.get("/api/v1/admin/topics", response_model=list[TopicOut], dependencies=[Depends(require_admin)])
async def admin_topics(db: Session = Depends(get_db)) -> list[TopicOut]:
    topics = list(db.scalars(select(Topic).order_by(Topic.name)).all())
    return [TopicOut.model_validate(item) for item in topics]


@app.post("/api/v1/admin/topics", response_model=TopicOut, dependencies=[Depends(require_admin)])
async def create_topic(payload: TopicCreateRequest, db: Session = Depends(get_db)) -> TopicOut:
    try:
        topic = create_topic_record(db, payload.category_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TopicOut.model_validate(topic)


@app.get("/api/v1/admin/users", response_model=list[UserOut], dependencies=[Depends(require_admin)])
async def admin_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(item) for item in list_users(db)]


@app.put("/api/v1/admin/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_admin)])
async def admin_update_user(user_id: int, payload: UserUpdateRequest, db: Session = Depends(get_db)) -> UserOut:
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
    return UserOut.model_validate(user)


@app.put("/api/v1/admin/topics/{topic_id}", response_model=TopicOut, dependencies=[Depends(require_admin)])
async def update_topic(topic_id: int, payload: TopicUpdateRequest, db: Session = Depends(get_db)) -> TopicOut:
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
    return TopicOut.model_validate(topic)
