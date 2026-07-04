from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "google-contacts.log"

logger = logging.getLogger("google-contacts")
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

logger.info("google-contacts MCP server bootstrap starting")

from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from shared.auth import GoogleAuth

SCOPES = [
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/userinfo.profile",
]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"

mcp = FastMCP("google-contacts")


def get_people_service():
    logger.info("Initializing People API service")
    auth = GoogleAuth(
        client_secrets_file=str(CLIENT_SECRETS),
        scopes=SCOPES,
        token_prefix="contacts",
    )
    creds = auth.get_credentials()
    logger.info("Google credentials loaded successfully")
    return build("people", "v1", credentials=creds)


@mcp.tool()
def search_contacts(query: str = "", page_size: int = 20) -> list[dict[str, Any]]:
    """Search Google Contacts using the People API.

    Args:
        query: Search term for name, email, or phone. Empty returns all.
        page_size: Max results (1-100, default 20).
    """
    logger.info("search_contacts called query=%r page_size=%s", query, page_size)

    try:
        service = get_people_service()
        request = service.people().connections().list(
            resourceName="people/me",
            personFields="names,emailAddresses,phoneNumbers,organizations",
            pageSize=min(page_size, 100),
        )
        if query:
            request = service.people().searchContacts(
                query=query,
                pageSize=min(page_size, 100),
                readMask="names,emailAddresses,phoneNumbers,organizations",
            )
            res = request.execute()
            results = res.get("results", [])
            out = []
            for r in results:
                person = r.get("person", {})
                out.append(_format_contact(person))
            return out

        res = request.execute()
        connections = res.get("connections", [])
        out = []
        for person in connections:
            out.append(_format_contact(person))
        return out

    except Exception:
        logger.exception("search_contacts failed")
        raise


@mcp.tool()
def get_contact_profile() -> dict[str, Any]:
    """Get the authenticated user's own Google profile (name, email, etc.)."""
    logger.info("get_contact_profile called")

    try:
        service = get_people_service()
        profile = service.people().get(
            resourceName="people/me",
            personFields="names,emailAddresses,phoneNumbers,organizations",
        ).execute()
        return _format_contact(profile)

    except Exception:
        logger.exception("get_contact_profile failed")
        raise


@mcp.tool()
def search_directory_people(query: str, page_size: int = 20) -> list[dict[str, Any]]:
    """Search the Google Workspace directory for people in the organization.

    Args:
        query: Search term for name or email.
        page_size: Max results (1-100, default 20).
    """
    logger.info("search_directory_people called query=%r", query)

    try:
        service = get_people_service()
        res = service.otherContacts().search(
            query=query,
            pageSize=min(page_size, 100),
            readMask="names,emailAddresses,phoneNumbers,organizations",
        ).execute()
        results = res.get("results", [])
        out = []
        for r in results:
            person = r.get("person", {})
            out.append(_format_contact(person))
        return out

    except Exception:
        logger.exception("search_directory_people failed")
        raise


@mcp.tool()
def create_contact(
    given_name: str,
    family_name: str = "",
    email: str = "",
    phone: str = "",
    organization: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Create a new Google Contact.

    Args:
        given_name: First name (required).
        family_name: Last name.
        email: Email address.
        phone: Phone number.
        organization: Company / organization name.
        title: Job title.
    """
    logger.info("create_contact called given_name=%r", given_name)

    try:
        service = get_people_service()

        body: dict[str, Any] = {"names": [{"givenName": given_name}]}
        if family_name:
            body["names"][0]["familyName"] = family_name
        if email:
            body.setdefault("emailAddresses", []).append({"value": email})
        if phone:
            body.setdefault("phoneNumbers", []).append({"value": phone})
        if organization:
            entry: dict[str, Any] = {"name": organization}
            if title:
                entry["title"] = title
            body.setdefault("organizations", []).append(entry)

        result = service.people().createContact(body=body).execute()
        logger.info("contact created resourceName=%s", result.get("resourceName"))
        return _format_contact(result)

    except Exception:
        logger.exception("create_contact failed")
        raise


@mcp.tool()
def update_contact(
    resource_name: str,
    given_name: str = "",
    family_name: str = "",
    email: str = "",
    phone: str = "",
    organization: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Update an existing Google Contact.

    Args:
        resource_name: The resource name of the contact (e.g. people/c12345).
        given_name: New first name.
        family_name: New last name.
        email: New email address.
        phone: New phone number.
        organization: New company / organization name.
        title: New job title.
    """
    logger.info("update_contact called resource_name=%s", resource_name)

    try:
        service = get_people_service()

        # Fetch current person to get etag (required by API for optimistic locking)
        current = (
            service.people()
            .get(
                resourceName=resource_name,
                personFields="names,emailAddresses,phoneNumbers,organizations",
            )
            .execute()
        )
        etag = current.get("etag")
        if not etag:
            return {"error": "Could not retrieve etag for contact"}

        body: dict[str, Any] = {"etag": etag}
        if given_name or family_name:
            name_entry: dict[str, str] = {}
            if given_name:
                name_entry["givenName"] = given_name
            if family_name:
                name_entry["familyName"] = family_name
            body["names"] = [name_entry]
        if email:
            body.setdefault("emailAddresses", []).append({"value": email})
        if phone:
            body.setdefault("phoneNumbers", []).append({"value": phone})
        if organization:
            org_entry: dict[str, str] = {"name": organization}
            if title:
                org_entry["title"] = title
            body.setdefault("organizations", []).append(org_entry)

        update_mask = ",".join(
            k for k in ("names", "emailAddresses", "phoneNumbers", "organizations")
            if k in body
        )
        if not update_mask:
            return {"error": "No fields to update"}

        result = (
            service.people()
            .updateContact(
                resourceName=resource_name,
                body=body,
                updatePersonFields=update_mask,
            )
            .execute()
        )
        logger.info("contact updated resourceName=%s", result.get("resourceName"))
        return _format_contact(result)

    except Exception:
        logger.exception("update_contact failed")
        raise


@mcp.tool()
def delete_contact(resource_name: str) -> dict[str, Any]:
    """Delete a Google Contact.

    Args:
        resource_name: The resource name of the contact (e.g. people/c12345).
    """
    logger.info("delete_contact called resource_name=%s", resource_name)

    try:
        service = get_people_service()
        service.people().deleteContact(resourceName=resource_name).execute()
        logger.info("contact deleted resourceName=%s", resource_name)
        return {"status": "deleted", "resourceName": resource_name}

    except Exception:
        logger.exception("delete_contact failed")
        raise


def _format_contact(person: dict[str, Any]) -> dict[str, Any]:
    names = person.get("names", [])
    emails = person.get("emailAddresses", [])
    phones = person.get("phoneNumbers", [])
    orgs = person.get("organizations", [])

    return {
        "resourceName": person.get("resourceName"),
        "name": names[0].get("displayName") if names else None,
        "givenName": names[0].get("givenName") if names else None,
        "familyName": names[0].get("familyName") if names else None,
        "email": emails[0].get("value") if emails else None,
        "phone": phones[0].get("value") if phones else None,
        "organization": orgs[0].get("name") if orgs else None,
        "title": orgs[0].get("title") if orgs else None,
    }


if __name__ == "__main__":
    try:
        logger.info("google-contacts MCP server started successfully")
        mcp.run()
    except KeyboardInterrupt:
        logger.info("google-contacts MCP server interrupted by user")
        raise
    except Exception:
        logger.exception("Fatal server error")
        raise
