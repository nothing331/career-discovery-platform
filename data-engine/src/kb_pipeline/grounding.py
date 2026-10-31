"""Attach exact retained source text to model candidates without fuzzy repair."""

import re
from .acquire import normal

GROUNDING_VERSION = "exact-blocks-v1"


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
        or normal(claim.value).casefold() not in quote.casefold()
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
    elif claim.field == "requirement":
        sequences = []
        positions = {
            b["id"]: i
            for i, b in enumerate(
                source_blocks if source_blocks is not None else blocks
            )
        }
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
        if len(sequences) != 1:
            return [claim], None
        matched = sequences[0]
    else:
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
