"""Connector stubs for the SaaS knowledge sources in the diagram.

Each implements the KnowledgeSource protocol. They raise until wired with real
credentials/SDKs so the contract is explicit and the diagram stays honest.
Implement `fetch()` against the respective API and you're done — ingestion,
chunking, embedding, retrieval are all source-agnostic.
"""

from __future__ import annotations

from collections.abc import Iterator

from data_agent.knowledge.sources.base import Document


class NotionSource:
    name = "notion"

    def __init__(self, token: str, database_ids: list[str]) -> None:
        self.token = token
        self.database_ids = database_ids

    def fetch(self) -> Iterator[Document]:
        # TODO: use notion-client to page over databases/blocks -> Document.
        raise NotImplementedError("Wire up notion-client and yield Documents.")


class GoogleDocsSource:
    name = "gdocs"

    def __init__(self, credentials_path: str, folder_id: str) -> None:
        self.credentials_path = credentials_path
        self.folder_id = folder_id

    def fetch(self) -> Iterator[Document]:
        # TODO: Google Drive/Docs API -> export docs as text -> Document.
        raise NotImplementedError("Wire up Google Docs API and yield Documents.")


class SlackSource:
    name = "slack"

    def __init__(self, bot_token: str, channel_ids: list[str]) -> None:
        self.bot_token = bot_token
        self.channel_ids = channel_ids

    def fetch(self) -> Iterator[Document]:
        # TODO: slack_sdk conversations.history per channel -> Document per thread.
        raise NotImplementedError("Wire up slack_sdk and yield Documents.")
