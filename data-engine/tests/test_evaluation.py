import json
from pathlib import Path
import pytest
from typer.testing import CliRunner
from kb_pipeline.acquire import parse, PARSER_VERSION
from kb_pipeline.config import PROJECT
from kb_pipeline.contracts import PipelineError
from kb_pipeline.db import jobs, snapshots, claims
from kb_pipeline.evaluation import load_dataset, classifier_report, extraction_report
from kb_pipeline.cli import app
from conftest import HTML


def dataset_for(engine, settings, run_id):
    job = engine.store.rows(jobs, run_id=run_id)[0]
    source = engine.store.one(snapshots, id=job["snapshot_id"])
    document = parse(HTML, "text/html", source["url"])
    # Known synthetic source has a title, introduction, four fact rows, and one requirement.
    expected = {
        "b0000": "relevant",
        "b0001": "other",
        "b0002": "relevant",
        "b0003": "relevant",
        "b0004": "relevant",
        "b0005": "relevant",
        "b0006": "relevant",
    }
    value = {
        "schema_version": "evaluation-v1",
        "name": "synthetic-snapshot",
        "annotation": "Manual labels for the synthetic HTML test source",
        "source": {
            "target_id": "test-bsc",
            "url": source["url"],
            "sha256": source["hash"],
            "raw_path": source["path"],
            "content_type": source["content_type"],
            "observed_at": source["observed_at"],
            "parser": PARSER_VERSION,
        },
        "cases": [
            {
                "id": id,
                "expected": label,
                "critical": label == "relevant",
                "reason": "Manual source label",
            }
            for id, label in expected.items()
        ],
        "expected_facts": [
            {
                "id": "title",
                "field": "programme_title",
                "location_id": "b0000",
                "contains": ["Computer Science"],
                "critical": True,
            }
        ],
    }
    path = settings.data_dir / "synthetic-evaluation.json"
    path.write_text(json.dumps(value))
    return path, value, document


def test_portable_manual_classifier_dataset_needs_no_provider(tmp_path):
    labelled, document = load_dataset(
        PROJECT / "evaluation/classifier-smoke-v1.json", tmp_path
    )
    report = classifier_report(labelled, document)
    assert report["passed"] and report["sample_count"] == 34
    assert report["critical_misses"] == []


def test_classifier_metrics_detect_deliberately_wrong_predictions(
    tmp_path, monkeypatch
):
    import kb_pipeline.evaluation as module

    labelled, document = load_dataset(
        PROJECT / "evaluation/classifier-smoke-v1.json", tmp_path
    )
    monkeypatch.setattr(module, "classify", lambda _: "other")
    report = classifier_report(labelled, document)
    assert report["recall"] == 0 and report["counts"]["false_negative"] == 22
    assert report["critical_misses"] and not report["passed"]


