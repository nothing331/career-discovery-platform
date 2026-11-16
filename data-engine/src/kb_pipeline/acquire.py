import copy
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
import pdfplumber
from .contracts import PipelineError
from .db import uid, now, snapshots

# v5: key facts outside p/li/tr are kept - <dl> term/value rows, heading + value fact
# boxes, label + value boxes, and loose text in <div>/<td>/<dd>.
PARSER_VERSION = "blocks-v5"
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
# Inline elements never form a block of their own; their text joins the enclosing one.
INLINE = {
    "a", "abbr", "b", "bdi", "bdo", "br", "button", "cite", "code", "data", "dfn", "em",
    "font", "i", "img", "kbd", "label", "mark", "q", "s", "samp", "small", "span",
    "strong", "sub", "sup", "time", "u", "var", "wbr",
}
LABELS = ("label", "strong", "b", "th", "dt")
# location.source of blocks added in v5. They get ids like "b0017.1" (after core block
# b0017) so every blocks-v4 block keeps its id, text and heading.
EXTRA_SOURCES = ("dl", "fact", "text")


def core_blocks(blocks):
    """The blocks a blocks-v4 parse produced: same ids, text and headings."""
    return [b for b in blocks if b.get("location", {}).get("source") not in EXTRA_SOURCES]
MAX_BYTES = 10_000_000
# Interstitials served instead of content (proof-of-work / browser checks). They are
# the site's refusal of automated access, not page text.
BOT_CHALLENGE_RE = re.compile(
    r"making sure you['’]re not a bot|checking your browser before accessing"
    r"|enable javascript and cookies to continue|attention required!? \| cloudflare"
    r"|verify you are human|just a moment\.\.\.",
    re.I,
)


def _article_header(tag):
    """A <header> that belongs to the article/main content, not the site banner."""
    return tag.find_parent(["article", "main"]) is not None


