import sys
from unittest.mock import MagicMock, patch

import pytest

from house_watch.browser import BrowserFetchError, BrowserFetcher, BrowserResponse, BrowserUnavailable


def test_browser_response_attributes():
    resp = BrowserResponse(status_code=200, text="<html></html>", title="Test", url="https://example.com")
    assert resp.status_code == 200
    assert resp.text == "<html></html>"
    assert resp.title == "Test"
    assert resp.url == "https://example.com"


def test_browser_unavailable_sin_playwright():
    with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
        fetcher = BrowserFetcher()
        with pytest.raises(BrowserUnavailable, match="Playwright no esta instalado"):
            fetcher._ensure_browser()


def test_browser_determines_headless():
    fetcher_true = BrowserFetcher(headless=True)
    assert fetcher_true._determine_headless() is True

    fetcher_false = BrowserFetcher(headless=False)
    assert fetcher_false._determine_headless() is False


def test_browser_fetch_presupuesto_agotado():
    budget = MagicMock()
    budget.exhausted = True
    fetcher = BrowserFetcher(budget=budget)
    with pytest.raises(BrowserFetchError, match="Presupuesto"):
        fetcher.get("https://example.com")
