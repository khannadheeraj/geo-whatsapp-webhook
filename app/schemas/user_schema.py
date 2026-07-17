from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.user_model import UserRole


class StaffUserCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    role: UserRole
    temporaryPassword: str = Field(min_length=1, max_length=128)
    confirmTemporaryPassword: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.temporaryPassword != self.confirmTemporaryPassword:
            raise ValueError("Temporary passwords must match.")
        return self


class StaffUserPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    displayName: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    isActive: Optional[bool] = None

    @model_validator(mode="after")
    def require_change(self):
        if not (self.model_fields_set - {"version"}):
            raise ValueError("At least one staff field must be supplied.")
        return self


class StaffPasswordResetModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporaryPassword: str = Field(min_length=1, max_length=128)
    confirmTemporaryPassword: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.temporaryPassword != self.confirmTemporaryPassword:
            raise ValueError("Temporary passwords must match.")
        return self
