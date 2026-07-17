from typing import Any, Dict, List, Optional
import time


def _clean_text(value: Any, limit: int = 2000) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] or None


def _failure_fields(status: Dict[str, Any]) -> Dict[str, Any]:
    errors = status.get("errors")
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return {}
    error = errors[0]
    data = error.get("error_data") if isinstance(error.get("error_data"), dict) else {}
    details = {
        "title": _clean_text(error.get("title"), 200),
        "details": _clean_text(data.get("details"), 500),
    }
    return {
        "failureCode": str(error.get("code"))[:100] if error.get("code") is not None else None,
        "failureMessage": _clean_text(error.get("message") or error.get("title"), 500),
        "failureDetails": {key: value for key, value in details.items() if value},
    }


def extract_whatsapp_events(
    payload: Dict[str, Any]
) -> List[Dict[str, Any]]:

    extracted_events = []

    entries = payload.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])

        for change in changes:
            value = change.get("value", {})
            metadata = value.get("metadata", {})

            phone_number_id = metadata.get("phone_number_id")
            display_phone_number = metadata.get("display_phone_number")

            for message in value.get("messages", []):

                message_type = message.get("type")

                text_body = None
                button_text = None
                button_payload = None
                reply_type = None
                template_name = None
                template_language = None

                if message_type == "text":
                    text_body = message.get("text", {}).get("body")

                elif message_type == "button":
                    button = message.get("button", {})
                    button_text = button.get("text")
                    button_payload = button.get("payload")

                elif message_type == "interactive":
                    interactive = message.get("interactive", {})
                    interactive_type = interactive.get("type")

                    if interactive_type == "button_reply":
                        button_reply = interactive.get("button_reply", {})
                        button_text = button_reply.get("title")
                        button_payload = button_reply.get("id")
                        reply_type = "BUTTON_REPLY"

                    elif interactive_type == "list_reply":
                        list_reply = interactive.get("list_reply", {})
                        button_text = list_reply.get("title")
                        button_payload = list_reply.get("id")
                        reply_type = "LIST_REPLY"

                elif message_type == "template":
                    template = message.get("template", {})
                    language = template.get("language", {})
                    template_name = _clean_text(template.get("name"), 200)
                    template_language = _clean_text(language.get("code"), 50)

                context = message.get("context", {})

                extracted_events.append(
                    {
                        "eventType": "incoming_message",
                        "waMessageId": message.get("id"),
                        "eventKey": f"message:{message.get('id')}" if message.get("id") else None,

                        # This is important.
                        # It tells us which outbound WhatsApp message this click belongs to.
                        "contextMessageId": context.get("id"),
                        "contextFrom": context.get("from"),

                        "from": message.get("from"),
                        "timestamp": message.get("timestamp"),
                        "messageType": message_type,
                        "text": _clean_text(text_body),
                        "buttonText": _clean_text(button_text, 500),
                        "buttonPayload": _clean_text(button_payload, 500),
                        "replyType": reply_type,
                        "templateName": template_name,
                        "templateLanguage": template_language,
                        "phoneNumberId": phone_number_id,
                        "displayPhoneNumber": display_phone_number,
                        "createTime": int(time.time() * 1000),
                        "updateTime": int(time.time() * 1000),
                    }
                )

            for status in value.get("statuses", []):

                status_name = str(status.get("status") or "").lower()
                message_id = status.get("id")
                timestamp = status.get("timestamp")
                extracted_events.append(
                    {
                        "eventType": "message_status",
                        "waMessageId": message_id,
                        "eventKey": (
                            f"status:{message_id}:{status_name}:{timestamp}"
                            if message_id and status_name and timestamp else None
                        ),
                        "recipientId": status.get("recipient_id"),
                        "status": status_name,
                        "timestamp": timestamp,
                        **_failure_fields(status),
                        "phoneNumberId": phone_number_id,
                        "displayPhoneNumber": display_phone_number,
                        "createTime": int(time.time() * 1000),
                        "updateTime": int(time.time() * 1000),
                    }
                )

    return extracted_events
