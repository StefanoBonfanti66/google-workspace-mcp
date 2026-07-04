#!/usr/bin/env python3
"""
Bootstrap a Google Gmail OAuth token outside of the MCP runtime.

Usage:
    python scripts/bootstrap_gmail_token.py --account info
    python scripts/bootstrap_gmail_token.py --account personal
    python scripts/bootstrap_gmail_token.py --account info --force

The script:
    - reads the same client_secrets.json as the MCP servers
    - starts a local server to catch the OAuth redirect
    - opens the browser for user consent (respects BROWSER env)
    - saves the token as token_{prefix}_{account}.pickle
    - skips if a valid token already exists (unless --force)
"""

import argparse
import os
import pickle
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_token_path(project_root: Path, prefix: str, account: str) -> Path:
    return project_root / f"token_{prefix}_{account}.pickle"


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap a Gmail OAuth token file outside the MCP runtime."
    )
    parser.add_argument(
        "--account",
        default="info",
        help="Account label (e.g. info, personal). Default: info",
    )
    parser.add_argument(
        "--prefix",
        default="gmail",
        help="Token prefix (e.g. gmail, contacts). Default: gmail",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-authentication even if a valid token exists",
    )
    args = parser.parse_args()

    project_root = resolve_project_root()
    secrets_path = project_root / "client_secrets.json"

    if not secrets_path.exists():
        print(f"[ERROR] client_secrets.json not found at: {secrets_path}")
        sys.exit(1)

    token_path = resolve_token_path(project_root, args.prefix, args.account)
    print(f"[INFO] Project root:  {project_root}")
    print(f"[INFO] Client secret: {secrets_path}")
    print(f"[INFO] Token target:   {token_path}")
    print(f"[INFO] Account:        {args.account}")
    print(f"[INFO] Scopes:         {SCOPES}")

    creds: Credentials | None = None

    if not args.force and token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        print(f"[INFO] Existing token loaded from {token_path}")

    if creds and creds.valid:
        print("[OK] Token is valid. Nothing to do.")
        print(f"     Path: {token_path}")
        sys.exit(0)

    if creds and creds.expired and creds.refresh_token:
        print("[INFO] Token expired, attempting refresh...")
        try:
            creds.refresh(Request())
            print("[OK] Token refreshed successfully.")
        except Exception as e:
            print(f"[WARN] Refresh failed ({e}). Will run full OAuth flow.")
            creds = None

    if not creds or not creds.valid:
        print("\n[INFO] Starting local OAuth server...")
        print("[INFO] The browser will open for authorization.")
        print("[INFO] On WSL, BROWSER=cmd.exe /C start opens the Windows browser.")
        print()

        flow = InstalledAppFlow.from_client_secrets_file(
            str(secrets_path),
            SCOPES,
        )

        creds = flow.run_local_server(
            port=0,
            authorization_prompt_message="",
            success_message="Autorizzazione completata! Puoi chiudere questa finestra e tornare al terminale.",
        )

    with open(token_path, "wb") as f:
        pickle.dump(creds, f)

    print(f"\n[SUCCESS] Token salvato in: {token_path}")
    print(f"[INFO]  Scopes: {creds.scopes}")
    print(f"[INFO]  Expiry: {creds.expiry}")
    print()
    print(f"Ora puoi usare /gmail-triage o qualunque MCP che usa questo account.")


if __name__ == "__main__":
    main()
