"""Working source: ingest local .md/.txt files. Use this for company wikis
exported to disk, runbooks, design docs, etc."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from data_agent.knowledge.sources.base import Document


class FilesystemSource:
    name = "filesystem"

    def __init__(self, root: str, patterns: tuple[str, ...] = ("*.md", "*.txt")) -> None:
        self.root = Path(root)
        self.patterns = patterns

    def fetch(self) -> Iterator[Document]:
        for pattern in self.patterns:
            for path in sorted(self.root.rglob(pattern)):
                yield Document(
                    id=str(path.relative_to(self.root)),
                    text=path.read_text(encoding="utf-8", errors="ignore"),
                    source=f"{self.name}:{path.name}",
                    metadata={"path": str(path)},
                )
