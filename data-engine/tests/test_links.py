import json
from pathlib import Path

import pytest

from kb_pipeline.contracts import Target
from kb_pipeline.links import LINK_SELECTOR_VERSION, ROLES, select_followups

H = "https://www.uni-x.de"
TARGET = Target(
    id="x-msc",
    institution="X",
    programme="CS",
    level="master",
    url=f"{H}/en/study/msc-cs",
    allowed_hosts=["www.uni-x.de"],
)


def doc(*pairs):
    return {"blocks": [], "links": [{"url": u, "text": t} for u, t in pairs]}


def pick(*pairs, **kw):
    return select_followups(doc(*pairs), TARGET, **kw)


def by_url(res):
    return {r["url"]: r for r in res}


def test_version_and_roles():
    assert LINK_SELECTOR_VERSION == "roles-v2"
    assert set(ROLES) == {
        "admission",
        "application",
        "fees",
        "regulations",
        "language",
        "deadlines",
    }


@pytest.mark.parametrize(
    "text,url,role",
    [
        ("Entry requirements", f"{H}/a", "admission"),
        ("Zulassungsvoraussetzungen", f"{H}/a", "admission"),
        ("Go", f"{H}/en/eligibility", "admission"),
        ("How to apply", f"{H}/a", "application"),
        ("Bewerbung", f"{H}/a", "application"),
        ("Go", f"{H}/uni-assist", "application"),
        ("Tuition fees", f"{H}/a", "fees"),
        ("Semesterbeitrag", f"{H}/a", "fees"),
        ("Prüfungsordnung", f"{H}/a", "regulations"),
        ("Go", f"{H}/downloads/Studienordnung.pdf", "regulations"),
        ("IELTS and TOEFL", f"{H}/a", "language"),
        ("Sprachnachweis", f"{H}/a", "language"),
        ("Bewerbungsfrist", f"{H}/a", "deadlines"),
        ("Go", f"{H}/en/deadlines", "deadlines"),
    ],
)
def test_role_detection(text, url, role):
    res = pick((url, text))
    assert len(res) == 1 and role in res[0]["roles"]


def test_cross_host_and_non_https_dropped():
    res = pick(
        ("https://other.de/apply", "Apply"),
        ("http://www.uni-x.de/apply", "Apply"),
        (f"{H}/apply", "Apply"),
    )
    assert [r["url"] for r in res] == [f"{H}/apply"]


def test_fragment_dedupe_and_merge():
    res = pick(
        (f"{H}/apply#a", "Apply"),
        (f"{H}/apply#b", "Application deadline"),
        (f"{H}/apply", ""),
    )
    assert len(res) == 1
    r = res[0]
    assert r["url"] == f"{H}/apply"
    assert {"application", "deadlines"} <= set(r["roles"])
    assert "Apply" in r["text"] and "Application deadline" in r["text"]


def test_target_url_excluded():
    res = pick(
        (f"{H}/en/study/msc-cs#apply", "Apply"),
        (f"{H}/en/study/msc-cs/", "Apply"),
        (f"{H}/en/study/msc-cs", "Apply"),
    )
    assert res == []


def test_exclusions():
    res = pick(
        (f"{H}/news/application-open", "Application news"),
        (f"{H}/login/apply", "Apply login"),
        (f"{H}/en/events/fees", "Fees event"),
        (f"{H}/files/Modulhandbuch.pdf", "Modulhandbuch Zulassung"),
        (f"{H}/en/module-handbook", "Module handbook admission"),
        (f"{H}/jobs/apply", "Apply for jobs"),
        (f"{H}/img/apply.png", "Apply"),
        (f"{H}/cal/deadlines.ics", "Deadlines"),
        (f"{H}/en/impressum", "Application impressum"),
        (f"{H}/en/privacy", "Privacy fees"),
        (f"{H}/en/search", "Search applications"),
        (f"{H}/en/apply", "Apply"),
    )
    assert [r["url"] for r in res] == [f"{H}/en/apply"]


def test_module_handbook_with_regulations_kept():
    res = pick((f"{H}/en/module-handbooks", "Module Handbooks and Exam Regulations"))
    assert res and res[0]["roles"] == ["regulations"]


def test_pdf_regulations_bonus_and_kind():
    res = by_url(
        pick(
            (f"{H}/docs/po.pdf", "Examination regulations"),
            (f"{H}/en/regs", "Examination regulations"),
        )
    )
    assert res[f"{H}/docs/po.pdf"]["kind"] == "pdf"
    assert res[f"{H}/en/regs"]["kind"] == "html"
    assert res[f"{H}/docs/po.pdf"]["score"] == res[f"{H}/en/regs"]["score"] + 1


def test_text_match_scores_above_url_only():
    res = by_url(pick((f"{H}/x/apply", "Click here"), (f"{H}/y/apply", "Apply")))
    assert res[f"{H}/y/apply"]["score"] == res[f"{H}/x/apply"]["score"] + 1


def test_same_section_tiebreak():
    res = pick(
        (f"{H}/other/apply", "Apply"),
        (f"{H}/en/study/msc-cs/apply", "Apply"),
    )
    assert res[0]["url"] == f"{H}/en/study/msc-cs/apply"


def test_per_role_cap_and_limit():
    fees = [(f"{H}/fees/{i}", "Tuition fees") for i in range(5)]
    res = pick(*fees, (f"{H}/apply", "Apply"), (f"{H}/lang", "IELTS"))
    assert sum(r["roles"] == ["fees"] for r in res) == 2
    assert {r["url"] for r in res} >= {f"{H}/apply", f"{H}/lang"}
    many = [
        (f"{H}/{w}", t)
        for w, t in [
            ("a1", "Apply"),
            ("a2", "Bewerbung"),
            ("f1", "Fees"),
            ("f2", "Tuition"),
            ("r1", "Prüfungsordnung"),
            ("r2", "Studienordnung"),
            ("l1", "IELTS"),
            ("l2", "TOEFL"),
            ("d1", "Deadlines"),
            ("d2", "Frist"),
        ]
    ]
    assert len(pick(*many)) == 6
    assert len(pick(*many, limit=3)) == 3
    assert len(pick(*many, limit=20)) == 10


def test_deterministic_and_order_independent():
    pairs = [
        (f"{H}/p{i}", t)
        for i, t in enumerate(
            ["Apply", "Fees", "IELTS", "Deadlines", "Zulassung", "Satzung"]
        )
    ]
    a = pick(*pairs)
    assert a == pick(*pairs)
    assert a == pick(*reversed(pairs))
    assert set(a[0]) == {"url", "text", "roles", "score", "kind"}


def test_real_parsed_documents():
    root = Path(__file__).resolve().parent.parent / "data" / "parsed"
    files = sorted(root.glob("*/blocks-v2/document.json"))
    hosts = {"www.uni-passau.de", "www.tf.uni-freiburg.de"}
    ran = 0
    for f in files:
        d = json.loads(f.read_text())
        host = next(
            (h for h in hosts if any(h in lk["url"] for lk in d["links"])), None
        )
        if not host:
            continue
        t = TARGET.model_copy(
            update={"allowed_hosts": [host], "url": f"https://{host}/__none__"}
        )
        res = select_followups(d, t)
        wanted = {"admission", "application", "regulations"}
        assert any(wanted & set(r["roles"]) for r in res), f
        assert all(r["url"].startswith(f"https://{host}/") for r in res)
        ran += 1
    if not ran:
        pytest.skip("no parsed Passau/Freiburg documents present")
