from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.db.mongodb import get_collection


def list_conversations(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(get_collection("conversations").find(query).sort([
        ("latestMessageAt", DESCENDING), ("_id", DESCENDING),
    ]))


def find_conversation(conversation_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("conversations").find_one({"_id": conversation_id})


def latest_message(conversation_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_messages").find_one(
        {"conversationId": conversation_id}, sort=[("createdAt", DESCENDING), ("_id", DESCENDING)]
    )


def latest_inbound_message(conversation_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_messages").find_one({"conversationId": conversation_id, "direction": "INBOUND"}, sort=[("createdAt", DESCENDING), ("_id", DESCENDING)])


def messages_after_view(conversation_id: ObjectId, viewed_at: Optional[datetime]) -> int:
    query: Dict[str, Any] = {"conversationId": conversation_id, "direction": "INBOUND"}
    if viewed_at is not None:
        query["createdAt"] = {"$gt": viewed_at}
    return get_collection("whatsapp_messages").count_documents(query)


def find_inbox_read(user_id: ObjectId, conversation_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_inbox_reads").find_one({"userId": user_id, "conversationId": conversation_id})


def mark_viewed(user_id: ObjectId, conversation_id: ObjectId, viewed_at: datetime) -> Dict[str, Any]:
    collection = get_collection("whatsapp_inbox_reads")
    collection.update_one(
        {"userId": user_id, "conversationId": conversation_id},
        {"$set": {"viewedAt": viewed_at, "updatedAt": viewed_at}, "$setOnInsert": {"userId": user_id, "conversationId": conversation_id, "createdAt": viewed_at}},
        upsert=True,
    )
    return collection.find_one({"userId": user_id, "conversationId": conversation_id})


def list_messages_after_cursor(conversation_id: ObjectId, cursor: Optional[Tuple[datetime, ObjectId]], limit: int) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"conversationId": conversation_id}
    if cursor:
        created_at, message_id = cursor
        query["$or"] = [{"createdAt": {"$gt": created_at}}, {"createdAt": created_at, "_id": {"$gt": message_id}}]
    return list(get_collection("whatsapp_messages").find(query).sort([("createdAt", ASCENDING), ("_id", ASCENDING)]).limit(limit))
