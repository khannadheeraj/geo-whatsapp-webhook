from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator
from app.models.crm_model import LeadStatus

FollowUpType = Literal["CALL", "WHATSAPP", "MEETING", "DOCUMENT", "PAYMENT", "GENERAL"]
FollowUpPriority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]
FollowUpOutcome = Literal["CONNECTED_INTERESTED", "CONNECTED_NOT_INTERESTED", "CALLBACK_REQUESTED", "NO_ANSWER", "BUSY", "WRONG_NUMBER", "GENERAL_COMPLETED"]
LeadStatusDecision = Literal["RECOMMENDATION_ACCEPTED", "MANUAL_OVERRIDE", "KEPT_CURRENT"]


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
    outcome: Optional[FollowUpOutcome] = None
    discussionSummary: Optional[str] = Field(default=None, max_length=2000)
    studentQuestionsOrObjections: Optional[str] = Field(default=None, max_length=2000)
    nextAction: Optional[str] = Field(default=None, max_length=500)
    nextFollowUpAt: Optional[datetime] = None
    nextFollowUpType: Optional[FollowUpType] = None
    nextFollowUpPriority: Optional[FollowUpPriority] = "MEDIUM"
    leadStatus: Optional[LeadStatus] = None
    leadStatusDecision: Optional[LeadStatusDecision] = None

    @field_validator("nextFollowUpAt")
    @classmethod
    def next_due_timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None): raise ValueError("nextFollowUpAt must include a timezone offset")
        return value
