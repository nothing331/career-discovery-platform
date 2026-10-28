import json
from pathlib import Path
from decimal import Decimal
import typer
from .config import Settings
from .contracts import PipelineError
from .engine import Engine
from .db import jobs, claims, errors, runs
from .knowledge import review, publish, catalogue, resolve_error
from .logging import Redactor

app = typer.Typer(
    help="Local programme collection. Model calls are opt-in; publication requires review.",
    pretty_exceptions_enable=False,
)


def engine():
    return Engine()


def output(value):
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command()
def init():
    e = engine()
    output(
        {
            "database": str(e.store.directory / "poc.db"),
            "targets": len(e.registry().targets),
            "model_key_configured": bool(e.settings.api_key),
        }
    )


@app.command()
def run(
    llm: bool = False,
    budget_usd: str | None = None,
    target: str | None = None,
    enqueue_only: bool = False,
):
    e = engine()
    targets = e.registry().targets
    if target:
        targets = [t for t in targets if t.id == target]
    rid = e.enqueue(
        targets=targets,
        llm=llm,
        budget=Decimal(budget_usd) if budget_usd is not None else None,
    )
    output({"run_id": rid, "status": "queued"})
    if not enqueue_only:
        output(e.work(rid))


@app.command()
def work(run_id: str):
    output(engine().work(run_id))


@app.command()
def status(run_id: str):
    output(engine().report(run_id))


@app.command("claims")
def list_claims(run_id: str):
    e = engine()
    output(
        [
            {**r, "body": json.loads(r["body"]), "quality": json.loads(r["quality"])}
            for r in e.store.rows(claims, run_id=run_id)
        ]
    )


@app.command("errors")
def list_errors(run_id: str, stage: str | None = None):
    rows = engine().store.rows(errors, run_id=run_id)
    output([r for r in rows if stage is None or r["stage"] == stage])


@app.command()
def replay(
    error_id: str,
    from_snapshot: bool = False,
    offline: bool = False,
    allow_paid_models: bool = False,
    budget_usd: str = "1",
):
    if not from_snapshot or offline == allow_paid_models:
        raise typer.BadParameter(
            "Use --from-snapshot and exactly one of --offline or --allow-paid-models"
        )
    e = engine()
    rid = e.replay(error_id, allow_paid=allow_paid_models, budget=Decimal(budget_usd))
    output(e.work(rid))


@app.command("review")
def review_claim(
    claim_id: str,
    reviewer: str,
    approve: bool = False,
    reject: bool = False,
    note: str = "",
    confirm_evidence: bool = False,
):
    if approve == reject or approve and not confirm_evidence:
        raise typer.BadParameter(
            "Choose --approve --confirm-evidence or --reject --note ..."
        )
    review(
        engine().store, claim_id, reviewer, "approved" if approve else "rejected", note
    )
    output({"claim_id": claim_id, "decision": "approved" if approve else "rejected"})


@app.command("publish")
def publish_run(run_id: str):
    output({"release_id": publish(engine().store, run_id)})


@app.command("resolve-error")
def resolve(error_id: str, replay_run_id: str, actor: str, note: str):
    resolve_error(engine().store, error_id, replay_run_id, actor, note)
    output({"error_id": error_id, "status": "resolved", "replay_run_id": replay_run_id})


@app.command("export")
def export_records():
    e = engine()
    path = e.store.directory / "exports" / "catalogue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalogue(e.store), ensure_ascii=False, indent=2))
    output({"path": str(path)})


@app.command()
def serve(port: int = 8000):
    import uvicorn
    from .api import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=port)


@app.command("models")
def models():
    import httpx

    e = engine()
    response = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
    response.raise_for_status()
    wanted = {e.settings.model, e.settings.fallback_model}
    output(
        [
            {
                "id": m["id"],
                "pricing": m["pricing"],
                "structured_outputs": "structured_outputs"
                in m.get("supported_parameters", []),
            }
            for m in response.json()["data"]
            if m["id"] in wanted
        ]
    )


def main():
    try:
        app()
    except Exception as exc:
        import os
        from dotenv import dotenv_values
        from .config import PROJECT

        keys = [
            os.environ.get("OPENROUTER_API_KEY"),
            dotenv_values(PROJECT / ".env").get("OPENROUTER_API_KEY"),
        ]
        typer.echo(
            Redactor(keys).text(f"{getattr(exc, 'code', type(exc).__name__)}: {exc}"),
            err=True,
        )
        raise SystemExit(1)
