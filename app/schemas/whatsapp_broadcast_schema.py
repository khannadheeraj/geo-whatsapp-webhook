from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class BroadcastVariableMappingModel(BaseModel):
    source: Literal["CONTACT", "LEAD", "FIXED"]
    field: Optional[str] = Field(default=None, max_length=100)
    value: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_source(self):
        if self.source == "FIXED" and not (self.value or "").strip():
            raise ValueError("A fixed mapping requires a value.")
        if self.source != "FIXED" and not (self.field or "").strip():
            raise ValueError("A field mapping requires a field.")
        return self


class BroadcastCreateModel(BaseModel):
    templateId: str = Field(min_length=1, max_length=100)
    recipientFilters: Dict[str, Any] = Field(default_factory=dict)
    variableMappings: List[BroadcastVariableMappingModel] = Field(default_factory=list, max_length=50)


class BroadcastPrepareModel(BaseModel):
    version: int = Field(ge=1)


class BroadcastVersionModel(BaseModel):
    version: int = Field(ge=1)


class BroadcastBatchModel(BaseModel):
    batchSize: int = Field(default=10, ge=1, le=50)
