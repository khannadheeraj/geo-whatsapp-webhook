from datetime import datetime
from pydantic import BaseModel, field_validator

class FollowUpReminderSnoozeModel(BaseModel):
    snoozedUntil: datetime
    @field_validator("snoozedUntil")
    @classmethod
    def future_aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("snoozedUntil must include a timezone offset")
        return value
