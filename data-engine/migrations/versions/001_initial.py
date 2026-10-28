"""Initial local evidence and review schema, frozen at revision 001."""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE ops_runs (\n\tid VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tcreated_at VARCHAR, \n\tfinished_at VARCHAR, \n\tconfig TEXT, \n\tbudget VARCHAR, \n\tspent VARCHAR, \n\treserved VARCHAR, \n\tparent_error_id VARCHAR, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE ops_snapshots (\n\tid VARCHAR NOT NULL, \n\turl VARCHAR, \n\thash VARCHAR, \n\tpath VARCHAR, \n\tcontent_type VARCHAR, \n\tobserved_at VARCHAR, \n\theaders TEXT, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE kb_releases (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\tcreated_at VARCHAR, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES ops_runs (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE ops_jobs (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\ttarget TEXT, \n\tstatus VARCHAR, \n\tstage VARCHAR, \n\tattempt INTEGER, \n\tsnapshot_id VARCHAR, \n\tparsed_path VARCHAR, \n\tlease VARCHAR, \n\tlease_until VARCHAR, \n\terror_id VARCHAR, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES ops_runs (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE ops_errors (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\tjob_id VARCHAR, \n\tstage VARCHAR, \n\tcode VARCHAR, \n\tmessage TEXT, \n\tdiagnostic_path VARCHAR, \n\tstatus VARCHAR, \n\tcreated_at VARCHAR, \n\tretryable INTEGER, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES ops_runs (id), \n\tFOREIGN KEY(job_id) REFERENCES ops_jobs (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE staging_claims (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\tjob_id VARCHAR, \n\tentity_id VARCHAR, \n\tsnapshot_id VARCHAR, \n\tbody TEXT, \n\tvalidation VARCHAR, \n\tquality TEXT, \n\treview VARCHAR, \n\treviewer VARCHAR, \n\treview_note TEXT, \n\treviewed_at VARCHAR, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES ops_runs (id), \n\tFOREIGN KEY(job_id) REFERENCES ops_jobs (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES ops_snapshots (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE kb_facts (\n\tid VARCHAR NOT NULL, \n\trelease_id VARCHAR, \n\tclaim_id VARCHAR, \n\tentity_id VARCHAR, \n\ttarget TEXT, \n\tbody TEXT, \n\tevidence TEXT, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(release_id) REFERENCES kb_releases (id), \n\tFOREIGN KEY(claim_id) REFERENCES staging_claims (id)\n)\n\n"
    )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; back up and migrate explicitly")
