from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.crm_model import ReassignmentReason


class ReassignmentCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestedTargetCounsellorId: Optional[str] = Field(default=None, min_length=24, max_length=24)
    reasonCode: ReassignmentReason
    note: Optional[str] = Field(default=None, max_length=1000)


class ReassignmentApproveModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetCounsellorId: Optional[str] = Field(default=None, min_length=24, max_length=24)
    version: int = Field(ge=1)
    decisionNote: Optional[str] = Field(default=None, max_length=1000)


class ReassignmentRejectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisionNote: str = Field(min_length=2, max_length=1000)
