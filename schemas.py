from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ---------- Admin / Auth ----------

class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)
    invite_code: Optional[str] = Field(default=None, max_length=100)

    @field_validator("username")
    @classmethod
    def clean_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_limits(cls, v: str) -> str:
        # bcrypt only looks at the first 72 bytes
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return v


class AdminOut(BaseModel):
    id: int
    username: str
    email: EmailStr

    model_config = {"from_attributes": True}


class AdminLogin(BaseModel):
    identifier: str = Field(max_length=255)  # username OR email
    password: str = Field(max_length=200)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Queue ----------

class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    fields: List[str] = Field(min_length=1, max_length=10)
    unique_field: str
    wait_time_estimate: int = Field(default=5, ge=1, le=240)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Queue name cannot be blank")
        return v

    @field_validator("fields")
    @classmethod
    def clean_fields(cls, v: List[str]) -> List[str]:
        cleaned = [f.strip() for f in v]
        if any(not f for f in cleaned):
            raise ValueError("Field names cannot be blank")
        if any(len(f) > 50 for f in cleaned):
            raise ValueError("Field names must be at most 50 characters")
        if len({f.lower() for f in cleaned}) != len(cleaned):
            raise ValueError("Field names must be unique")
        return cleaned

    @model_validator(mode="after")
    def unique_field_in_fields(self):
        self.unique_field = self.unique_field.strip()
        if self.unique_field not in self.fields:
            raise ValueError("unique_field must be one of the queue's fields")
        return self


class QueueOut(BaseModel):
    id: int
    name: str
    fields: List[str]
    unique_field: str
    wait_time_estimate: int
    is_active: bool

    model_config = {"from_attributes": True}


class WaitTimeUpdate(BaseModel):
    wait_time_estimate: int = Field(ge=1, le=240)


# ---------- Entry ----------

class EntryJoin(BaseModel):
    data: Dict[str, str] = Field(max_length=20)   # field name -> value (checked against the queue in the router)


class EntryOut(BaseModel):
    id: int
    queue_id: int
    data: Dict[str, str]
    status: str
    position: int
    created_at: datetime
    called_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EntryStatusOut(BaseModel):
    id: int
    queue_id: int
    queue_name: str
    status: str
    position_in_queue: int      # place among still-waiting entries (1 = next)
    people_ahead: int
    estimated_wait_minutes: int
