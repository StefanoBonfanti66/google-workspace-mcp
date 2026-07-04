from __future__ import annotations

import base64
import logging
import os
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "google-gmail.log"

ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"
ATTACHMENTS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("google-gmail")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()
logger.propagate = False

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.DEBUG)
stderr_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

logger.addHandler(stderr_handler)
logger.addHandler(file_handler)

logger.info("google-gmail MCP server bootstrap starting")
logger.info("Resolved project root: %s", PROJECT_ROOT)

from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from shared.auth import GoogleAuth

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"

logger.info("Using client secrets file: %s", CLIENT_SECRETS)
logger.info("Client secrets exists: %s", CLIENT_SECRETS.exists())

mcp = FastMCP("google-gmail")


def get_gmail_service():
    logger.info("Initializing Gmail service")
    account_label = os.environ.get("GMAIL_ACCOUNT", "default")
    token_prefix = f"gmail_{account_label}"
    logger.info("Using token prefix=%s for account=%s", token_prefix, account_label)
    auth = GoogleAuth(
        client_secrets_file=str(CLIENT_SECRETS),
        scopes=SCOPES,
        token_prefix=token_prefix,
    )
    creds = auth.get_credentials()
    logger.info("Google credentials loaded successfully")
    return build("gmail", "v1", credentials=creds)


def _headers_to_dict(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers", []) or []
    out = {}
    for h in headers:
        name = h.get("name")
        value = h.get("value")
        if name and value:
            out[name.lower()] = value
    return out


def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []

    filename = payload.get("filename", "") or ""
    mime_type = payload.get("mimeType", "") or ""
    body = payload.get("body", {}) or {}

    if filename:
        attachments.append(
            {
                "filename": filename,
                "mimeType": mime_type,
                "attachmentId": body.get("attachmentId"),
                "size": body.get("size", 0),
                "partId": payload.get("partId"),
            }
        )

    for part in payload.get("parts", []) or []:
        attachments.extend(_extract_attachments(part))

    return attachments



def _download_attachment(service, message_id: str, attachment_id: str, filename: str) -> str:
    logger.info(
        "Downloading attachment message_id=%s attachment_id=%s filename=%r",
        message_id,
        attachment_id,
        filename,
    )
    res = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    data = res.get("data")
    if not data:
        raise RuntimeError("Attachment has no data field")
    import base64
    file_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))
    safe_name = filename or f"{message_id}_{attachment_id}"
    out_path = ATTACHMENTS_DIR / safe_name
    out_path.write_bytes(file_bytes)
    logger.info("Attachment saved to %s (%s bytes)", out_path, len(file_bytes))
    return str(out_path)


def _extract_plain_text(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}

    if mime == "text/plain" and body.get("data"):
        try:
            return base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="ignore")
        except Exception:
            logger.exception("Failed to decode text/plain body")
            return ""

    for part in payload.get("parts", []) or []:
        text = _extract_plain_text(part)
        if text:
            return text

    return ""


