"""Parser edge cases seen on real university pages (blocks-v4)."""

import pytest
from kb_pipeline.acquire import parse
from kb_pipeline.contracts import PipelineError

FILLER = "<p>" + "Admission requires a recognised bachelor's degree in computer science. " * 3 + "</p>"


def h1s(doc):
    return [b["text"] for b in doc["blocks"] if b["location"].get("tag") == "h1"]


def test_h1_inside_article_header_is_kept():
    # FAU / Tübingen / TU Darmstadt: the title lives in the article's own <header>.
    html = f"""<html><body><header><h1>Site banner</h1></header>
    <main><article><header><h1>Informatik (B.Sc.)</h1></header>{FILLER}</article></main>
    </body></html>"""
    doc = parse(html.encode(), "text/html", "https://x.test/")
    assert h1s(doc) == ["Informatik (B.Sc.)"]
    assert doc["blocks"][0]["text"] == "Informatik (B.Sc.)"


def test_h1_in_article_header_outside_narrowed_container():
    # Bonn: #content-core is chosen, the title is in article#content > header.
    html = f"""<html><body><main><article id="content"><header><h1>Computer Science</h1></header>
    <div id="content-core">{FILLER}</div></article></main></body></html>"""
    doc = parse(html.encode(), "text/html", "https://x.test/")
    assert h1s(doc) == ["Computer Science"]


def test_site_banner_h1_is_not_the_title():
    html = f"""<html><head><title>Informatics Bachelor of Science</title></head><body>
    <header><h1>University Portal</h1></header><main>{FILLER}</main></body></html>"""
    doc = parse(html.encode(), "text/html", "https://x.test/")
    # No content h1, so the document title is used instead of the site banner.
    assert h1s(doc) == ["Informatics Bachelor of Science"]
    assert doc["blocks"][0]["location"] == {"tag": "h1", "source": "title"}


def test_existing_content_h1_wins_over_document_title():
    html = f"""<html><head><title>Other</title></head><body><main>
    <h1>Computer Science M.Sc.</h1>{FILLER}</main></body></html>"""
    doc = parse(html.encode(), "text/html", "https://x.test/")
    assert h1s(doc) == ["Computer Science M.Sc."]


@pytest.mark.parametrize(
    "text",
    [
        "Making sure you're not a bot!",
        "Checking your browser before accessing example.org",
        "Enable JavaScript and cookies to continue",
    ],
)
def test_bot_challenge_page_is_rejected(text):
    html = f"<html><body><main><h1>{text}</h1><p>{'Please wait while we verify. ' * 5}</p></main></body></html>"
    with pytest.raises(PipelineError) as exc:
        parse(html.encode(), "text/html", "https://x.test/")
    assert exc.value.code == "BOT_CHALLENGE"


def test_long_page_mentioning_javascript_is_not_a_challenge():
    html = "<html><body><main><h1>Informatik</h1>" + FILLER * 30 + (
        "<p>Enable JavaScript and cookies to continue using the course portal.</p></main></body></html>"
    )
    doc = parse(html.encode(), "text/html", "https://x.test/")
    assert h1s(doc) == ["Informatik"]


def test_banner_header_inside_main_does_not_beat_content_h1():
    # FU Berlin: a site-name header sits inside the content container.
    html = f"""<html><body><main><header><h1>Freie Universität Berlin</h1></header>
    <div><h1>Informatik</h1>{FILLER}</div></main></body></html>"""
    doc = parse(html.encode(), "text/html", "https://x.test/")
    assert h1s(doc) == ["Informatik"]
