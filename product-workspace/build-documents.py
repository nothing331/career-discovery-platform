"""Embed readable repository documents and research into the offline workspace.

Build: pip install -r product-workspace/requirements-documents.txt
       python product-workspace/build-documents.py
No dependency or web server is needed to open or export the generated HTML.
"""
from pathlib import Path
import json
import html as html_escape
import re
import sys

try:
    import markdown
except ImportError:
    sys.exit("Install build dependency: pip install -r product-workspace/requirements-documents.txt")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def excluded_source(path):
    parts = path.relative_to(ROOT).parts
    # Runtime snapshots, diagnostics and log summaries are local operational data,
    # not documents to include in a shareable or hosted workspace.
    local_data = parts[0] == "data" or parts[:2] == ("data-engine", "data")
    return local_data or any(part.startswith(".") or part in {"node_modules", "venv"} for part in parts)


def build():
    documents = {}
    for path in sorted(ROOT.rglob("*.md")):
        if excluded_source(path):
            continue
        key = path.relative_to(ROOT).as_posix()
        text = path.read_text()
        renderer = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"], tab_length=2)
        rendered = renderer.convert(text)
        title = re.search(r"^#\s+(.+)$", text, re.M)
        # The workspace supplies the title once, above the document body.
        rendered = re.sub(r"^<h1\b[^>]*>.*?</h1>\s*", "", rendered, count=1, flags=re.S)
        # The source H1 is displayed by the reader, so keep its contents link valid.
        toc = renderer.toc
        if renderer.toc_tokens and renderer.toc_tokens[0]["level"] == 1:
            toc = toc.replace('href="#' + renderer.toc_tokens[0]["id"] + '"', 'href="#reader-title"', 1)
        documents[key] = {"title": title[1] if title else path.stem, "html": rendered, "toc": toc}
    # Structured source records should remain available in the single-file export.
    for path in sorted(ROOT.rglob("*.json")):
        if excluded_source(path):
            continue
        key = path.relative_to(ROOT).as_posix()
        record = json.loads(path.read_text())
        title = record.get("title", path.stem.replace("-", " ").capitalize()) if isinstance(record, dict) else path.stem
        formatted = html_escape.escape(json.dumps(record, ensure_ascii=False, indent=2))
        documents[key] = {"title": title, "html": '<p>Structured project source record.</p><pre><code>' + formatted + '</code></pre>', "toc": ""}
    reports = {}
    for path in sorted((HERE / "research-findings").glob("*.json")):
        report = json.loads(path.read_text())
        reports[report["id"]] = report
    payload = json.dumps({"documents": documents, "reports": reports}, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    # The editable workspace is embedded in the unified index at build time.
    index = HERE / "src" / "workspace.html"
    if not index.exists():
        index = HERE / "index.html"
    html = index.read_text()
    block = '<script id="document-data" type="application/json">' + payload + '</script>'
    if 'id="document-data"' in html:
        html = re.sub(r'<script id="document-data" type="application/json">.*?</script>', lambda _: block, html, count=1, flags=re.S)
    else:
        html = html.replace('<script id="workspace-data"', block + '\n<script id="workspace-data"', 1)
    index.write_text(html)
    print(f"Embedded {len(documents)} formatted documents and {len(reports)} current research reports into {index.name}")


if __name__ == "__main__":
    build()
