from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.crm_model import LeadPriority, LeadStatus, PreferredMode


class ContactCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firstName: Optional[str] = Field(default=None, max_length=100)
    lastName: Optional[str] = Field(default=None, max_length=100)
    displayName: Optional[str] = Field(default=None, max_length=200)
    phone: str = Field(min_length=5, max_length=40)
    alternatePhone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=254)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    companyOrCollege: Optional[str] = Field(default=None, max_length=200)
    instagramProfile: Optional[str] = Field(default=None, max_length=500)
    facebookProfile: Optional[str] = Field(default=None, max_length=500)
    linkedinProfile: Optional[str] = Field(default=None, max_length=500)
    source: Optional[str] = Field(default=None, max_length=100)
    sourceDetails: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    createLead: bool = True
    leadStatus: LeadStatus = LeadStatus.NEW
    leadPriority: LeadPriority = LeadPriority.MEDIUM
    preferredMode: Optional[PreferredMode] = None
    targetExamYear: Optional[int] = Field(default=None, ge=2020, le=2100)
    assignedCounsellorId: Optional[str] = Field(default=None, min_length=24, max_length=24)
    courseInterest: Optional[str] = Field(default=None, max_length=200)


class ContactPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    firstName: Optional[str] = Field(default=None, max_length=100)
    lastName: Optional[str] = Field(default=None, max_length=100)
    displayName: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, min_length=5, max_length=40)
    alternatePhone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=254)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    companyOrCollege: Optional[str] = Field(default=None, max_length=200)
    instagramProfile: Optional[str] = Field(default=None, max_length=500)
    facebookProfile: Optional[str] = Field(default=None, max_length=500)
    linkedinProfile: Optional[str] = Field(default=None, max_length=500)
    source: Optional[str] = Field(default=None, max_length=100)
    sourceDetails: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    isActive: Optional[bool] = None

    @model_validator(mode="after")
    def require_change(self):
        if not (self.model_fields_set - {"version"}):
            raise ValueError("At least one contact field must be supplied.")
        return self


class ContactPreferencePatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    whatsappAllowed: Optional[bool] = None
    marketingAllowed: Optional[bool] = None
    doNotContact: Optional[bool] = None
    optOutSource: Optional[str] = Field(default=None, max_length=100)
    reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def require_preference_change(self):
        if not (
            self.model_fields_set
            & {"whatsappAllowed", "marketingAllowed", "doNotContact", "optOutSource"}
        ):
            raise ValueError("At least one communication preference must be supplied.")
        return self
