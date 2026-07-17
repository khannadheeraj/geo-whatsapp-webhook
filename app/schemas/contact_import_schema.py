from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.crm_model import LeadPriority, LeadStatus, PreferredMode


class ContactImportDefaultsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Optional[str] = Field(default=None, max_length=100)
    sourceDetails: Optional[str] = Field(default=None, max_length=500)
    status: LeadStatus = LeadStatus.NEW
    priority: LeadPriority = LeadPriority.MEDIUM
    preferredMode: Optional[PreferredMode] = None
    targetExamYear: Optional[int] = Field(default=None, ge=2020, le=2100)
    assignedCounsellorId: Optional[str] = Field(default=None, min_length=24, max_length=24)


class ContactImportPreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: Dict[str, str]
    defaults: ContactImportDefaultsModel = Field(default_factory=ContactImportDefaultsModel)
    duplicateMode: Literal["SKIP", "UPDATE_EMPTY_FIELDS"] = "SKIP"

    @model_validator(mode="after")
    def validate_mapping(self):
        allowed = {
            "firstName", "lastName", "fullName", "phone", "alternatePhone", "email",
            "city", "state", "companyOrCollege", "instagramProfile", "facebookProfile",
            "linkedinProfile", "source", "courseInterest", "preferredMode",
            "targetExamYear", "notes",
        }
        unknown = set(self.mapping) - allowed
        if unknown:
            raise ValueError(f"Unsupported import mapping fields: {', '.join(sorted(unknown))}")
        mapped = [value for value in self.mapping.values() if value]
        if "phone" not in self.mapping or not self.mapping.get("phone"):
            raise ValueError("Phone must be mapped.")
        if len(mapped) != len(set(mapped)):
            raise ValueError("A file column can be mapped only once.")
        return self
