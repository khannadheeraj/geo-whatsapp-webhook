from typing import List

from pydantic import BaseModel


class UserPayloadModel(BaseModel):
    username: str
    phoneNumber: str


class BulkUserUploadRequestModel(BaseModel):
    users: List[UserPayloadModel]
