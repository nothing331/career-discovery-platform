from kb_pipeline.contracts import Claim
from kb_pipeline.grounding import ground
from kb_pipeline.extract import validate


def block(id, text):
    return {"id": id, "text": text, "heading": "Entry conditions"}


def claim(text, id="wrong", field="requirement", value=None):
    return Claim(
        field=field,
        value=value or text,
        quote=text,
        location_id=id,
        applicant_group="not established",
        intake=None,
        conditions=None,
        method="groq:test-model",
    )


def test_unique_exact_quote_can_restore_wrong_location():
    text = "A language certificate is needed unless a documented exemption applies."
    source = [block("correct", text)]
    result, action = ground(claim(text), source)
    assert result[0].location_id == "correct" and action["original_location"] == "wrong"
    assert validate(result[0], {"blocks": source}) == "MISSING_APPLICANT_SCOPE"


def test_merged_requirements_expand_only_with_exact_consecutive_source_context():
    a = "A prior degree is required."
    b = "Alternatively, equivalent experience may be considered."
    source = [block("a", a), block("b", b)]
    result, action = ground(claim(a + " " + b), source)
    assert [r.location_id for r in result] == ["a", "b"]
    assert all(r.conditions == a + " " + b for r in result)
    assert action["source_locations"] == ["a", "b"]
    assert all(
        validate(r, {"blocks": source}) == "MISSING_APPLICANT_SCOPE" for r in result
    )
    intervening = block(
        "exception", "This pathway is unavailable to the stated applicant group."
    )
    unchanged, action = ground(
        claim(a + " " + b), source, source_blocks=[source[0], intervening, source[1]]
    )
    assert unchanged[0].location_id == "wrong" and action is None


def test_fabricated_or_ambiguous_quotes_are_not_repaired():
    text = "A language certificate is required."
    source = [block("a", text), block("b", text)]
    original = claim(text)
    result, action = ground(original, source)
    assert result == [original] and action is None
    original = claim("A language certificate is never required.")
    result, action = ground(original, source)
    assert result == [original] and action is None
    assert validate(original, {"blocks": source}) == "EVIDENCE_NOT_FOUND"


def test_full_paragraph_preserves_waiver_after_partial_model_selection():
    fragment = "A language certificate is required"
    text = fragment + ", unless prior instruction was in that language."
    source = [block("a", text)]
    original = claim(fragment, id="a")
    result, action = ground(original, source)
    assert result[0].value == text and result[0].quote == text
    assert action and result[0].intake is None


def test_tuition_preserves_semester_charge_in_same_source():
    text = "No tuition fees apply. However, a semester contribution is payable."
    result, action = ground(
        claim(text, field="tuition", value="No tuition fees"), [block("a", text)]
    )
    assert result[0].value == text and action


def test_language_label_is_canonicalized_without_dropping_choices():
    text = "Languages of instruction German and English (either or both)."
    result, action = ground(claim(text, field="teaching_language"), [block("a", text)])
    assert result[0].value == "German and English (either or both)." and action


def test_oversized_or_empty_evidence_is_not_repaired():
    text = "A degree is required. " + "Example source text. " * 200
    original = claim("A degree is required.", id="a")
    result, action = ground(original, [block("a", text)])
    assert result == [original] and action is None
    empty = claim("    ", id="a")
    result, action = ground(empty, [block("a", text)])
    assert result == [empty] and action is None
    assert validate(empty, {"blocks": [block("a", text)]}) == "EMPTY_CLAIM"
