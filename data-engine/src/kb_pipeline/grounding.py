"""Attach exact retained source text to model candidates without fuzzy repair."""

import re
from .acquire import normal
from .extract import value_in_quote

GROUNDING_VERSION = "exact-blocks-v2"


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
    singles = [b for b in blocks if quote in normal(b["text"])]
    selected = next((b for b in singles if b["id"] == claim.location_id), None)
    if selected:
        matched = [selected]
    elif len(singles) == 1:
        matched = singles
    elif singles:
        return [claim], None
    else:
        matched = _spanning_blocks(claim, quote, blocks, source_blocks)
        if matched is None:
            return [claim], None
    result = []
    for block in matched:
        text = block["text"]
        value = claim.value
        if claim.field in ("requirement", "tuition", "semester_contribution"):
            value = text
        elif claim.field == "teaching_language":
            value = re.sub(
                r"^(?:languages? of instruction|teaching language)\s*[:：]?\s*",
                "",
                text,
                flags=re.I,
            )
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
        "source_locations": [b["id"] for b in matched],
        "field": claim.field,
        "grounder": GROUNDING_VERSION,
        "reason": "unique verbatim source match; full source clauses retained",
    }
