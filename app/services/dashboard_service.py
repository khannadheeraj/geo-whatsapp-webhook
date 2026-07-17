from typing import Any, Dict

from app.db.mongodb import get_collection
from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE, CONTACT_ENTITY_TYPE
from app.models.user_model import STAFF_USER_ENTITY_TYPE, UserRole


def dashboard_summary(actor: Dict[str, Any]) -> Dict[str, int]:
    is_admin = actor.get("role") == UserRole.SUPER_ADMIN.value
    lead_query: Dict[str, Any] = {
        "entityType": ADMISSION_LEAD_ENTITY_TYPE,
        "isActive": True,
    }
    if not is_admin:
        lead_query["assignedCounsellorId"] = actor["_id"]
    leads = get_collection("leads")
    requests = get_collection("reassignment_requests")
    request_query: Dict[str, Any] = {"status": "PENDING"}
    if not is_admin:
        request_query["requestedBy"] = actor["_id"]
    result = {
        "activeLeads" if is_admin else "myLeads": leads.count_documents(lead_query),
        "new": leads.count_documents({**lead_query, "status": "NEW"}),
        "needsContact": leads.count_documents({**lead_query, "status": "NEEDS_CONTACT"}),
        "interested": leads.count_documents({**lead_query, "status": "INTERESTED"}),
        "pendingReassignmentRequests": requests.count_documents(request_query),
    }
    if is_admin:
        result.update(
            {
                "totalContacts": get_collection("contacts").count_documents(
                    {"entityType": CONTACT_ENTITY_TYPE}
                ),
                "unassignedLeads": leads.count_documents(
                    {**lead_query, "assignedCounsellorId": None}
                ),
                "activeCounsellors": get_collection("users").count_documents(
                    {
                        "entityType": STAFF_USER_ENTITY_TYPE,
                        "role": UserRole.COUNSELLOR.value,
                        "isActive": True,
                    }
                ),
            }
        )
    return result
