from datetime import datetime, timezone

from app.utils.mongo_utils import public_document, serialize_value


def test_datetime_serialization_marks_aware_and_legacy_naive_values_as_utc():
    naive = datetime(2026, 7, 19, 8, 43)
    aware = datetime(2026, 7, 19, 8, 43, tzinfo=timezone.utc)
    assert serialize_value(naive) == "2026-07-19T08:43:00+00:00"
    assert serialize_value(aware) == "2026-07-19T08:43:00+00:00"
    assert public_document({"_id": "record", "createdAt": naive})["createdAt"].endswith("+00:00")
