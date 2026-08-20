"""The SaaS knowledge connectors.

None of these has touched its live API, so the tests carry more weight than
usual: they drive the real request/response handling through httpx mock
transports (Notion, Slack) and a stand-in service object (Google Docs). What
they can prove is that parsing, pagination, deduplication and rate-limit
handling behave. What they cannot prove is that the real APIs answer in the
shapes assumed here.

Pagination gets deliberate attention. A connector that reads only the first page
fails silently: ingestion reports a plausible document count and the knowledge
base is quietly missing most of the corpus.
"""

from __future__ import annotations

import httpx
import pytest

from data_agent.knowledge.sources._http import (
    ConnectorError,
    request_json,
    retry_after_seconds,
)
from data_agent.knowledge.sources.gdocs import GoogleDocsSource
from data_agent.knowledge.sources.notion import NotionSource
from data_agent.knowledge.sources.slack import SlackSource


def client_for(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.example.com", transport=httpx.MockTransport(handler))


def rich(text: str) -> list[dict]:
    return [{"plain_text": text}]


def paragraph(text: str, **extra) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": rich(text)}, **extra}


def notion_page(page_id: str, title: str) -> dict:
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "last_edited_time": "2026-08-01T00:00:00.000Z",
        "properties": {"Name": {"type": "title", "title": rich(title)}},
    }


# ----------------------------------------------------------------- plumbing --
class TestRequestJson:
    def test_a_successful_response_is_returned(self):
        client = client_for(lambda r: httpx.Response(200, json={"ok": True}))
        assert request_json(client, "GET", "/x") == {"ok": True}

    def test_an_error_status_raises(self):
        client = client_for(lambda r: httpx.Response(403, text="nope"))
        with pytest.raises(ConnectorError, match="403"):
            request_json(client, "GET", "/x")

    def test_rate_limiting_is_retried_then_succeeds(self):
        calls = {"n": 0}
        slept: list[float] = []

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return httpx.Response(200, json={"done": True})

        result = request_json(client_for(handler), "GET", "/x", sleep=slept.append)
        assert result == {"done": True}
        assert slept == [2.0]

    def test_persistent_rate_limiting_gives_up(self):
        client = client_for(lambda r: httpx.Response(429))
        with pytest.raises(ConnectorError, match="still rate limited"):
            request_json(client, "GET", "/x", sleep=lambda _: None)

    @pytest.mark.parametrize(
        ("header", "expected"),
        [({}, 1.0), ({"Retry-After": "5"}, 5.0), ({"Retry-After": "junk"}, 1.0)],
    )
    def test_retry_after_parsing(self, header, expected):
        response = httpx.Response(429, headers=header)
        assert retry_after_seconds(response) == expected

    def test_an_absurd_retry_after_is_capped(self):
        """A bad header must not stall an ingest for hours."""
        response = httpx.Response(429, headers={"Retry-After": "99999"})
        assert retry_after_seconds(response) == 60.0