def check_url(url, hosts):
    p = urlsplit(str(url))
    if (
        p.scheme != "https"
        or p.hostname not in hosts
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise PipelineError(
            "SOURCE_NOT_ALLOWED", "Only registered HTTPS source hosts are allowed"
        )
    return str(url)


class Fetcher:
    def __init__(self, settings, store, client=None, sleep=time.sleep):
        self.settings, self.store = settings, store
        self.client = client or httpx.Client(
            timeout=30,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=False,
        )
        self.owns_client = client is None
        self.sleep = sleep
        self.last = {}
        self.robots = {}

    def get(self, url, hosts):
        for _ in range(6):
            check_url(url, hosts)
            host = urlsplit(url).hostname
            if host in self.robots and not self.robots[host][0].can_fetch(
                self.settings.user_agent, url
            ):
                raise PipelineError(
                    "ROBOTS_DISALLOWED", "Redirect destination disallows this crawler"
                )
            delay = max(self.settings.delay, self.robots.get(host, (None, 0))[1])
            elapsed = time.monotonic() - self.last.get(host, 0)
            if elapsed < delay:
                self.sleep(delay - elapsed)
            self.last[host] = time.monotonic()
            try:
                with self.client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise PipelineError(
                                "BAD_REDIRECT", "Redirect without Location"
                            )
                        new_url = urljoin(url, location)
                        if urlsplit(new_url).hostname != host:
                            raise PipelineError(
                                "REDIRECT_SOURCE_REVIEW",
                                "Cross-host redirect needs a reviewed source registration",
                            )
                        url = new_url
                        continue
                    if response.status_code >= 400:
                        code = f"HTTP_{response.status_code}"
                        error = PipelineError(
                            code,
                            code + " for registered source",
                            retryable=response.status_code == 429
                            or response.status_code >= 500,
                        )
                        try:
                            raw_delay = response.headers.get("retry-after", "0")
                            try:
                                delay_seconds = float(raw_delay)
                            except ValueError:
                                delay_seconds = (
                                    parsedate_to_datetime(raw_delay)
                                    - datetime.now(timezone.utc)
                                ).total_seconds()
                            error.retry_after = max(0, delay_seconds)
                            if error.retry_after > 300:
                                error.retryable = False
                                error.code = "RETRY_AFTER_REVIEW"
                        except ValueError:
                            error.retry_after = 0
                        raise error
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise PipelineError(
                                "DOCUMENT_TOO_LARGE", "Document exceeds 10 MB"
                            )
                    return str(response.url), bytes(content), dict(response.headers)
            except httpx.TransportError as e:
                raise PipelineError(
                    "FETCH_TRANSPORT", type(e).__name__, retryable=True
                ) from e
        raise PipelineError("REDIRECT_LIMIT", "Too many source redirects")

    def fetch(self, target):
        url = check_url(target.url, target.allowed_hosts)
        host = urlsplit(url).hostname
        if host not in self.robots:
            robots_url = "https://" + host + "/robots.txt"
            try:
                _, body, _ = self.get(robots_url, target.allowed_hosts)
                rp = RobotFileParser()
                rp.parse(body.decode("utf-8", errors="replace").splitlines())
            except PipelineError as e:
                if e.code != "HTTP_404":
                    raise PipelineError(
                        "ROBOTS_UNAVAILABLE",
                        "Cannot establish source crawl policy",
                        retryable=e.retryable,
                    ) from e
                rp = RobotFileParser()
                rp.parse([])
            self.robots[host] = (
                rp,
                rp.crawl_delay(self.settings.user_agent) or rp.crawl_delay("*") or 0,
            )
        if not self.robots[host][0].can_fetch(self.settings.user_agent, url):
            raise PipelineError(
                "ROBOTS_DISALLOWED", "Registered source disallows this crawler"
            )
        final, body, headers = self.get(url, target.allowed_hosts)
        if not self.robots[host][0].can_fetch(self.settings.user_agent, final):
            raise PipelineError(
                "ROBOTS_DISALLOWED", "Redirect destination disallows this crawler"
            )
        digest = hashlib.sha256(body).hexdigest()
        sid = uid()
        kind = headers.get("content-type", "").split(";")[0]
        if body.startswith(b"%PDF"):
            kind = "application/pdf"
        if kind not in ("text/html", "application/xhtml+xml", "application/pdf"):
            raise PipelineError("UNSUPPORTED_DOCUMENT", "Expected HTML or PDF")
        suffix = "pdf" if kind == "application/pdf" else "html"
        path = (
            self.store.directory
            / "raw"
            / target.country
            / target.id
            / (digest + "." + suffix)
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
        self.store.insert(
            snapshots,
            id=sid,
            url=final,
            hash=digest,
            path=str(path.relative_to(self.store.directory)),
            content_type=kind,
            observed_at=now(),
            headers=json.dumps(
                {
                    k: headers[k]
                    for k in ("etag", "last-modified", "content-type")
                    if k in headers
                }
            ),
        )
        return self.store.one(snapshots, id=sid)

    def close(self):
        if self.owns_client:
            self.client.close()


def normal(text):
    return re.sub(r"\s+", " ", text).strip()


def parse(body, kind, url):
    blocks = []
    links = []
    core = [0]  # blocks-v4 blocks keep their ids; extra blocks are numbered after them

    def add(text, location, heading=""):
        text = normal(text)
        if not text:
            return
        if location.get("source") in EXTRA_SOURCES:
            base = f"b{core[0] - 1:04d}" if core[0] else "b"
            after = sum(1 for b in blocks if b["id"].startswith(base + "."))
            block_id = f"{base}.{after + 1}"
        else:
            block_id = f"b{core[0]:04d}"
            core[0] += 1
        blocks.append(
            {"id": block_id, "text": text, "location": location, "heading": heading}
        )

    if kind == "application/pdf":
        try:
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                if len(pdf.pages) > 100:
                    raise PipelineError("PDF_PAGE_LIMIT", "PDF exceeds 100-page limit")
                for n, page in enumerate(pdf.pages, 1):
                    for text in (page.extract_text() or "").split("\n\n"):
                        add(text, {"page": n})
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(
                "PDF_PARSE_FAILED", "PDF parser could not read document"
            ) from e
    else:
        soup = BeautifulSoup(body, "html.parser")
        links = [
            {"url": urljoin(url, a["href"]), "text": normal(a.get_text(" "))[:200]}
            for a in soup.select("a[href]")
            if not a["href"].startswith(("mailto:", "javascript:", "#"))
        ]
        main = (
            soup.select_one("#content-core")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("#content")
            or soup.body
            or soup
        )
        lead_h1 = None
        if main is not soup.body and main is not soup and not main.find("h1"):
            # The narrowed content container can omit the page title, which lives in an
            # enclosing container. Keep the nearest enclosing h1 outside site chrome.
            for ancestor in main.parents:
                lead_h1 = next(
                    (
                        h
                        for h in ancestor.find_all("h1")
                        if h.find_parent(["nav", "footer"]) is None
                        and (
                            h.find_parent("header") is None
                            or _article_header(h.find_parent("header"))
                        )
                    ),
                    None,
                )
                if lead_h1 is not None:
                    break
        page_text = normal(soup.get_text(" "))
        if len(page_text) < 3000 and BOT_CHALLENGE_RE.search(page_text):
            raise PipelineError(
                "BOT_CHALLENGE",
                "Source served an anti-bot challenge instead of content; "
                "use another official source or ask the site for access",
            )
        # An article's own <header> often holds the page title; keep its h1 before
        # site-chrome headers are dropped.
        if not any(h.find_parent("header") is None for h in main.find_all("h1")):
            for hdr in main.find_all("header"):
                h1 = hdr.find("h1")
                if h1 is not None and hdr.find_parent("header") is None:
                    hdr.replace_with(h1.extract())
                    break
        for tag in main.select("script,style,nav,footer,header,form,noscript"):
            tag.decompose()
        if lead_h1 is not None:
            main.insert(0, copy.copy(lead_h1))
        if main.find("h1") is None and soup.title and normal(soup.title.get_text()):
            # No visible h1 anywhere: the document <title> is the page's own name.
            add(soup.title.get_text(" "), {"tag": "h1", "source": "title"})
        heading = ""

        def data_row(tag):
            return (
                tag.name == "tr"
                and not tag.find("tr")
                and len(normal(tag.get_text(" "))) <= 3000
                and len(tag.find_all(["td", "th"], recursive=False)) >= 2
            )

        def keeps(tag):
            if tag.find_parent(["p", "li"]) is not None:
                return False
            if tag.name == "tr" and not data_row(tag):
                return False
            parent_row = tag.find_parent("tr")
            return parent_row is None or not data_row(parent_row)

        order = {
            id(tag): i
            for i, tag in enumerate(
                main.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr"])
            )
        }
        emitted = {}  # id(tag) -> block index, for every element whose text is a block
        pending = []  # consecutive loose strings sharing one container

        def inside_emitted(node):
            return any(id(p) in emitted for p in node.parents)

        def flush():
            if not pending:
                return
            container = pending[0][0]
            text = normal(" ".join(s for _, s in pending))
            pending.clear()
            if not text:
                return
            index = len(blocks) and blocks[-1]["location"].get("index", 0)
            prev = container.find_previous_sibling()
            label = None
            term = container.find_previous_sibling("dt") if container.name == "dd" else None
            if (
                term is not None
                and blocks
                and blocks[-1]["location"] == {"tag": "dt", "index": index, "source": "text"}
                and blocks[-1]["text"] == normal(term.get_text(" "))
            ):
                # dt/dd outside a plain <dl> row (the list also holds links or lists).
                label = blocks.pop()["text"]
            elif (
                prev is not None
                and prev.name in HEADINGS
                and emitted.get(id(prev)) == len(blocks) - 1
                and len(normal(prev.get_text(" "))) <= 60
                and len(text) <= 150
                # the box holds just the heading and its value
                and container.parent is not main
                and len(container.parent.find_all(True, recursive=False)) == 2
            ):
                # A fact box: short heading + its value ("REGELSTUDIENZEIT" / "6 Semester").
                label = normal(prev.get_text(" "))
            elif len(text) <= 150:
                first = next(
                    (
                        t
                        for t in container.find_all(string=True)
                        if normal(t)
                    ),
                    None,
                )
                tag = first.find_parent(LABELS) if first is not None else None
                if tag is not None and container in tag.parents:
                    rest = normal(text[len(normal(tag.get_text(" "))):])
                    if rest:
                        # "Language of instruction" <label> + "English" in one key-fact box.
                        label = normal(tag.get_text(" "))
                        text = rest
            if label:
                add(
                    f"{label} {text}",
                    {"tag": "tr", "index": index, "source": "fact"},
                    heading,
                )
            else:
                add(text, {"tag": container.name, "index": index, "source": "text"}, heading)

        for node in main.descendants:
            if isinstance(node, Tag):
                if inside_emitted(node):
                    continue
                if (
                    node.name == "dl"
                    and node.find("dt") is not None
                    and not any(id(t) in order for t in node.find_all(True))
                ):
                    flush()
                    # Definition lists are key facts: one row per term with its values.
                    for dt in node.find_all("dt"):
                        if dt.find_parent("dl") is not node:
                            continue
                        values = []
                        for sib in dt.find_next_siblings():
                            if sib.name == "dt":
                                break
                            if sib.name == "dd":
                                values.append(sib.get_text(" "))
                        add(
                            " ".join([dt.get_text(" "), *values]),
                            {
                                "tag": "tr",
                                "index": len(blocks) and blocks[-1]["location"].get("index", 0),
                                "source": "dl",
                            },
                            heading,
                        )
                    emitted[id(node)] = len(blocks) - 1
                elif id(node) in order and keeps(node):
                    flush()
                    if node.name.startswith("h"):
                        heading = normal(node.get_text(" "))
                    before = len(blocks)
                    add(node.get_text(" "), {"tag": node.name, "index": order[id(node)]}, heading)
                    emitted[id(node)] = len(blocks) - 1 if len(blocks) > before else -1
            elif type(node) is NavigableString and normal(node):
                if inside_emitted(node):
                    continue
                container = next(p for p in node.parents if p.name not in INLINE or p is main)
                if pending and pending[0][0] is not container:
                    flush()
                pending.append((container, str(node)))
        flush()
    if len(" ".join(b["text"] for b in blocks)) < 80:
        raise PipelineError(
            "EMPTY_PARSED_TEXT", "No usable text; OCR or a source adapter may be needed"
        )
    return {"parser_version": PARSER_VERSION, "blocks": blocks, "links": links}
