import json
import logging
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import mirror


class FakeResponse:
    def __init__(
        self, data: List[Dict[str, Any]], headers: Optional[Dict[str, str]] = None
    ) -> None:
        self._data = data
        self.headers = headers or {}

    def read(self) -> bytes:
        return json.dumps(self._data).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _logger() -> logging.Logger:
    logger = logging.getLogger("test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


def test_fetch_github_repos_paginates() -> None:
    page1 = [
        {"name": "a", "owner": {"login": "me"}},
        {"name": "b", "owner": {"login": "me"}},
    ]
    page2: List[Dict[str, Any]] = []

    responses = [FakeResponse(page1), FakeResponse(page2)]

    with patch("mirror.urllib.request.urlopen", side_effect=responses):
        repos = mirror.fetch_github_repos("token", _logger())

    assert [r["name"] for r in repos] == ["a", "b"]


def test_fetch_gitea_repos_filters_owner() -> None:
    page1 = [
        {"name": "repo1", "owner": {"login": "alice"}, "mirror": True, "empty": False},
        {"name": "repo2", "owner": {"login": "bob"}, "mirror": False, "empty": True},
    ]
    page2: List[Dict[str, Any]] = []

    responses = [FakeResponse(page1), FakeResponse(page2)]

    with patch("mirror.urllib.request.urlopen", side_effect=responses):
        repos = mirror.fetch_gitea_repos("https://gitea", "t", "alice", _logger())

    assert "repo1" in repos
    assert repos["repo1"]["mirror"] is True
    assert repos["repo1"]["empty"] is False
    assert "repo2" not in repos


def test_detect_webhook_type() -> None:
    assert mirror._detect_webhook_type("https://hooks.slack.com/services/x", "") == "slack"
    assert (
        mirror._detect_webhook_type("https://api.telegram.org/bot123/sendMessage", "") == "telegram"
    )
    assert mirror._detect_webhook_type("https://example.com/hook", "generic") == "generic"


def test_build_summary_text_includes_failures() -> None:
    results = [
        {"name": "ok", "status": "success", "duration": 1, "error": ""},
        {"name": "bad", "status": "failed", "duration": 1, "error": "boom"},
    ]
    report_file = mirror.REPORTS_DIR / "report_test.md"
    text = mirror._build_summary_text(results, 3.0, 2, 600, "en", report_file)

    assert "Failed Repositories" in text
    assert "bad: boom" in text
