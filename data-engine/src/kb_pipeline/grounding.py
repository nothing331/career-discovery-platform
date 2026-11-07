"""Attach exact retained source text to model candidates without fuzzy repair."""

import re
import unicodedata
from .acquire import normal
from .extract import value_in_quote

GROUNDING_VERSION = "exact-blocks-v3"


_DASHES = re.compile("[\u2010-\u2015\u2212\u00ad\ufe58\ufe63\uff0d-]")
_DROPPED = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))
_APOS = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032\u00b4`"), "'")
_DQUOTE = dict.fromkeys(
    map(ord, "\u201c\u201d\u201e\u201f\u2033\u00ab\u00bb"), '"'
)


def _loose(text):
    """Typography-insensitive key of ``text`` plus, per key char, its index in ``text``.

    Whitespace of any kind, every hyphen/dash/soft hyphen (PDF line-break hyphenation,
    U+2011 non-breaking hyphen, en dash), zero-width characters and the quote style
    are ignored; letters and digits are compared exactly. This repairs typography
    only: reworded, elided or reordered text never produces the same key.
    """
    key, index = [], []
    for i, ch in enumerate(text):
        if ch.isspace() or _DASHES.match(ch) or ord(ch) in _DROPPED:
            continue
        for c in unicodedata.normalize("NFKC", ch).translate(_APOS).translate(_DQUOTE):
            if not c.isspace() and not _DASHES.match(c):
                key.append(c)
                index.append(i)
    return "".join(key), index


def _verbatim_span(quote, text):
    """The exact span of ``text`` that equals ``quote`` up to typography, or None.

    A trailing sentence punctuation mark the model appended to its quote is ignored.
    """
    qkey, _ = _loose(quote.rstrip())
    qkey = qkey.rstrip(".;:,")
    if len(qkey) < 3:
        return None
    tkey, tindex = _loose(text)
    start = tkey.find(qkey)
    if start < 0:
        return None
    return text[tindex[start] : tindex[start + len(qkey) - 1] + 1]


def _matches(quote, blocks):
    """(block, verbatim span) for blocks carrying the quote: exact first, else typographic."""
    exact = [(b, quote) for b in blocks if quote in normal(b["text"])]
    if exact:
        return exact
    loose = []
    for b in blocks:
        span = _verbatim_span(quote, normal(b["text"]))
        if span:
            loose.append((b, span))
    return loose


def _distance(a, b):
    digits = lambda x: int(re.sub(r"\D", "", x) or 0)  # noqa: E731
    return abs(digits(a) - digits(b))


def _spanning_blocks(claim, quote, blocks, source_blocks):
    """Source blocks behind a quote that spans several blocks, or None.

    requirement: one unique consecutive run of complete blocks equal to the quote.
    other fields: the model often joins whole paragraphs with newlines (adjacent or
    not). When every non-empty line is verbatim inside exactly one supplied block,
    keep the single such block that carries the value; otherwise nothing.
    """
    positions = {
        b["id"]: i
        for i, b in enumerate(source_blocks if source_blocks is not None else blocks)
    }
    sequences = []
    for i in range(len(blocks)):
        text = ""
        for j in range(i, len(blocks)):
            text = (text + " " + normal(blocks[j]["text"])).strip()
            if len(text) > len(quote):
                break
            if (
                text == quote
                and j > i
                and all(
                    positions.get(blocks[k]["id"], -2) + 1
                    == positions.get(blocks[k + 1]["id"], -4)
                    for k in range(i, j)
                )
            ):
                sequences.append(blocks[i : j + 1])
    if claim.field == "requirement":
        return sequences[0] if len(sequences) == 1 else None
    if len(sequences) == 1:
        candidates = sequences[0]
    else:
        lines = [normal(x) for x in claim.quote.split("\n") if normal(x)]
        if len(lines) < 2:
            return None
        candidates = []
        for line in lines:
            owners = [b for b in blocks if line in normal(b["text"])]
            if len(owners) != 1:
                return None
            candidates.append(owners[0])
    holders = [
        b
        for b in candidates
        if value_in_quote(claim.field, claim.value, normal(b["text"]))
    ]
    return holders if len(holders) == 1 else None


def ground(claim, blocks, *, source_blocks=None):
    """Return candidates plus an audit action. The original model cache stays intact.

    A wrong location can be repaired only by a unique verbatim match among the
    blocks supplied to the model. A merged requirement can be split only when
    its quote equals one unique consecutive sequence of complete source blocks.
    This never supplies a candidate for text the model did not select.
    """
    quote = normal(claim.quote)
    if (
        not quote
        or not normal(claim.value)
        or not value_in_quote(claim.field, claim.value, quote)
    ):
        return [claim], None
    hits = _matches(quote, blocks)
    selected = next((h for h in hits if h[0]["id"] == claim.location_id), None)
    if selected:
        matched = [selected]
    elif len(hits) == 1:
        matched = hits
    elif (
        hits
        and claim.field == "programme_title"
        and len({normal(h[0]["text"]) for h in hits}) == 1
    ):
        # A title repeated verbatim in several blocks (page header, breadcrumb, list):
        # the evidence is the same text, so keep the one nearest the cited location.
        # Other fields stay ambiguous: identical clauses may carry different scope.
        matched = [min(hits, key=lambda h: _distance(h[0]["id"], claim.location_id))]
    elif hits:
        return [claim], None
    else:
        spanning = _spanning_blocks(claim, quote, blocks, source_blocks)
        if spanning is None:
            return [claim], None
        matched = [(b, None) for b in spanning]
    result = []
    for block, span in matched:
        text = block["text"]
        oversized = len(text) > 4000 or (
            claim.field
            in ("requirement", "tuition", "semester_contribution", "teaching_language")
            and len(text) > 3000
        )
        if oversized:
            # The whole block cannot be retained as the quote/value: keep the model's
            # own verbatim sub-quote, now at the block that actually contains it.
            if span is None or len(span) > 3000:
                return [claim], None
            text = span
        value = claim.value
        if claim.field in ("requirement", "tuition", "semester_contribution"):
            value = text
        elif claim.field == "teaching_language" and not oversized:
            value = re.sub(
                r"^(?:languages? of instruction|teaching language)\s*[:：]?\s*",
                "",
                text,
                flags=re.I,
            )
        if not value_in_quote(claim.field, value, text):
            # Typography repaired in the quote carries over to a free-text value
            # (hyphenated "Appli- cations" ...): use the source's spelling of it.
            value = _verbatim_span(normal(value), text) or value
        conditions = claim.conditions
        if len(matched) > 1:
            # Keep the full selected sequence, including conjunctions/waivers,
            # as context rather than turning split rows into independent rules.
            conditions = (
                claim.quote if not conditions else claim.quote + " " + conditions
            )
        elif claim.field == "deadline" and not conditions:
            conditions = block.get("heading") or None
        if len(value) > 3000 or len(text) > 4000:
            return [claim], None
        result.append(
            claim.model_copy(
                update={
                    "location_id": block["id"],
                    "value": value,
                    "quote": text,
                    "conditions": conditions,
                }
            )
        )
    if len(result) == 1 and result[0] == claim:
        return result, None
    return result, {
        "original_location": claim.location_id,
        "source_locations": [h[0]["id"] for h in matched],
        "field": claim.field,
        "grounder": GROUNDING_VERSION,
        "reason": "unique verbatim source match; full source clauses retained",
    }
