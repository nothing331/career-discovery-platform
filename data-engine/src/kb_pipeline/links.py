"""Deterministic selection of admissions-relevant outlinks (depth-1 crawl)."""

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .acquire import check_url
from .contracts import PipelineError

LINK_SELECTOR_VERSION = "roles-v2"

_B = r"(?<![a-zäöüß])"
_E = r"(?![a-zäöüß])"

_ROLE_SOURCES = {
    "admission": [
        r"admission(?!\s*regulation)",
        r"entry[\s_-]*requirement",
        r"eligibility",
        r"prerequisite",
        r"zulassung(?!s?ordnung)",
        r"zugangsvoraussetzung",
        r"voraussetzung",
        r"eignungsfeststellung",
        r"aptitude",
    ],
    "application": [
        _B + r"apply" + _E,
        r"application",
        r"bewerbung(?!sfrist)",
        r"bewerben",
        r"uni-?assist",
        r"enrol+ment",
        r"einschreibung",
        r"immatrikulation",
    ],
    "fees": [
        _B + r"fees?" + _E,
        r"tuition",
        r"semester[\s_-]*contribution",
        r"semesterbeitrag",
        r"studiengeb(ü|ue)hr",
        r"geb(ü|ue)hren",
        _B + r"beitrag" + _E,
        _B + r"costs?" + _E,
    ],
    "regulations": [
        r"(exam|examination|study|admission|degree)s?[\s_-]*regulation",
        r"(prüfungs|pruefungs|studien|zulassungs|fachprüfungs|fachpruefungs)[\s_-]*ordnung",
        _B + r"satzung",
        r"po[\s_-]*(bsc|msc|ba|ma)" + _E,
    ],
    "language": [
        r"language[\s_-]*(requirement|certificate|proficiency|test)",
        _B + r"ielts" + _E,
        _B + r"toefl" + _E,
        r"test[\s_-]?daf",
        _B + r"dsh" + _E,
        r"sprachnachweis",
        r"sprachkenntnis",
        r"deutschkenntnis",
        r"english[\s_-]*proficiency",
    ],
    "deadlines": [
        r"deadline",
        _B + r"frist(en)?" + _E,
        r"bewerbungsfrist",
        _B + r"dates" + _E,
    ],
}
ROLES = {k: [re.compile(p, re.I) for p in v] for k, v in _ROLE_SOURCES.items()}

_EXCLUDE = re.compile(
    "|".join(
        [
            _B + r"login" + _E,
            r"log[\s_-]?in" + _E,
            r"intranet",
            _B + r"news",
            _B + r"events?" + _E,
            _B + r"press" + _E,
            _B + r"contact" + _E,
            _B + r"kontakt" + _E,
            _B + r"(staff|people|personen|mitarbeiter)" + _E,
            _B + r"search" + _E,
            _B + r"suche" + _E,
            r"sitemap",
            r"imprint",
            r"impressum",
            r"privacy",
            r"datenschutz",
            _B + r"jobs?" + _E,
            _B + r"careers?" + _E,
            r"stellen",
            r"skip[\s_-]to",
        ]
    ),
    re.I,
)
_SOCIAL = (
    "facebook.",
    "twitter.",
    "x.com",
    "instagram.",
    "linkedin.",
    "youtube.",
    "youtu.be",
    "mastodon.",
    "tiktok.",
    "xing.",
)
_BAD_EXT = re.compile(
    r"\.(ics|png|jpe?g|gif|svg|webp|ico|zip|docx?|xlsx?|pptx?|mp[34]|css|js)$", re.I
)
_HTML_EXT = re.compile(r"\.(html?|php|aspx?|xhtml)$", re.I)
_MODULE_HB = re.compile(r"modul(e)?[\s_-]*(handbook|handbuch)", re.I)
MAX_PER_ROLE = 2
_LEVEL_RX = {
    "bachelor": re.compile(
        _B + r"(?:bachelor[a-zäöüß]*|b\.?sc\.?|b\.?a\.?)" + _E, re.I
    ),
    "master": re.compile(_B + r"(?:master[a-zäöüß]*|m\.?sc\.?|m\.?a\.?)" + _E, re.I),
}


def _other_level_only(level, *texts):
    """True when the link names only the degree level that is not the target's."""
    blob = " ".join(texts)
    other = "master" if level == "bachelor" else "bachelor"
    return bool(_LEVEL_RX[other].search(blob)) and not _LEVEL_RX[level].search(blob)


def _normalise(url):
    p = urlsplit(url.strip())
    host = p.hostname or ""
    netloc = host if p.port in (None, 443) else f"{host}:{p.port}"
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


def _roles(*texts):
    found = set()
    for role, patterns in ROLES.items():
        if any(p.search(t) for t in texts for p in patterns):
            found.add(role)
    return found


def _segments(path):
    return [s for s in path.lower().split("/") if s]


def _prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def select_followups(document, target, *, limit=6):
    target_url = _normalise(str(target.url)).rstrip("/")
    target_segs = _segments(urlsplit(target_url).path)
    hosts = set(target.allowed_hosts)
    merged = {}
    for link in document.get("links", []):
        raw = (link.get("url") or "").strip()
        text = " ".join((link.get("text") or "").split())
        try:
            check_url(raw, hosts)
        except PipelineError:
            continue
        url = _normalise(raw)
        if url.rstrip("/") == target_url:
            continue
        path = unquote(urlsplit(url).path)
        host = urlsplit(url).hostname or ""
        if any(s in host for s in _SOCIAL) or _BAD_EXT.search(path):
            continue
        if _EXCLUDE.search(path) or _EXCLUDE.search(text):
            continue
        if _other_level_only(target.level, path, text):
            continue
        is_pdf = path.lower().endswith(".pdf")
        if (
            not is_pdf
            and re.search(r"\.[a-z0-9]{2,5}$", path, re.I)
            and not _HTML_EXT.search(path)
        ):
            continue
        text_roles = _roles(text)
        roles = text_roles | _roles(path)
        # module handbooks are excluded unless the link also names regulations
        if _MODULE_HB.search(path + " " + text) and "regulations" not in roles:
            continue
        if not roles:
            continue
        entry = merged.setdefault(
            url,
            {
                "url": url,
                "texts": [],
                "roles": set(),
                "text_roles": set(),
                "pdf": is_pdf,
            },
        )
        if text and text not in entry["texts"]:
            entry["texts"].append(text)
        entry["roles"] |= roles
        entry["text_roles"] |= text_roles
    ranked = []
    for e in merged.values():
        score = len(e["roles"]) + (1 if e["text_roles"] else 0)
        if e["pdf"] and "regulations" in e["roles"]:
            score += 1
        pre = _prefix(_segments(urlsplit(e["url"]).path), target_segs)
        ranked.append((-score, -pre, e["url"], e, score))
    ranked.sort(key=lambda r: r[:3])
    counts = dict.fromkeys(ROLES, 0)
    out = []
    for *_, e, score in ranked:
        if len(out) >= limit:
            break
        roles = sorted(e["roles"])
        if all(counts[r] >= MAX_PER_ROLE for r in roles):
            continue
        for r in roles:
            counts[r] += 1
        out.append(
            {
                "url": e["url"],
                "text": " | ".join(e["texts"]),
                "roles": roles,
                "score": score,
                "kind": "pdf" if e["pdf"] else "html",
            }
        )
    return out
