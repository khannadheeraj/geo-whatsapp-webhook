import logging

from fastapi import APIRouter, HTTPException

from app.services.template_service import get_templates


logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/template",
    tags=["Template"]
)


@router.get("/all")
async def get_all_templates():
    try:
        templates = get_templates()

        return {
            "success": True,
            "data": templates
        }

    except Exception as e:
        logger.exception(
            "Failed to fetch templates: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while fetching templates"
        )
