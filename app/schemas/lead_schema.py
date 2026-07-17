from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.crm_model import LeadPriority, LeadStatus, PreferredMode


class LeadCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contactId: str = Field(min_length=24, max_length=24)
    status: LeadStatus = LeadStatus.NEW
    priority: LeadPriority = LeadPriority.MEDIUM
    preferredMode: Optional[PreferredMode] = None
    targetExamYear: Optional[int] = Field(default=None, ge=2020, le=2100)
    source: Optional[str] = Field(default=None, max_length=100)
    sourceDetails: Optional[str] = Field(default=None, max_length=500)
    assignedCounsellorId: Optional[str] = Field(default=None, min_length=24, max_length=24)


class LeadPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    status: Optional[LeadStatus] = None
    priority: Optional[LeadPriority] = None
    preferredMode: Optional[PreferredMode] = None
    targetExamYear: Optional[int] = Field(default=None, ge=2020, le=2100)
    source: Optional[str] = Field(default=None, max_length=100)
    sourceDetails: Optional[str] = Field(default=None, max_length=500)
    lostReason: Optional[str] = Field(default=None, max_length=500)
    nextActionAt: Optional[datetime] = None

    @model_validator(mode="after")
    def require_change(self):
        if not (self.model_fields_set - {"version"}):
            raise ValueError("At least one lead field must be supplied.")
        return self


class LeadAssignmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counsellorId: str = Field(min_length=24, max_length=24)
    reasonCode: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=2, max_length=500)
    version: int = Field(ge=1)
