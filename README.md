# GEO IAS WhatsApp backend

FastAPI backend for the GEO IAS CRM. The existing MongoDB, Meta configuration, webhook path, and deployment entry point (`main:app`) are preserved.

## Local setup

1. Create and activate a Python virtual environment.
2. Install `requirements.txt`; install `requirements-dev.txt` for tests.
3. Copy the names from `.env.example` into a local `.env` without committing it.
4. Configure a random `JWT_SECRET_KEY` of at least 32 characters and an explicit `AUTH_ALLOWED_ORIGINS` list.
5. Run `uvicorn main:app --reload`.

`ADMIN_USER_EMAIL` and `ADMIN_USER_PASSWORD` are retained in `.env.example` as deprecated names so existing deployment configuration is not renamed. They are intentionally ignored; no plaintext account is created or authenticated from them.

## Secure initial-user bootstrap

Create a protected local JSON file outside source control containing exactly two Super Admins and three or four Counsellors. Password fields are forbidden:

```json
[
  {"displayName": "Admin One", "email": "admin-one@example.invalid", "role": "SUPER_ADMIN"},
  {"displayName": "Admin Two", "email": "admin-two@example.invalid", "role": "SUPER_ADMIN"},
  {"displayName": "Counsellor One", "email": "counsellor-one@example.invalid", "role": "COUNSELLOR"},
  {"displayName": "Counsellor Two", "email": "counsellor-two@example.invalid", "role": "COUNSELLOR"},
  {"displayName": "Counsellor Three", "email": "counsellor-three@example.invalid", "role": "COUNSELLOR"}
]
```

Run:

```text
python scripts/bootstrap_users.py C:\protected\staff-users.json
```

The command prompts invisibly for each new user's temporary password, stores only Argon2id hashes, and forces password change at first login. Reruns skip existing normalized emails without asking for their passwords. The command never prints passwords or hashes.

## Authentication routes

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `POST /auth/change-password`

Only `GET /`, the authentication entry points, and `GET|POST /webhooks/whatsapp` are public. Templates require an authenticated staff session. Existing user-import, campaign, and analytics routes require `SUPER_ADMIN`.

## Verification

```text
python -m pytest -q
python -m compileall -q app main.py scripts
```
