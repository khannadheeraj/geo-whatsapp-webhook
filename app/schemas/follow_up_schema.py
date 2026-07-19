from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

FollowUpType = Literal["CALL", "WHATSAPP", "MEETING", "DOCUMENT", "PAYMENT", "GENERAL"]
FollowUpPriority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]


class FollowUpCreateModel(BaseModel):
    contactId: str
    assignedCounsellorId: str
    type: FollowUpType
    dueAt: datetime
    priority: FollowUpPriority = "MEDIUM"
    purpose: str = Field(min_length=1, max_length=500)
    internalNote: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("dueAt")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("dueAt must include a timezone offset")
        return value


class FollowUpPatchModel(BaseModel):
    version: int = Field(ge=1)
    assignedCounsellorId: Optional[str] = None
    type: Optional[FollowUpType] = None
    dueAt: Optional[datetime] = None
    priority: Optional[FollowUpPriority] = None
    purpose: Optional[str] = Field(default=None, min_length=1, max_length=500)
    internalNote: Optional[str] = Field(default=None, max_length=2000)


class FollowUpActionModel(BaseModel):
    version: int = Field(ge=1)
    completionNote: Optional[str] = Field(default=None, max_length=1000)
    cancellationNote: Optional[str] = Field(default=None, max_length=1000)
