"""YouTube OAuth 2.0 (installed-app flow) (LLD §8.9, LLR-AUT-01..03)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edutube.errors import AuthExpiredError, ConfigError
from edutube.logging_setup import get_logger
from edutube.utils.fs import set_owner_only_permissions

log = get_logger("publish.youtube_auth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def run_auth_flow(client_secret_path: Path, token_path: Path) -> None:
    """LLR-AUT-01: installed-app OAuth flow; saves secrets/token.json."""
    if not client_secret_path.exists():
        raise ConfigError(
            f"OAuth client secret not found: {client_secret_path}",
            hint="Download it from Google Cloud Console and save it there (see docs/SRS.md A-02)",
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    set_owner_only_permissions(token_path)
    log.info("Saved OAuth token to %s", token_path)


def get_credentials(token_path: Path) -> Any:
    """Load token, refresh if expired (LLR-AUT-02)."""
    if not token_path.exists():
        raise AuthExpiredError(f"No token file at {token_path}", hint="Run `edutube auth`")

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise AuthExpiredError(f"Token refresh failed: {e}") from e
        token_path.write_text(creds.to_json(), encoding="utf-8")
        set_owner_only_permissions(token_path)
    if not creds or not creds.valid:
        raise AuthExpiredError("OAuth token is invalid")
    return creds


def youtube_client(creds: Any) -> Any:
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds, cache_discovery=False)
