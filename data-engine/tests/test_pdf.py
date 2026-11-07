import pytest
from kb_pipeline.acquire import parse
from kb_pipeline.contracts import PipelineError


def pdf_bytes():
    # Tiny synthetic PDF; no university document is committed to the repository.
    text = "Applicants must provide a degree in computer science. This is a synthetic parser test, not an admission rule."
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets[1:]:
        result += f"{off:010d} 00000 n \n".encode()
    return (
        result
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
    )


def test_pdf_preserves_page_evidence():
    document = parse(
        pdf_bytes(), "application/pdf", "https://university.example/rules.pdf"
    )
    assert document["blocks"][0]["location"]["page"] == 1
    assert "must provide a degree" in document["blocks"][0]["text"]


def test_bad_pdf_has_actionable_failure():
    with pytest.raises(PipelineError, match="could not read"):
        parse(b"%PDF broken", "application/pdf", "https://university.example/rules.pdf")
