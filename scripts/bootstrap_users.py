import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import validate_security_configuration
from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.services.bootstrap_service import bootstrap_users


def password_provider(user):
    label = f"{user['displayName']} <{user['email']}>"
    first = getpass.getpass(f"Temporary password for {label}: ")
    second = getpass.getpass(f"Confirm temporary password for {label}: ")
    if first != second:
        raise ValueError("Temporary passwords do not match")
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotently bootstrap GEO IAS staff users")
    parser.add_argument("manifest", help="Path to a protected JSON manifest (passwords are forbidden)")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise ValueError("Manifest must be a JSON array")
    validate_security_configuration()
    connect_to_mongo()
    try:
        result = bootstrap_users(manifest, password_provider)
        print(f"Bootstrap complete: {result['created']} created, {result['existing']} already present.")
    finally:
        close_mongo_connection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
