from pydantic import BaseModel


class UserModel(BaseModel):
    username: str
    phoneNumber: str
    normalizedPhone: str
    createTime: int
    updateTime: int
