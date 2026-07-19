from typing import List

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppTemplateSendModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contactId: str = Field(min_length=24, max_length=24)
    templateId: str = Field(min_length=24, max_length=24)
    variableValues: List[str] = Field(default_factory=list, max_length=50)
