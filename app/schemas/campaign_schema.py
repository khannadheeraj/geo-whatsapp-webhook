from typing import List
from pydantic import BaseModel


class LeadInviteModel(BaseModel):
    name: str
    phone: str


class CampaignInviteRequestModel(BaseModel):
    leads: List[LeadInviteModel]