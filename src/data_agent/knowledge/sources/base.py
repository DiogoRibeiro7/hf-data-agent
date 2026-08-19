"""Knowledge sources feed the offline ingestion pipeline. Each yields Documents;
ingestion chunks + embeds them. Matches the diagram's 'Slack, Google Docs, Notion'.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Document:
    id: str
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeSource(Protocol):
    name: str

    def fetch(self) -> Iterator[Document]: ...
