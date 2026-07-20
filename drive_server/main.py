from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "google-drive.log"

logger = logging.getLogger("google-drive")
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

logger.info("google-drive MCP server bootstrap starting")
logger.info("Resolved project root: %s", PROJECT_ROOT)

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from mcp.server.fastmcp import FastMCP

from shared.auth import GoogleAuth

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"

logger.info("Using client secrets file: %s", CLIENT_SECRETS)
logger.info("Client secrets exists: %s", CLIENT_SECRETS.exists())

mcp = FastMCP("google-drive")


def get_drive_service():
    logger.info("Initializing Drive service")
    account_label = os.environ.get("DRIVE_ACCOUNT", "default")
    token_prefix = f"drive_{account_label}" if account_label != "default" else "drive"
    logger.info("Using token prefix=%s for account=%s", token_prefix, account_label)
    auth = GoogleAuth(
        client_secrets_file=str(CLIENT_SECRETS),
        scopes=SCOPES,
        token_prefix=token_prefix,
    )
    creds = auth.get_credentials()
    logger.info("Google Drive credentials loaded successfully")
    return build("drive", "v3", credentials=creds)


@mcp.tool()
def search_files(
    query: str | None = None,
    name: str | None = None,
    mime_type: str | None = None,
    parent_id: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """Search for files in Google Drive.

    Args:
        query: Free-text search terms, or raw Drive API query.
        name: Name or part of name of the file to search for.
        mime_type: MIME type of the file (e.g. 'application/vnd.google-apps.folder', 'application/pdf').
        parent_id: ID of the parent folder to search within.
        max_results: Maximum results to return.
    """
    logger.info("search_files called query=%r name=%r mime_type=%r parent_id=%r", query, name, mime_type, parent_id)
    try:
        service = get_drive_service()
        
        # Build query clauses
        clauses = ["trashed = false"]
        
        if query:
            # We can use the query parameter. If it looks like a valid Drive API query (contains equals, contains, etc.),
            # we can treat it as raw query. Otherwise, we treat it as fullText search.
            if any(op in query for op in ["=", "contains", "mimeType", "parents", "name"]):
                clauses.append(query)
            else:
                # Escape single quotes in the query
                escaped_query = query.replace("'", "\\'")
                clauses.append(f"fullText contains '{escaped_query}'")
        
        if name:
            escaped_name = name.replace("'", "\\'")
            clauses.append(f"name contains '{escaped_name}'")
            
        if mime_type:
            clauses.append(f"mimeType = '{mime_type}'")
            
        if parent_id:
            clauses.append(f"'{parent_id}' in parents")
            
        q = " and ".join(clauses)
        logger.info("Drive API search query constructed: %s", q)
        
        res = service.files().list(
            q=q,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, parents, size, modifiedTime)",
            pageSize=max_results,
        ).execute()
        
        files = res.get("files", []) or []
        logger.info("search_files found %s files", len(files))
        return files
    except Exception:
        logger.exception("search_files failed")
        raise


@mcp.tool()
def download_file(file_id: str, dest_name: str | None = None) -> dict[str, str]:
    """Download a file from Google Drive to the local attachments/ folder.
    
    If it is a Google document (Doc, Sheet, Slide), it will be exported to PDF/OpenOffice format.
    
    Args:
        file_id: The ID of the file on Google Drive.
        dest_name: Optional name for the downloaded file on disk.
    """
    logger.info("download_file called file_id=%s dest_name=%r", file_id, dest_name)
    try:
        service = get_drive_service()
        
        # Get file metadata
        meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()
        name = meta.get("name", "untitled")
        mime = meta.get("mimeType", "")
        
        attachments_dir = PROJECT_ROOT / "attachments"
        attachments_dir.mkdir(exist_ok=True)
        
        is_google_app = mime.startswith("application/vnd.google-apps.")
        
        if is_google_app:
            # We must export it
            # Map Google Apps types to export formats
            export_mappings = {
                "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
                "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
                "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
            }
            if mime in export_mappings:
                export_mime, ext = export_mappings[mime]
                safe_name = dest_name or (name if name.endswith(ext) else name + ext)
                out_path = attachments_dir / safe_name
                
                logger.info("Exporting Google App document mime=%s as %s", mime, export_mime)
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            else:
                raise ValueError(f"Cannot download/export Google App type: {mime}")
        else:
            # Regular binary file download
            safe_name = dest_name or name
            out_path = attachments_dir / safe_name
            logger.info("Downloading binary file mime=%s", mime)
            request = service.files().get_media(fileId=file_id)
            
        fh = io.FileIO(out_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            logger.debug("Download progress: %d%%", int(status.progress() * 100))
            
        logger.info("Download completed. File saved to %s", out_path)
        return {
            "status": "success",
            "path": str(out_path),
            "filename": safe_name,
            "mimeType": mime,
        }
    except Exception:
        logger.exception("download_file failed")
        raise


@mcp.tool()
def list_folder_contents(folder_id: str = "root", max_results: int = 50) -> list[dict[str, Any]]:
    """List the contents of a specific folder on Google Drive.

    Args:
        folder_id: The ID of the folder (default is 'root').
        max_results: Maximum number of files to return.
    """
    logger.info("list_folder_contents called folder_id=%s", folder_id)
    try:
        service = get_drive_service()
        q = f"'{folder_id}' in parents and trashed = false"
        res = service.files().list(
            q=q,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            pageSize=max_results,
        ).execute()
        files = res.get("files", []) or []
        logger.info("list_folder_contents found %s files", len(files))
        return files
    except Exception:
        logger.exception("list_folder_contents failed")
        raise


@mcp.tool()
def move_file(file_id: str, folder_id: str) -> dict[str, Any]:
    """Move a file to a different folder.

    Args:
        file_id: The ID of the file to move.
        folder_id: The ID of the destination folder.
    """
    logger.info("move_file called file_id=%s folder_id=%s", file_id, folder_id)
    try:
        service = get_drive_service()
        
        # Get existing parents
        file = service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []) or [])
        
        # Move the file by adding the new parent and removing the old ones
        updated = service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, name, parents",
        ).execute()
        
        logger.info("move_file succeeded: %s", updated)
        return updated
    except Exception:
        logger.exception("move_file failed")
        raise


if __name__ == "__main__":
    try:
        logger.info("google-drive MCP server started successfully")
        mcp.run()
    except KeyboardInterrupt:
        logger.info("google-drive MCP server interrupted by user")
        raise
    except Exception:
        logger.exception("Fatal server error")
        raise