def _build_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a Gmail API message dict (raw base64url-encoded MIME)."""
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc

    msg.attach(MIMEText(body, "plain"))

    if attachment_paths:
        for filepath in attachment_paths:
            path = Path(filepath)
            if not path.exists():
                logger.warning("Attachment not found, skipping: %s", filepath)
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


@mcp.tool()
def create_draft(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Gmail draft.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
        cc: Optional CC recipient.
        bcc: Optional BCC recipient.
        attachment_paths: Optional list of local file paths to attach.
    """
    logger.info("create_draft called to=%r subject=%r", to, subject)
    try:
        service = get_gmail_service()
        message = _build_message(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachment_paths=attachment_paths,
        )
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": message})
            .execute()
        )
        result = {
            "id": draft.get("id"),
            "message_id": draft.get("message", {}).get("id"),
        }
        logger.info("create_draft succeeded id=%s", result["id"])
        return result
    except Exception:
        logger.exception("create_draft failed")
        raise


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Send an email immediately.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
        cc: Optional CC recipient.
        bcc: Optional BCC recipient.
        attachment_paths: Optional list of local file paths to attach.
    """
    logger.info("send_email called to=%r subject=%r", to, subject)
    try:
        service = get_gmail_service()
        message = _build_message(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, attachment_paths=attachment_paths,
        )
        sent = (
            service.users()
            .messages()
            .send(userId="me", body=message)
            .execute()
        )
        result = {
            "id": sent.get("id"),
            "threadId": sent.get("threadId"),
        }
        logger.info("send_email succeeded id=%s", result["id"])
        return result
    except Exception:
        logger.exception("send_email failed")
        raise


@mcp.tool()
def search_emails(query: str = "is:unread in:inbox", max_results: int = 10) -> list[dict[str, Any]]:
    """Search Gmail messages using Gmail query syntax and return a compact summary."""
    logger.info("search_emails called query=%r max_results=%s", query, max_results)

    try:
        service = get_gmail_service()
        res = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = res.get("messages", []) or []
        logger.info("Gmail API returned %s message refs", len(messages))

        out: list[dict[str, Any]] = []

        for item in messages:
            msg = service.users().messages().get(
                userId="me",
                id=item["id"],
                format="full",
            ).execute()

            payload = msg.get("payload", {}) or {}
            headers = _headers_to_dict(payload)
            snippet = msg.get("snippet", "") or ""
            attachments = _extract_attachments(payload)
            plain_text = _extract_plain_text(payload)

            raw_date = headers.get("date", "")
            iso_date = raw_date
            try:
                iso_date = parsedate_to_datetime(raw_date).isoformat()
            except Exception:
                logger.warning("Failed to parse email date: %r", raw_date)

            out.append(
                {
                    "id": msg.get("id"),
                    "threadId": msg.get("threadId"),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "date": iso_date,
                    "snippet": snippet,
                    "attachments_present": len(attachments) > 0,
                    "attachments_count": len(attachments),
                    "body_preview": plain_text[:1000],
                }
            )

        logger.info("search_emails returning %s messages", len(out))
        return out

    except Exception:
        logger.exception("search_emails failed")
        raise


@mcp.tool()
def get_email(message_id: str) -> dict[str, Any]:
    """Get a single Gmail message by ID with headers, snippet, and plain text preview."""
    logger.info("get_email called message_id=%s", message_id)

    try:
        service = get_gmail_service()
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

        payload = msg.get("payload", {}) or {}
        headers = _headers_to_dict(payload)
        attachments = _extract_attachments(payload)
        plain_text = _extract_plain_text(payload)

        result = {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "labelIds": msg.get("labelIds", []),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "attachments_present": len(attachments) > 0,
            "attachments_count": len(attachments),
            "attachments": attachments,
            "body_preview": plain_text[:4000],
        }

        logger.info("get_email succeeded message_id=%s", message_id)
        return result

    except Exception:
        logger.exception("get_email failed message_id=%s", message_id)
        raise



@mcp.tool()
def download_attachment(message_id: str, attachment_id: str, filename: str | None = None) -> dict[str, str]:
    """Download a single Gmail attachment to the local attachments/ folder.

    Returns the path on disk where the file was saved.
    """
    logger.info("download_attachment called message_id=%s attachment_id=%s", message_id, attachment_id)
    service = get_gmail_service()
    path = _download_attachment(service, message_id=message_id, attachment_id=attachment_id, filename=filename or "")
    return {
        "path": path,
        "message_id": message_id,
        "attachment_id": attachment_id,
    }


@mcp.tool()
def list_labels() -> list[dict[str, Any]]:
    """List all Gmail labels (both system and user-created)."""
    logger.info("list_labels called")
    try:
        service = get_gmail_service()
        res = service.users().labels().list(userId="me").execute()
        labels = res.get("labels", []) or []
        logger.info("list_labels returned %s labels", len(labels))
        return [
            {
                "id": lbl["id"],
                "name": lbl["name"],
                "type": lbl.get("type", ""),
                "messagesTotal": lbl.get("messagesTotal", 0),
                "messagesUnread": lbl.get("messagesUnread", 0),
            }
            for lbl in labels
        ]
    except Exception:
        logger.exception("list_labels failed")
        raise


def _resolve_label_id(service, label_name: str) -> str:
    """Resolve a label name to a Gmail label ID, creating it if not found."""
    logger.info("Resolving label name=%r", label_name)

    res = service.users().labels().list(userId="me").execute()
    labels = res.get("labels", []) or []

    for lbl in labels:
        if lbl["name"] == label_name:
            logger.info("Found existing label id=%s for name=%s", lbl["id"], label_name)
            return lbl["id"]

    logger.info("Label %r not found, creating it", label_name)
    created = (
        service.users()
        .labels()
        .create(userId="me", body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"})
        .execute()
    )
    logger.info("Created label id=%s for name=%s", created["id"], label_name)
    return created["id"]


@mcp.tool()
def apply_label(message_id: str, label_name: str) -> dict[str, Any]:
    """Apply a label to a Gmail message. Creates the label if it doesn't exist.

    Args:
        message_id: The Gmail message ID.
        label_name: The label name (e.g. \"Follow-up\", \"Project X\").
    """
    logger.info("apply_label called message_id=%s label_name=%r", message_id, label_name)
    try:
        service = get_gmail_service()
        label_id = _resolve_label_id(service, label_name)
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        result = {"message_id": message_id, "label": label_name, "label_id": label_id}
        logger.info("apply_label succeeded: %s", result)
        return result
    except Exception:
        logger.exception("apply_label failed")
        raise


@mcp.tool()
def remove_label(message_id: str, label_name: str) -> dict[str, Any]:
    """Remove a label from a Gmail message.

    Args:
        message_id: The Gmail message ID.
        label_name: The label name (e.g. \"Follow-up\", \"Project X\").
    """
    logger.info("remove_label called message_id=%s label_name=%r", message_id, label_name)
    try:
        service = get_gmail_service()
        label_id = _resolve_label_id(service, label_name)
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": [label_id]},
        ).execute()
        result = {"message_id": message_id, "label": label_name, "label_id": label_id}
        logger.info("remove_label succeeded: %s", result)
        return result
    except Exception:
        logger.exception("remove_label failed")
        raise


@mcp.tool()
def get_auto_reply() -> dict[str, Any]:
    """Get the current auto-reply (vacation responder) settings."""
    logger.info("get_auto_reply called")
    try:
        service = get_gmail_service()
        vac = service.users().settings().getVacation(userId="me").execute()
        logger.info("get_auto_reply succeeded: %s", vac)
        return dict(vac)
    except Exception:
        logger.exception("get_auto_reply failed")
        raise


@mcp.tool()
def set_auto_reply(
    enabled: bool,
    message: str,
    subject: str | None = None,
    restrict_to_contacts: bool = False,
    restrict_to_domain: bool = False,
    start_time: int | None = None,
    end_time: int | None = None,
) -> dict[str, Any]:
    """Set auto-reply (vacation responder) settings.

    Args:
        enabled: Whether auto-reply is enabled.
        message: Plain text auto-reply message.
        subject: Optional subject line for the auto-reply.
        restrict_to_contacts: Only send auto-reply to contacts.
        restrict_to_domain: Only send auto-reply to users in the same domain.
        start_time: Optional Unix timestamp (seconds) for when to start.
        end_time: Optional Unix timestamp (seconds) for when to end.
    """
    logger.info("set_auto_reply called enabled=%s", enabled)
    try:
        service = get_gmail_service()
        body: dict[str, Any] = {
            "enableAutoReply": enabled,
            "responseBodyPlainText": message,
        }
        if subject is not None:
            body["responseSubject"] = subject
        if restrict_to_contacts:
            body["restrictToContacts"] = True
        if restrict_to_domain:
            body["restrictToDomain"] = True
        if start_time is not None:
            body["startTime"] = start_time
        if end_time is not None:
            body["endTime"] = end_time

        vac = service.users().settings().updateVacation(userId="me", body=body).execute()
        logger.info("set_auto_reply succeeded: %s", vac)
        return dict(vac)
    except Exception:
        logger.exception("set_auto_reply failed")
        raise


if __name__ == "__main__":
    try:
        logger.info("google-gmail MCP server started successfully")
        logger.info("Starting FastMCP stdio run loop")
        mcp.run()
    except KeyboardInterrupt:
        logger.info("google-gmail MCP server interrupted by user")
        raise
    except Exception:
        logger.exception("Fatal server error")
        raise
