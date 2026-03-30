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


class WebAppSessionRequest(BaseModel):
    init_data: str = Field(min_length=1)


class WebAppSessionOut(BaseModel):
    max_user_id: str
    full_name: str
    init_data_validated: bool
    access_token: str


class AppSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_name: str
    brand_subtitle: str
    brand_mark: str
    brand_icon_url: str


class AppThemeSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    background_color: str
    card_color: str
    accent_color: str
    button_color: str


class IntegrationSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    extended_api_enabled: bool
    plugin_label: str


class AppSettingsUpdateRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=255)
    brand_subtitle: str = Field(min_length=0, max_length=255)
    brand_mark: str = Field(min_length=1, max_length=16)
    brand_icon_url: str = Field(min_length=0, max_length=1000)


class AppThemeSettingsUpdateRequest(BaseModel):
    background_color: str = Field(min_length=4, max_length=32)
    card_color: str = Field(min_length=4, max_length=32)
    accent_color: str = Field(min_length=4, max_length=32)
    button_color: str = Field(min_length=4, max_length=32)


class IntegrationSettingsUpdateRequest(BaseModel):
    extended_api_enabled: bool
    plugin_label: str = Field(min_length=1, max_length=255)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    max_user_id: str
    full_name: str
    work_email: str
    is_admin: bool
    is_active: bool
    can_manage_admins: bool = False


class UserUpdateRequest(BaseModel):
    full_name: str = Field(min_length=0, max_length=255)
    is_admin: bool
    is_active: bool


class UserTicketAccessItemOut(BaseModel):
    user_id: int
    max_user_id: str
    full_name: str
    work_email: str
    can_view: bool


class UserTicketAccessUpdateRequest(BaseModel):
    owner_user_ids: list[int]


class AdminAuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int
    action: str
    entity_type: str
    entity_id: str
    details_json: str
    created_at: datetime


class TicketStatusNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    max_user_id: str
    external_id: str
    subject: str
    previous_status: str
    new_status: str
    created_at: datetime


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
    owner_max_user_id: str
    owner_full_name: str
    owner_work_email: str
    is_shared: bool
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
