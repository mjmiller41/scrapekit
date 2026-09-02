import pytest

from scrapekit.schema import apply_schema, fill_rates, parse_fields_spec, validate_schema, weakest_field

BOOKS = {
    "name": "books",
    "baseSelector": "li.product",
    "fields": [
        {"name": "title", "selector": "h3 a", "type": "attribute", "attribute": "title"},
        {"name": "price", "selector": ".price_color", "type": "text"},
        {"name": "url", "selector": "h3 a", "type": "attribute", "attribute": "href"},
        {"name": "stock", "selector": ".instock", "type": "text"},
        {"name": "amount", "selector": ".price_color", "type": "regex", "pattern": r"\d+\.\d{2}"},
        {"name": "missing", "selector": ".nope", "type": "text", "default": "n/a"},
    ],
}


def test_apply_schema_extracts_rows_and_resolves_urls(fixture_html):
    rows = apply_schema(fixture_html("static.html"), BOOKS, base_url="https://books.toscrape.com/")
    assert len(rows) == 4
    assert rows[0]["title"] == "A Light in the Attic"
    assert rows[0]["price"] == "£51.77"
    assert rows[0]["amount"] == "51.77"
    assert rows[0]["url"] == "https://books.toscrape.com/catalogue/a-light-in-the-attic"
    assert rows[0]["missing"] == "n/a"


def test_fill_rates_flag_weak_field(fixture_html):
    rows = apply_schema(fixture_html("static.html"), BOOKS)
    rates = fill_rates(rows, BOOKS)
    assert rates["title"] == 1.0
    assert rates["stock"] == 0.75
    name, rate = weakest_field({k: v for k, v in rates.items() if k != "missing"})
    assert name == "stock" and rate == 0.75


def test_fill_rates_empty():
    assert fill_rates([], BOOKS)["title"] == 0.0


def test_parse_fields_spec_handles_attrs_and_commas_in_selectors():
    s = parse_fields_spec("title=h3 a@title,price=.price_color, url=a@href, tag=h1, h2", base_selector="li.product")
    names = [f["name"] for f in s["fields"]]
    assert names == ["title", "price", "url", "tag"]
    assert s["fields"][0] == {"name": "title", "selector": "h3 a", "type": "attribute", "attribute": "title"}
    assert s["fields"][3]["selector"] == "h1, h2"
    assert s["baseSelector"] == "li.product"
    validate_schema(s)


def test_parse_fields_spec_bare_names_for_llm_tiers():
    assert parse_fields_spec("text, author")["fields"] == [{"name": "text", "type": "text"}, {"name": "author", "type": "text"}]
    s = parse_fields_spec("title=,price=, url=a@href")
    assert s["fields"] == [{"name": "title", "type": "text"}, {"name": "price", "type": "text"},
                           {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}]


def test_parse_fields_spec_rejects_garbage():
    with pytest.raises(ValueError):
        parse_fields_spec("bad name=h1")


def test_validate_schema_requires_attribute():
    with pytest.raises(ValueError):
        validate_schema({"fields": [{"name": "x", "selector": "a", "type": "attribute"}]})
