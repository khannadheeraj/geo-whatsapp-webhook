from pydantic import BaseModel


class LoginRequestModel(BaseModel):
    emailId: str
    password: str