# -------------------------------------------------------------------- notion --
class TestNotion:
    def source(self, handler) -> NotionSource:
        return NotionSource("tok", ["db1"], client=client_for(handler))

    def test_a_page_becomes_a_document(self):
        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [notion_page("p1", "Runbook")]})
            return httpx.Response(200, json={"results": [paragraph("Runs at 02:00 UTC.")]})

        docs = list(self.source(handler).fetch())
        assert len(docs) == 1
        assert docs[0].id == "p1"
        assert docs[0].source == "notion:Runbook"
        assert "Runbook" in docs[0].text
        assert "Runs at 02:00 UTC." in docs[0].text

    def test_metadata_records_the_origin(self):
        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [notion_page("p1", "T")]})
            return httpx.Response(200, json={"results": [paragraph("body")]})

        meta = next(iter(self.source(handler).fetch())).metadata
        assert meta["page_id"] == "p1"
        assert meta["database_id"] == "db1"
        assert meta["url"].endswith("p1")

    def test_database_pagination_is_followed(self):
        """The regression that matters: stopping after page one silently drops
        most of the corpus."""
        seen = {"queries": 0}

        def handler(request):
            if request.url.path.endswith("/query"):
                seen["queries"] += 1
                if seen["queries"] == 1:
                    return httpx.Response(
                        200,
                        json={
                            "results": [notion_page("p1", "One")],
                            "has_more": True,
                            "next_cursor": "cur",
                        },
                    )
                return httpx.Response(200, json={"results": [notion_page("p2", "Two")]})
            return httpx.Response(200, json={"results": [paragraph("body")]})

        docs = list(self.source(handler).fetch())
        assert [d.id for d in docs] == ["p1", "p2"]
        assert seen["queries"] == 2

    def test_block_pagination_is_followed(self):
        seen = {"blocks": 0}

        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [notion_page("p1", "T")]})
            seen["blocks"] += 1
            if seen["blocks"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "results": [paragraph("first")],
                        "has_more": True,
                        "next_cursor": "c",
                    },
                )
            return httpx.Response(200, json={"results": [paragraph("second")]})

        text = next(iter(self.source(handler).fetch())).text
        assert "first" in text
        assert "second" in text

    def test_nested_blocks_are_flattened(self):
        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [notion_page("p1", "T")]})
            if "/blocks/p1/" in request.url.path:
                return httpx.Response(
                    200,
                    json={"results": [paragraph("outer", id="b1", has_children=True)]},
                )
            return httpx.Response(200, json={"results": [paragraph("inner")]})

        text = next(iter(self.source(handler).fetch())).text
        assert "outer" in text
        assert "inner" in text

    def test_non_text_blocks_are_skipped(self):
        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [notion_page("p1", "T")]})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"type": "image", "image": {}},
                        {"type": "divider", "divider": {}},
                        paragraph("kept"),
                    ]
                },
            )

        assert "kept" in next(iter(self.source(handler).fetch())).text

    def test_a_page_with_no_text_is_dropped(self):
        def handler(request):
            if request.url.path.endswith("/query"):
                return httpx.Response(200, json={"results": [{"id": "p1", "properties": {}}]})
            return httpx.Response(200, json={"results": []})

        assert list(self.source(handler).fetch()) == []

    def test_a_missing_token_is_refused(self):
        with pytest.raises(ValueError, match="integration token"):
            NotionSource("", ["db"])

    def test_the_default_client_sends_auth_and_version(self):
        source = NotionSource("secret-token", ["db"])
        try:
            assert source._client.headers["authorization"] == "Bearer secret-token"
            assert source._client.headers["notion-version"]
        finally:
            source.close()


# --------------------------------------------------------------------- slack --
class TestSlack:
    def source(self, handler) -> SlackSource:
        return SlackSource("xoxb", ["C1"], client=client_for(handler))

    def test_a_standalone_message_becomes_a_document(self):
        def handler(request):
            return httpx.Response(
                200, json={"ok": True, "messages": [{"ts": "1.0", "text": "deploy is done"}]}
            )

        docs = list(self.source(handler).fetch())
        assert len(docs) == 1
        assert docs[0].text == "deploy is done"
        assert docs[0].id == "C1:1.0"

    def test_a_thread_becomes_one_document(self):
        """Indexing replies separately would cut the answer away from its
        question, and retrieval would surface half a conversation."""

        def handler(request):
            if "replies" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "messages": [
                            {"ts": "1.0", "text": "why did revenue drop?"},
                            {"ts": "1.1", "text": "currency filter dropped rows"},
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "messages": [
                        {"ts": "1.0", "thread_ts": "1.0", "text": "why did revenue drop?"}
                    ],
                },
            )

        docs = list(self.source(handler).fetch())
        assert len(docs) == 1
        assert "why did revenue drop?" in docs[0].text
        assert "currency filter dropped rows" in docs[0].text
        assert docs[0].metadata["messages"] == 2

    def test_a_reply_at_top_level_is_not_indexed_twice(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "messages": [
                        {"ts": "2.0", "thread_ts": "1.0", "text": "a reply"},
                        {"ts": "3.0", "text": "standalone"},
                    ],
                },
            )

        docs = list(self.source(handler).fetch())
        assert [d.text for d in docs] == ["standalone"]

    def test_join_noise_is_skipped(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "messages": [
                        {"ts": "1.0", "subtype": "channel_join", "text": "x joined"},
                        {"ts": "2.0", "text": "real content"},
                    ],
                },
            )

        assert [d.text for d in self.source(handler).fetch()] == ["real content"]

    def test_history_pagination_is_followed(self):
        seen = {"n": 0}

        def handler(request):
            seen["n"] += 1
            if seen["n"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "messages": [{"ts": "1.0", "text": "first"}],
                        "response_metadata": {"next_cursor": "c2"},
                    },
                )
            second = {"ts": "2.0", "text": "second"}
            return httpx.Response(200, json={"ok": True, "messages": [second]})

        assert [d.text for d in self.source(handler).fetch()] == ["first", "second"]

    def test_an_api_level_failure_raises(self):
        """Slack answers 200 with ok:false, so status codes alone would miss it."""

        def handler(request):
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

        with pytest.raises(ConnectorError, match="invalid_auth"):
            list(self.source(handler).fetch())

    def test_an_empty_message_is_dropped(self):
        blank = {"ts": "1.0", "text": "  "}

        def handler(request):
            return httpx.Response(200, json={"ok": True, "messages": [blank]})

        assert list(self.source(handler).fetch()) == []

    def test_a_missing_token_is_refused(self):
        with pytest.raises(ValueError, match="bot token"):
            SlackSource("", ["C1"])


