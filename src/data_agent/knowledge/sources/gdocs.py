"""Google Docs knowledge source.

Unlike Notion and Slack, this one does not drop to raw HTTP: reaching the Drive
API means a signed service-account assertion, and reimplementing JWT signing to
avoid a dependency would be a bad trade. It uses `google-api-python-client`,
installed by the optional `gdocs` extra and imported lazily, so the core stays
installable without it.

**Not verified against the live Google API.** The call shapes follow the
documented Drive v3 API and the tests drive a stand-in service object, but this
has not read a real Drive. The service account needs `drive.readonly`, and — the
step people usually miss — the folder must be **shared with the service
account's email**, or it will authenticate happily and find nothing.

    pip install "hf-data-agent[gdocs]"
    export DA_GDOCS_CREDENTIALS=/path/to/service-account.json
    export DA_GDOCS_FOLDER_ID=1AbC...
    python scripts/ingest.py data/seed --gdocs
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from data_agent.knowledge.sources.base import Document

logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)
DOC_MIME = "application/vnd.google-apps.document"
EXPORT_MIME = "text/plain"
PAGE_SIZE = 100


class GoogleDocsSource:
    """Yields one Document per Google Doc in a Drive folder."""

    name = "gdocs"

    def __init__(
        self,
        credentials_path: str,
        folder_id: str,
        *,
        service: Any | None = None,
        recursive: bool = False,
    ) -> None:
        if not folder_id:
            raise ValueError("GoogleDocsSource requires a folder id")
        if service is None and not credentials_path:
            raise ValueError("GoogleDocsSource requires a service account credentials path")
        self.credentials_path = credentials_path
        self.folder_id = folder_id
        self.recursive = recursive
        self._service = service

    # ------------------------------------------------------------------ api --
    def fetch(self) -> Iterator[Document]:
        service = self._ensure_service()
        for folder in self._folders(service):
            for meta in self._documents_in(service, folder):
                document = self._document(service, meta)
                if document is not None:
                    yield document

    # -------------------------------------------------------------- helpers --
    def _ensure_service(self) -> Any:
        """Build the Drive client, importing the SDK only when actually used."""
        if self._service is not None:
            return self._service

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=list(SCOPES)
        )
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def _folders(self, service: Any) -> Iterator[str]:
        """The target folder, plus its subfolders when recursive."""
        yield self.folder_id
        if not self.recursive:
            return
        pending = [self.folder_id]
        seen = {self.folder_id}
        while pending:
            parent = pending.pop()
            query = (
                f"'{parent}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and trashed=false"
            )
            for child in self._list(service, query):
                child_id = child.get("id")
                if child_id and child_id not in seen:
                    seen.add(child_id)
                    pending.append(child_id)
                    yield child_id

    def _documents_in(self, service: Any, folder_id: str) -> Iterator[dict[str, Any]]:
        query = f"'{folder_id}' in parents and mimeType='{DOC_MIME}' and trashed=false"
        yield from self._list(service, query)

    def _list(self, service: Any, query: str) -> Iterator[dict[str, Any]]:
        """Drive files.list, followed to the last page."""
        token: str | None = None
        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    pageSize=PAGE_SIZE,
                    pageToken=token,
                    fields="nextPageToken, files(id, name, modifiedTime, webViewLink)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            yield from response.get("files", [])
            token = response.get("nextPageToken")
            if not token:
                return

    def _document(self, service: Any, meta: dict[str, Any]) -> Document | None:
        file_id = meta.get("id")
        if not file_id:
            return None

        exported = service.files().export(fileId=file_id, mimeType=EXPORT_MIME).execute()
        # The SDK returns bytes for an export; be tolerant of a str stand-in.
        if isinstance(exported, bytes):
            text = exported.decode("utf-8", errors="replace")
        else:
            text = str(exported)
        if not text.strip():
            logger.debug("skipping empty google doc", extra={"file_id": file_id})
            return None

        name = meta.get("name") or file_id
        return Document(
            id=file_id,
            text=text.strip(),
            source=f"{self.name}:{name}",
            metadata={
                "file_id": file_id,
                "name": name,
                "modified_time": meta.get("modifiedTime", ""),
                "url": meta.get("webViewLink", ""),
            },
        )
