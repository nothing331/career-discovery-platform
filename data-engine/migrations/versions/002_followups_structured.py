"""Follow-up page audit, claim dedupe keys and structured facts, frozen at revision 002.

Existing staging_claims rows keep claim_key/agreeing_methods NULL: SQLite treats NULLs
as distinct, so the unique index never blocks them and they are never merged retroactively.
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE ops_pages (id VARCHAR NOT NULL, job_id VARCHAR, url VARCHAR, roles TEXT, link_text TEXT, kind VARCHAR, snapshot_id VARCHAR, status VARCHAR, error_code VARCHAR, created_at VARCHAR, PRIMARY KEY (id), FOREIGN KEY(job_id) REFERENCES ops_jobs (id), FOREIGN KEY(snapshot_id) REFERENCES ops_snapshots (id))"
    )
    op.execute("CREATE INDEX ix_ops_pages_job_id ON ops_pages (job_id)")
    op.execute("ALTER TABLE staging_claims ADD COLUMN claim_key VARCHAR")
    op.execute("ALTER TABLE staging_claims ADD COLUMN agreeing_methods TEXT")
    op.execute(
        "CREATE UNIQUE INDEX uq_staging_claims_run_claim_key ON staging_claims (run_id, claim_key)"
    )
    op.execute(
        "CREATE TABLE structured_facts (id VARCHAR NOT NULL, run_id VARCHAR, job_id VARCHAR, entity_id VARCHAR, kind VARCHAR, data TEXT, evidence_claim_ids TEXT, evidence_text TEXT, method VARCHAR, applicant_group VARCHAR, fact_key VARCHAR, review VARCHAR DEFAULT 'pending', created_at VARCHAR, PRIMARY KEY (id), FOREIGN KEY(run_id) REFERENCES ops_runs (id), FOREIGN KEY(job_id) REFERENCES ops_jobs (id))"
    )
    op.execute("CREATE INDEX ix_structured_facts_kind ON structured_facts (kind)")
    op.execute(
        "CREATE UNIQUE INDEX uq_structured_facts_run_fact_key ON structured_facts (run_id, fact_key)"
    )
    op.execute(
        "CREATE TABLE kb_structured_facts (id VARCHAR NOT NULL, release_id VARCHAR, entity_id VARCHAR, kind VARCHAR, data TEXT, evidence TEXT, method VARCHAR, PRIMARY KEY (id), FOREIGN KEY(release_id) REFERENCES kb_releases (id))"
    )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; back up and migrate explicitly")
