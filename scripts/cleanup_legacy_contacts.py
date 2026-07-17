"""Dry-run-first cleanup for obsolete Contact-like records in the users collection.

This utility is intentionally manual and is never imported by application startup.
It never drops the users collection or an index. Review the Phase 1B cleanup
runbook before considering its explicit execution mode.
"""

import argparse
from collections import Counter
from typing import Any, Iterable, Set

from app.db.mongodb import close_mongo_connection, connect_to_mongo, get_collection
from app.models.user_model import STAFF_USER_ENTITY_TYPE, UserRole


CONFIRMATION = "DELETE_LEGACY_CONTACTS"


def _referenced_user_ids() -> Set[Any]:
    protected: Set[Any] = set()
    protected.update(
        get_collection("user_sessions").distinct("userId", {"userId": {"$exists": True}})
    )
    protected.update(
        get_collection("leads").distinct(
            "assignedCounsellorId", {"assignedCounsellorId": {"$ne": None}}
        )
    )
    assignments = get_collection("lead_assignments")
    protected.update(assignments.distinct("fromCounsellorId", {"fromCounsellorId": {"$ne": None}}))
    protected.update(assignments.distinct("toCounsellorId", {"toCounsellorId": {"$ne": None}}))
    protected.update(
        get_collection("users").distinct(
            "_id",
            {
                "role": {"$in": [UserRole.SUPER_ADMIN.value, UserRole.COUNSELLOR.value]},
                "isActive": True,
            },
        )
    )
    return {item for item in protected if item is not None}


def _candidate_documents() -> list[dict[str, Any]]:
    protected = _referenced_user_ids()
    return list(
        get_collection("users").find(
            {
                "entityType": {"$ne": STAFF_USER_ENTITY_TYPE},
                "_id": {"$nin": list(protected)},
            }
        )
    )


def _shape_summary(documents: Iterable[dict[str, Any]]) -> Counter:
    summary: Counter = Counter()
    for document in documents:
        for key in document:
            if key != "_id":
                summary[key] += 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Review obsolete Contact-like users records.")
    parser.add_argument("--execute", action="store_true", help="Enable deletion after every safety gate.")
    parser.add_argument("--confirm", default="", help=f"Must equal {CONFIRMATION} for execution.")
    parser.add_argument("--backup-id", default="", help="Operator-recorded database backup identifier.")
    parser.add_argument(
        "--export-confirmed",
        action="store_true",
        help="Confirm a protected export of the exact candidate IDs/documents already exists.",
    )
    args = parser.parse_args()

    connect_to_mongo()
    try:
        users = get_collection("users")
        total = users.count_documents({})
        staff = users.count_documents({"entityType": STAFF_USER_ENTITY_TYPE})
        candidates = _candidate_documents()
        print(f"users total: {total}")
        print(f"staff users excluded: {staff}")
        print(f"legacy cleanup candidates: {len(candidates)}")
        print("candidate shape summary (field: record count):")
        for field, count in sorted(_shape_summary(candidates).items()):
            print(f"  {field}: {count}")

        if not args.execute:
            print("DRY RUN ONLY: no records were deleted.")
            print("Before execution: create and verify a database backup and protected candidate export.")
            print("Rollback after deletion requires restoring/export-reimporting data and may conflict with later writes.")
            return 0
        if args.confirm != CONFIRMATION:
            parser.error(f"--confirm must equal {CONFIRMATION}")
        if not args.backup_id.strip():
            parser.error("--backup-id is required for execution")
        if not args.export_confirmed:
            parser.error("--export-confirmed is required for execution")
        if not candidates:
            print("No candidate records exist; nothing was deleted.")
            return 0
        candidate_ids = [document["_id"] for document in candidates]
        result = users.delete_many(
            {
                "_id": {"$in": candidate_ids},
                "entityType": {"$ne": STAFF_USER_ENTITY_TYPE},
            }
        )
        print(f"Deleted legacy records: {result.deleted_count}")
        print("The users collection, staff users, sessions, assignments, and indexes were retained.")
        return 0
    finally:
        close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(main())
