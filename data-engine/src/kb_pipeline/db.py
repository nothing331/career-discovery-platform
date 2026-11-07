"""Versioned SQLite schema, short transactions, explicit review/publication boundary."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    Text,
    ForeignKey,
    event,
    select,
)
from .contracts import PipelineError


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


meta = MetaData()
runs = Table(
    "ops_runs",
    meta,
    Column("id", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("created_at", String),
    Column("finished_at", String),
    Column("config", Text),
    Column("budget", String),
    Column("spent", String, default="0"),
    Column("reserved", String, default="0"),
    Column("parent_error_id", String),
)
jobs = Table(
    "ops_jobs",
    meta,
    Column("id", String, primary_key=True),
    Column("run_id", ForeignKey("ops_runs.id")),
    Column("target", Text),
    Column("status", String),
    Column("stage", String),
    Column("attempt", Integer, default=0),
    Column("snapshot_id", String),
    Column("parsed_path", String),
    Column("lease", String),
    Column("lease_until", String),
    Column("error_id", String),
)
snapshots = Table(
    "ops_snapshots",
    meta,
    Column("id", String, primary_key=True),
    Column("url", String),
    Column("hash", String),
    Column("path", String),
    Column("content_type", String),
    Column("observed_at", String),
    Column("headers", Text),
)
errors = Table(
    "ops_errors",
    meta,
    Column("id", String, primary_key=True),
    Column("run_id", ForeignKey("ops_runs.id")),
    Column("job_id", ForeignKey("ops_jobs.id")),
    Column("stage", String),
    Column("code", String),
    Column("message", Text),
    Column("diagnostic_path", String),
    Column("status", String, default="open"),
    Column("created_at", String),
    Column("retryable", Integer),
)
claims = Table(
    "staging_claims",
    meta,
    Column("id", String, primary_key=True),
    Column("run_id", ForeignKey("ops_runs.id")),
    Column("job_id", ForeignKey("ops_jobs.id")),
    Column("entity_id", String),
    Column("snapshot_id", ForeignKey("ops_snapshots.id")),
    Column("body", Text),
    Column("validation", String),
    Column("quality", Text),
    Column("review", String, default="pending"),
    Column("reviewer", String),
    Column("review_note", Text),
    Column("reviewed_at", String),
)
releases = Table(
    "kb_releases",
    meta,
    Column("id", String, primary_key=True),
    Column("run_id", ForeignKey("ops_runs.id")),
    Column("created_at", String),
)
facts = Table(
    "kb_facts",
    meta,
    Column("id", String, primary_key=True),
    Column("release_id", ForeignKey("kb_releases.id")),
    Column("claim_id", ForeignKey("staging_claims.id")),
    Column("entity_id", String),
    Column("target", Text),
    Column("body", Text),
    Column("evidence", Text),
)


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            "sqlite:///" + str(self.directory / "poc.db"), connect_args={"timeout": 30}
        )

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA journal_mode=WAL")

        # Alembic owns schema creation; never silently recreate an existing DB.
        from alembic.config import Config
        from alembic import command

        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
        )
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def rows(self, table, **where):
        with self.engine.connect() as c:
            q = select(table)
            for k, v in where.items():
                q = q.where(table.c[k] == v)
            return [dict(r) for r in c.execute(q).mappings()]

    def one(self, table, **where):
        rows = self.rows(table, **where)
        if not rows:
            raise PipelineError(
                "NOT_FOUND", f"No {table.name} record matches the supplied ID"
            )
        return rows[0]

    def insert(self, table, **values):
        with self.engine.begin() as c:
            c.execute(table.insert().values(**values))

    def update(self, table, identifier, **values):
        with self.engine.begin() as c:
            c.execute(table.update().where(table.c.id == identifier).values(**values))

    def reserve(self, run_id, amount):
        # Lock before reading the balance so another worker cannot over-reserve.
        with self.engine.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            r = c.execute(select(runs).where(runs.c.id == run_id)).mappings().one()
            if Decimal(r["spent"]) + Decimal(r["reserved"]) + amount > Decimal(
                r["budget"]
            ):
                c.rollback()
                raise PipelineError(
                    "BUDGET_EXHAUSTED", "Insufficient remaining run budget"
                )
            c.execute(
                runs.update()
                .where(runs.c.id == run_id)
                .values(reserved=str(Decimal(r["reserved"]) + amount))
            )
            c.commit()

    def settle(self, run_id, reservation, actual):
        with self.engine.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            r = c.execute(select(runs).where(runs.c.id == run_id)).mappings().one()
            c.execute(
                runs.update()
                .where(runs.c.id == run_id)
                .values(
                    reserved=str(Decimal(r["reserved"]) - reservation),
                    spent=str(Decimal(r["spent"]) + actual),
                )
            )
            c.commit()