def test_source_hash_and_complete_labels_are_required(engine, settings):
    rid = engine.enqueue()
    engine.work(rid)
    path, value, _ = dataset_for(engine, settings, rid)
    labelled, document = load_dataset(path, settings.data_dir)
    assert classifier_report(labelled, document)["passed"]
    value["cases"].pop()
    path.write_text(json.dumps(value))
    with pytest.raises(PipelineError) as exc:
        load_dataset(path, settings.data_dir)
    assert exc.value.code == "EVALUATION_LABELS_MISMATCH"
    value["source"]["sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(PipelineError) as exc:
        load_dataset(path, settings.data_dir)
    assert exc.value.code == "EVALUATION_SOURCE_CHANGED"


def test_rules_do_not_count_as_a_successful_llm_evaluation(engine, settings):
    rid = engine.enqueue()
    engine.work(rid)
    path, _, _ = dataset_for(engine, settings, rid)
    labelled, document = load_dataset(path, settings.data_dir)
    report = extraction_report(engine.store, rid, labelled, document)
    assert not report["passed"] and report["model_claim_count"] == 0
    assert report["missing"] == [{"expected": "title", "critical": True}]


def test_no_key_pilot_uses_snapshot_without_network_and_leaves_review_pending(
    engine, settings, monkeypatch
):
    import kb_pipeline.cli as cli

    rid = engine.enqueue()
    engine.work(rid)
    path, _, _ = dataset_for(engine, settings, rid)

    def deny(*_):
        pytest.fail("Pilot must not refetch the retained source")

    monkeypatch.setattr(engine.fetch_client, "send", deny)
    monkeypatch.setattr(cli, "engine", lambda: engine)
    result = CliRunner().invoke(app, ["pilot", "--dataset", str(path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["classifier"]["passed"]
    assert report["extraction"]["status"] == "not_run"
    assert report["run"]["cost_basis"] == "no_model_calls"
    assert Path(report["report_path"]).is_file()
    assert all(r["review"] == "pending" for r in engine.store.rows(claims))


def test_extraction_evaluation_requires_model_grounding_and_exact_snapshot(
    engine, settings
):
    from kb_pipeline.db import runs, fingerprint

    rid = engine.enqueue(llm=True)
    # Complete locally with rules to seed source artifacts, then inject controlled model candidates.
    row = engine.store.one(runs, id=rid)
    config = json.loads(row["config"])
    config["llm"] = False
    engine.store.update(runs, rid, config=json.dumps(config))
    engine.work(rid)
    config["llm"] = True
    engine.store.update(runs, rid, config=json.dumps(config))
    path, _, _ = dataset_for(engine, settings, rid)
    labelled, document = load_dataset(path, settings.data_dir)
    title = next(
        r
        for r in engine.store.rows(claims, run_id=rid)
        if json.loads(r["body"])["field"] == "programme_title"
    )
    model = dict(title)
    body = json.loads(model["body"])
    body["method"] = "openrouter:synthetic-model"
    model.update(id=fingerprint(body), body=json.dumps(body))
    engine.store.insert(claims, **model)
    assert extraction_report(engine.store, rid, labelled, document)["passed"]
    body["value"] = "An invented programme"
    engine.store.update(claims, model["id"], body=json.dumps(body))
    report = extraction_report(engine.store, rid, labelled, document)
    assert not report["passed"] and report["invalid_claims"]
    labelled.source.sha256 = "0" * 64
    with pytest.raises(PipelineError) as exc:
        extraction_report(engine.store, rid, labelled, document)
    assert exc.value.code == "EVALUATION_SOURCE_CHANGED"


@pytest.mark.parametrize("with_model_claim", [True, False])
def test_groq_pilot_cli_evaluates_actual_adapter_output(
    engine, settings, monkeypatch, with_model_claim
):
    from dataclasses import replace
    from decimal import Decimal
    import httpx
    import kb_pipeline.cli as cli
    from kb_pipeline.engine import Engine

    original = engine.enqueue()
    engine.work(original)
    path, _, _ = dataset_for(engine, settings, original)
    calls = []

    def model_request(request):
        calls.append(request)
        claim = {
            "field": "programme_title",
            "value": "Computer Science (B.Sc.)",
            "quote": "Computer Science (B.Sc.)",
            "location_id": "b0000",
            "applicant_group": "not established",
            "intake": None,
            "conditions": None,
            "method": "llm",
        }
        return httpx.Response(
            200,
            json={
                "id": "synthetic-evaluation-call",
                "model": "openai/gpt-oss-20b",
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"claims": [claim] if with_model_claim else []}
                            )
                        },
                    }
                ],
            },
        )

    selected = replace(
        settings,
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback_model="",
        api_key="synthetic-pilot-key",
        input_rate=Decimal(".075"),
        output_rate=Decimal(".30"),
    )
    e = Engine(
        selected,
        store=engine.store,
        fetch_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("Pilot refetched source")
            )
        ),
        model_client=httpx.Client(transport=httpx.MockTransport(model_request)),
    )
    monkeypatch.setattr(cli, "engine", lambda: e)
    result = CliRunner().invoke(app, ["pilot", "--llm", "--dataset", str(path)])
    report = json.loads(result.stdout)
    assert len(calls) == 1
    assert result.exit_code == (0 if with_model_claim else 1)
    assert report["extraction"]["passed"] == with_model_claim
    assert report["run"]["known_cost_usd"] is None
    assert Decimal(report["run"]["estimated_cost_usd"]) > 0
    assert "synthetic-pilot-key" not in result.output
