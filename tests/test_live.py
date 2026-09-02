"""Hits real, scrape-friendly demo sites. Run with: uv run pytest -m live"""

import pytest

from scrapekit import api
from scrapekit.probe import probe

pytestmark = pytest.mark.live

BOOKS = {
    "baseSelector": "article.product_pod",
    "fields": [
        {"name": "title", "selector": "h3 a", "type": "attribute", "attribute": "title"},
        {"name": "price", "selector": ".price_color", "type": "text"},
        {"name": "url", "selector": "h3 a", "type": "attribute", "attribute": "href"},
    ],
}
QUOTES = {
    "baseSelector": "div.quote",
    "fields": [
        {"name": "text", "selector": ".text", "type": "text"},
        {"name": "author", "selector": ".author", "type": "text"},
    ],
}


def test_probe_static_site():
    assert probe("https://books.toscrape.com/").recommended_tier == 1


def test_probe_js_site():
    assert probe("https://quotes.toscrape.com/js/").recommended_tier == 2


def test_tier1_extract():
    page = api.extract("https://books.toscrape.com/", BOOKS, tier=1)
    assert page.ok and len(page.rows) == 20
    assert page.rows[0]["url"].startswith("https://books.toscrape.com/")


def test_tier1_finds_nothing_on_js_site_but_tier2_does():
    assert api.extract("https://quotes.toscrape.com/js/", QUOTES, tier=1).rows == []
    page = api.extract("https://quotes.toscrape.com/js/", QUOTES, tier=2)
    assert page.ok and len(page.rows) == 10 and page.rows[0]["author"]
