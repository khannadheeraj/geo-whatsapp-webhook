from fastapi import APIRouter, Depends

from app.api.dependencies.auth import require_authenticated_user
from app.services.dashboard_service import dashboard_summary


router = APIRouter(prefix="/dashboards", tags=["Dashboards"])


@router.get("/summary")
async def dashboard_summary_route(user=Depends(require_authenticated_user)):
    return {"data": dashboard_summary(user)}