# --------------------------------------------------------------------- gdocs --
class FakeDrive:
    """Stands in for the Drive service object the SDK builds."""

    def __init__(self, pages: list[dict], exports: dict[str, bytes]):
        self.pages = pages
        self.exports = exports
        self.queries: list[str] = []

    def files(self):
        return self

    def list(self, *, q, pageToken=None, **kwargs):  # noqa: N803 - Google's spelling
        self.queries.append(q)
        index = 0 if pageToken is None else int(pageToken)
        page = self.pages[index] if index < len(self.pages) else {"files": []}
        return _Executable(page)

    def export(self, *, fileId, mimeType):  # noqa: N803 - Google's spelling
        return _Executable(self.exports.get(fileId, b""))


class _Executable:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class TestGoogleDocs:
    def test_a_doc_becomes_a_document(self):
        drive = FakeDrive(
            [{"files": [{"id": "d1", "name": "Policy", "webViewLink": "https://doc"}]}],
            {"d1": b"Access is read-only."},
        )
        docs = list(GoogleDocsSource("", "folder", service=drive).fetch())
        assert len(docs) == 1
        assert docs[0].text == "Access is read-only."
        assert docs[0].source == "gdocs:Policy"
        assert docs[0].metadata["url"] == "https://doc"

    def test_listing_pagination_is_followed(self):
        drive = FakeDrive(
            [
                {"files": [{"id": "d1", "name": "One"}], "nextPageToken": "1"},
                {"files": [{"id": "d2", "name": "Two"}]},
            ],
            {"d1": b"first", "d2": b"second"},
        )
        assert [d.id for d in GoogleDocsSource("", "f", service=drive).fetch()] == ["d1", "d2"]

    def test_only_documents_in_the_folder_are_requested(self):
        drive = FakeDrive([{"files": []}], {})
        list(GoogleDocsSource("", "folder-x", service=drive).fetch())
        assert "'folder-x' in parents" in drive.queries[0]
        assert "trashed=false" in drive.queries[0]

    def test_an_empty_document_is_dropped(self):
        drive = FakeDrive([{"files": [{"id": "d1", "name": "Blank"}]}], {"d1": b"   "})
        assert list(GoogleDocsSource("", "f", service=drive).fetch()) == []

    def test_a_string_export_is_tolerated(self):
        drive = FakeDrive([{"files": [{"id": "d1", "name": "N"}]}], {})
        drive.exports["d1"] = "plain string"
        assert next(iter(GoogleDocsSource("", "f", service=drive).fetch())).text == "plain string"

    def test_a_missing_folder_is_refused(self):
        with pytest.raises(ValueError, match="folder id"):
            GoogleDocsSource("creds.json", "")

    def test_credentials_are_required_without_an_injected_service(self):
        with pytest.raises(ValueError, match="credentials path"):
            GoogleDocsSource("", "folder")


# ----------------------------------------------------------- ingest wiring --
class TestIngestCli:
    """Selecting a source without its credentials must fail, not no-op.

    A connector that quietly contributes nothing is the worst outcome: the run
    reports success and the knowledge base is missing an entire source.
    """

    def build(self, argv, **settings_kwargs):
        from scripts.ingest import build_sources, parse_args

        from data_agent.config import Settings

        return build_sources(parse_args(argv), Settings(**settings_kwargs))

    def test_the_filesystem_source_is_the_default(self, tmp_path):
        sources = self.build([str(tmp_path)])
        assert [s.name for s in sources] == ["filesystem"]

    def test_the_filesystem_source_can_be_skipped(self, tmp_path):
        assert self.build([str(tmp_path), "--no-filesystem"]) == []

    def test_notion_without_database_ids_is_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="DA_NOTION_DATABASE_IDS"):
            self.build([str(tmp_path), "--notion"])

    def test_notion_without_a_token_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="integration token"):
            self.build([str(tmp_path), "--notion"], notion_database_ids="db1")

    def test_slack_without_channels_is_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="DA_SLACK_INGEST_CHANNELS"):
            self.build([str(tmp_path), "--slack"])

    def test_gdocs_without_a_folder_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="folder id"):
            self.build([str(tmp_path), "--gdocs"])

    def test_configured_connectors_are_added(self, tmp_path):
        sources = self.build(
            [str(tmp_path), "--notion", "--slack"],
            notion_token="t",
            notion_database_ids="db1",
            slack_ingest_token="xoxb",
            slack_ingest_channels="C1",
        )
        assert [s.name for s in sources] == ["filesystem", "notion", "slack"]
        for source in sources[1:]:
            source.close()
