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

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"

logger.info("Using client secrets file: %s", CLIENT_SECRETS)
logger.info("Client secrets exists: %s", CLIENT_SECRETS.exists())

mcp = FastMCP("google-gmail")


def get_gmail_service():
    logger.info("Initializing Gmail service")
    account = os.environ.get("GMAIL_ACCOUNT", "default")
    # Derive a unique token prefix per account (e.g. "gmail_info", "gmail_personal")
    account_slug = account.split("@")[0].replace(".", "_")
    token_prefix = f"gmail_{account_slug}"
    logger.info("Using token prefix=%s for account=%s", token_prefix, account)
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
