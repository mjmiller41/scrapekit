from scrapekit.probe import Probe, analyse_html


def test_static_page_is_tier_1(fixture_html):
    p = analyse_html(Probe(url="x", status=200), fixture_html("static.html"))
    assert p.recommended_tier == 1
    assert not p.js_shell and not p.blocked


def test_js_shell_is_tier_2(fixture_html):
    p = analyse_html(Probe(url="x", status=200), fixture_html("js_shell.html"))
    assert p.recommended_tier == 2
    assert p.js_shell
    assert "empty app root" in p.reason


def test_cloudflare_challenge_is_blocked(fixture_html):
    p = analyse_html(Probe(url="x", status=403), fixture_html("cloudflare.html"))
    assert p.blocked
    assert p.recommended_tier == "blocked"
    assert "cf-chl" in p.markers
    assert "tier4" in p.reason.lower() or "Tier 4" in p.reason


def test_challenge_markers_with_200_and_real_content_are_not_blocked(fixture_html):
    html = fixture_html("static.html").replace("</footer>", " captcha </footer>")
    p = analyse_html(Probe(url="x", status=200), html)
    assert not p.blocked
    assert p.recommended_tier == 1
