from typing import List, Optional

from pydantic import BaseModel

class UserUploadItemModel(BaseModel):
    username: str
    phoneNumber: str
    description: Optional[str] = None  # ← added

class BulkUserUploadRequestModel(BaseModel):
    users: list[UserUploadItemModel]