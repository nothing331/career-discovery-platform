import hashlib
import io
import json
from pathlib import Path
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
import pdfplumber
from .contracts import PipelineError
from .db import uid, now, snapshots

PARSER_VERSION = "blocks-v2"
MAX_BYTES = 10_000_000


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

    def add(text, location, heading=""):
        text = normal(text)
        if text:
            blocks.append(
                {
                    "id": f"b{len(blocks):04d}",
                    "text": text,
                    "location": location,
                    "heading": heading,
                }
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
        for tag in main.select("script,style,nav,footer,header,form,noscript"):
            tag.decompose()
        heading = ""

        def data_row(tag):
            return (
                tag.name == "tr"
                and not tag.find("tr")
                and len(normal(tag.get_text(" "))) <= 3000
                and len(tag.find_all(["td", "th"], recursive=False)) >= 2
            )

        for i, tag in enumerate(
            main.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr"])
        ):
            if tag.find_parent(["p", "li"]) is not None:
                continue
            if tag.name == "tr" and not data_row(tag):
                continue
            parent_row = tag.find_parent("tr")
            if parent_row is not None and data_row(parent_row):
                continue
            if tag.name.startswith("h"):
                heading = normal(tag.get_text(" "))
            add(tag.get_text(" "), {"tag": tag.name, "index": i}, heading)
    if len(" ".join(b["text"] for b in blocks)) < 80:
        raise PipelineError(
            "EMPTY_PARSED_TEXT", "No usable text; OCR or a source adapter may be needed"
        )
    return {"parser_version": PARSER_VERSION, "blocks": blocks, "links": links}
