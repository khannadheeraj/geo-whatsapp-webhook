from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument

from app.db.mongodb import get_collection


def insert_import_job(document: Dict[str, Any]) -> Dict[str, Any]:
    document.setdefault("_id", ObjectId())
    get_collection("import_jobs").insert_one(document)
    return document


def insert_import_rows(documents: List[Dict[str, Any]]) -> None:
    if documents:
        get_collection("import_job_rows").insert_many(documents)


def find_import_job(import_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("import_jobs").find_one({"_id": import_id, "entityType": "CONTACT_IMPORT"})


def update_import_job(import_id: ObjectId, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("import_jobs").find_one_and_update(
        {"_id": import_id, "entityType": "CONTACT_IMPORT"},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


def list_import_rows(
    import_id: ObjectId,
    *,
    page: int,
    page_size: int,
    statuses: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    query: Dict[str, Any] = {"importId": import_id}
    if statuses:
        query["validationStatus"] = {"$in": statuses}
    collection = get_collection("import_job_rows")
    total = collection.count_documents(query)
    rows = list(
        collection.find(query)
        .sort([("rowNumber", 1), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return rows, total


def all_import_rows(import_id: ObjectId) -> List[Dict[str, Any]]:
    return list(get_collection("import_job_rows").find({"importId": import_id}).sort("rowNumber", 1))


def update_import_row(row_id: ObjectId, updates: Dict[str, Any]) -> None:
    get_collection("import_job_rows").update_one({"_id": row_id}, {"$set": updates})


def claim_import_commit(import_id: ObjectId, now: Any, lease_until: Any) -> Optional[Dict[str, Any]]:
    return get_collection("import_jobs").find_one_and_update(
        {
            "_id": import_id,
            "entityType": "CONTACT_IMPORT",
            "$or": [
                {"status": "PREVIEWED"},
                {"status": "COMMITTING", "commitLeaseUntil": {"$lte": now}},
            ],
        },
        {"$set": {"status": "COMMITTING", "commitLeaseUntil": lease_until, "updatedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
