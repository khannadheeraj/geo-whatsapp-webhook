from typing import Any, Dict, List

import time


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

                extracted_events.append(
                    {
                        "eventType": "incoming_message",
                        "waMessageId": message.get("id"),
                        "from": message.get("from"),
                        "timestamp": message.get("timestamp"),
                        "messageType": message_type,
                        "text": text_body,
                        "buttonText": button_text,
                        "buttonPayload": button_payload,
                        "phoneNumberId": phone_number_id,
                        "displayPhoneNumber": display_phone_number,
                        "rawMessage": message,
                        "rawValue": value,
                        "creatTime":  int(time.time() * 1000),
                        "updateTime":  int(time.time() * 1000),
                    }
                )

            for status in value.get("statuses", []):

                extracted_events.append(
                    {
                        "eventType": "message_status",
                        "waMessageId": status.get("id"),
                        "recipientId": status.get("recipient_id"),
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "conversation": status.get("conversation"),
                        "pricing": status.get("pricing"),
                        "errors": status.get("errors"),
                        "phoneNumberId": phone_number_id,
                        "displayPhoneNumber": display_phone_number,
                        "rawStatus": status,
                        "rawValue": value,
                        "creatTime":  int(time.time() * 1000),
                        "updateTime":  int(time.time() * 1000),
                    }
                )

    return extracted_events