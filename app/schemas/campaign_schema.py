from typing import List
from pydantic import BaseModel


class LeadInviteModel(BaseModel):
    name: str
    phone: str


class CampaignInviteRequestModel(BaseModel):
    leads: List[LeadInviteModel]


class UpscFoundationAdmissionOpenRequestModel(BaseModel):
    campaignName: str
    admissionOpenFrom: str
    admissionOpenTo: str
    classesStart: str
    leads: List[LeadInviteModel]