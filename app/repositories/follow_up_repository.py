from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId
from pymongo import ReturnDocument
from app.db.mongodb import get_collection

def insert(document: Dict[str, Any]):
    result = get_collection("follow_up_tasks").insert_one(document); document["_id"] = result.inserted_id; return document
def find(task_id: ObjectId): return get_collection("follow_up_tasks").find_one({"_id": task_id})
def list_tasks(query: Dict[str, Any], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("follow_up_tasks"); total = collection.count_documents(query)
    return list(collection.find(query).sort([("dueAt", 1), ("_id", 1)]).skip((page - 1) * page_size).limit(page_size)), total
def update(task_id: ObjectId, version: int, query: Dict[str, Any], updates: Dict[str, Any]):
    return get_collection("follow_up_tasks").find_one_and_update({"_id": task_id, "version": version, **query}, {"$set": updates, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER)
