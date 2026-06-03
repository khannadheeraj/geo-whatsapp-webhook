from typing import List
from pydantic import BaseModel


class LeadInviteModel(BaseModel):
    name: str
    phone: str


class CampaignInviteRequestModel(BaseModel):
    leads: List[LeadInviteModel]


class UpscFoundationAdmissionOpenRequestModel(BaseModel):
    admissionOpenFrom: str
    admissionOpenTo: str
    classesStart: str
    leads: List[LeadInviteModel]