from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BindEmailRequest(BaseModel):
    max_user_id: str
    full_name: str = ""
    email: EmailStr


class RequestEmailCodeRequest(BaseModel):
    max_user_id: str
    full_name: str = ""
    email: EmailStr


class VerifyEmailCodeRequest(BaseModel):
    max_user_id: str
    full_name: str = ""
    email: EmailStr
    code: str = Field(min_length=4, max_length=16)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    max_user_id: str
    full_name: str
    work_email: str
    is_admin: bool
    is_active: bool


class UserUpdateRequest(BaseModel):
    full_name: str = Field(min_length=0, max_length=255)
    is_admin: bool
    is_active: bool


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    name: str
    is_active: bool


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    osticket_topic_id: int
    is_active: bool
    topics: list[TopicOut]


class HotelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


class CatalogOut(BaseModel):
    hotels: list[HotelOut]
    categories: list[CategoryOut]


class TicketCreateRequest(BaseModel):
    max_user_id: str
    hotel_id: int
    category_id: int
    topic_id: int
    description: str = Field(min_length=1, max_length=10000)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    subject: str
    description: str
    status: str
    current_status: str
    created_at: datetime
    updated_at: datetime


class HealthOut(BaseModel):
    status: str


class MessageOut(BaseModel):
    message: str


class TicketStatusOut(BaseModel):
    external_id: str
    status: str


class HotelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class HotelUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    osticket_topic_id: int


class CategoryUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    osticket_topic_id: int
    is_active: bool


class TopicCreateRequest(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=255)


class TopicUpdateRequest(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=255)
    is_active: bool
