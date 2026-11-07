"""Read-only catalogue API. Bind locally; collection/review remain local CLI operations."""

from fastapi import FastAPI, HTTPException, Query
from .config import Settings
from .db import Store
from .knowledge import catalogue


def create_app(settings=None):
    settings = settings or Settings.load()
    store = Store(settings.data_dir)
    app = FastAPI(title="Programme knowledge POC", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "publication": "review required"}

    @app.get("/v1/programmes")
    def programmes(
        country: str | None = None,
        level: str | None = Query(None, pattern="^(bachelor|master)$"),
    ):
        return {"programmes": catalogue(store, country=country, level=level)}

    @app.get("/v1/programmes/{programme_id}")
    def programme(programme_id: str):
        rows = catalogue(store, entity=programme_id)
        if not rows:
            raise HTTPException(404, "No published programme with this ID")
        return rows[0]

    @app.get("/v1/programmes/{programme_id}/evidence")
    def evidence(programme_id: str):
        return {
            "release_id": programme(programme_id)["release_id"],
            "facts": programme(programme_id)["facts"],
        }

    return app
