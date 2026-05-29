from collections import defaultdict

from fastapi import APIRouter, Query
from app.db.mongodb import get_collection


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)


@router.get("/campaign/{campaign_name}")
async def get_campaign_analytics(
    campaign_name: str,
    page: int = Query(0, ge=0),
    size: int = Query(10, ge=1)
):

    whatsapp_message_logs = get_collection(
        "whatsapp_message_logs"
    )

    whatsapp_events = get_collection(
        "whatsapp_events"
    )

    # ==================================================
    # Pagination
    # ==================================================

    skip = page * size

    total_records = whatsapp_message_logs.count_documents(
        {
            "campaignName": campaign_name
        }
    )

    pagination = {
        "page": page,
        "size": size,
        "totalRecords": total_records,
        "totalPages": (
            (total_records + size - 1) // size
        ),
        "hasNext": (
            skip + size < total_records
        ),
        "hasPrevious": page > 0
    }

    # ==================================================
    # Fetch paginated logs
    # ==================================================

    message_logs = list(
        whatsapp_message_logs.find(
            {
                "campaignName": campaign_name
            },
            {
                "_id": 0
            }
        )
        .sort("createTime", -1)
        .skip(skip)
        .limit(size)
    )

    wa_message_ids = [
        log.get("waMessageId")
        for log in message_logs
        if log.get("waMessageId")
    ]

    # ==================================================
    # Fetch ALL related events in ONE query
    # ==================================================

    all_events = list(
        whatsapp_events.find(
            {
                "eventType": "message_status",
                "waMessageId": {
                    "$in": wa_message_ids
                }
            },
            {
                "_id": 0,
                "waMessageId": 1,
                "status": 1,
                "timestamp": 1,
                "errors": 1,
                "createTime": 1
            }
        ).sort("createTime", 1)
    )

    # ==================================================
    # Group events by waMessageId
    # ==================================================

    events_map = defaultdict(list)

    for event in all_events:

        wa_message_id = event.get("waMessageId")

        if wa_message_id:
            events_map[wa_message_id].append(event)

    analytics_data = []

    # ==================================================
    # Build analytics response
    # ==================================================

    for log in message_logs:

        wa_message_id = log.get("waMessageId")

        events = events_map.get(
            wa_message_id,
            []
        )

        latest_event = (
            events[-1]
            if events
            else None
        )

        final_status = (
            latest_event.get("status", "SENT").upper()
            if latest_event
            else log.get("status", "SENT")
        )

        failed_reason = None

        if final_status == "FAILED" and latest_event:

            errors = latest_event.get("errors") or []

            if errors and isinstance(errors, list):

                first_error = errors[0]

                failed_reason = (
                    first_error.get("title")
                    or first_error.get("message")
                    or str(first_error)
                )

        status_history = [
            {
                "status": (
                    e.get("status", "")
                    .upper()
                ),
                "timestamp": e.get("timestamp"),
                "createTime": e.get("createTime")
            }
            for e in events
        ]

        analytics_data.append(
            {
                "phone": log.get("phone"),
                "name": log.get("name"),
                "campaignName": log.get("campaignName"),
                "templateName": log.get("templateName"),
                "messagePurpose": log.get("messagePurpose"),
                "waMessageId": wa_message_id,

                "status": final_status,

                "failedReason": failed_reason,

                "metaMessageStatus": (
                    log.get("apiResponse", {})
                    .get("messages", [{}])[0]
                    .get("message_status")
                ),

                "statusHistory": status_history,

                "createTime": log.get("createTime"),
                "updateTime": log.get("updateTime"),
            }
        )

    # ==================================================
    # Summary
    # ==================================================

    campaign_wa_message_ids = list(
        whatsapp_message_logs.distinct(
            "waMessageId",
            {
                "campaignName": campaign_name,
                "waMessageId": {
                    "$ne": None
                }
            }
        )
    )


    summary = {
        "total": total_records,
        "sent": 0,
        "delivered": 0,
        "read": 0,
        "failed": 0,
    }

    status_summary = list(
        whatsapp_events.aggregate([
            {
                "$match": {
                    "eventType": "message_status",
                    "waMessageId": {
                        "$in": campaign_wa_message_ids
                    }
                }
            },
            {
                "$sort": {
                    "createTime": -1
                }
            },
            {
                "$group": {
                    "_id": "$waMessageId",
                    "latestStatus": {
                        "$first": "$status"
                    }
                }
            },
            {
                "$group": {
                    "_id": {
                        "$toUpper": "$latestStatus"
                    },
                    "count": {
                        "$sum": 1
                    }
                }
            }
        ])
    )

    for item in status_summary:

        status = str(item.get("_id", "")).upper()
        count = item.get("count", 0)

        if status == "SENT":
            summary["sent"] = count

        elif status == "DELIVERED":
            summary["delivered"] = count

        elif status == "READ":
            summary["read"] = count

        elif status == "FAILED":
            summary["failed"] = count




    return {
        "success": True,
        "campaignName": campaign_name,
        "pagination": pagination,
        "summary": summary,
        "data": analytics_data
    }




@router.get("/campaign/{campaign_name}/summary")
async def get_campaign_summary(
    campaign_name: str
):


    # -------------------------------------
    # Get campaign message ids
    # -------------------------------------

    

    campaign_recipients = get_collection(
        "campaign_recipients"
    )

    whatsapp_events = get_collection(
        "whatsapp_events"
    )



    campaign_message_ids = (
        campaign_recipients.distinct(
            "initialWaMessageId",
            "phone",
            {
                "campaignName": campaign_name,
                "initialWaMessageId": {
                    "$nin": [None, ""]
                }
            }
        )
    )

    logger.critical(f"campaign_message_ids======>{campaign_message_ids}")

    if not campaign_message_ids:
        return {
            "campaignName": campaign_name,
            "total": 0,
            "sent": 0,
            "delivered": 0,
            "read": 0
        }

    total = len(campaign_message_ids)

    # -------------------------------------
    # Event Summary
    # -------------------------------------

    pipeline = [
        {
            "$match": {
                "initialWaMessageId": {
                    "$in": campaign_message_ids
                },
                "status": {
                    "$in": [
                        "sent",
                        "delivered",
                        "read"
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$status",
                "messageIds": {
                    "$addToSet": "$initialWaMessageId"
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "status": "$_id",
                "count": {
                    "$size": "$messageIds"
                }
            }
        }
    ]

    aggregation_result = list(
        whatsapp_events.aggregate(
            pipeline
        )
    )

    summary = {
        "campaignName": campaign_name,
        "total": total,
        "sent": 0,
        "delivered": 0,
        "read": 0
    }

    for item in aggregation_result:

        summary[
            item["status"]
        ] = item["count"]

    return summary