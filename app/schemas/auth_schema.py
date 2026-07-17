from pydantic import BaseModel, ConfigDict, Field


class LoginRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emailId: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)
