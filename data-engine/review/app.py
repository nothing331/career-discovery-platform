"""Run with: uv run --extra review streamlit run review/app.py --server.address 127.0.0.1"""

import json
import streamlit as st
from kb_pipeline.engine import Engine
from kb_pipeline.db import runs, jobs, claims, errors
from kb_pipeline.knowledge import review, publish, catalogue

st.set_page_config(page_title="Fieldnotes · Data review", layout="wide")
st.title("Programme data review")
st.caption(
    "Local collection POC · candidate facts need explicit evidence review before publication."
)
e = Engine()
all_runs = e.store.rows(runs)
if not all_runs:
    st.info("No collection runs yet. Run `uv run python -m kb_pipeline run` first.")
    st.stop()
run_id = st.sidebar.selectbox("Collection run", [r["id"] for r in reversed(all_runs)])
report = e.report(run_id)
cols = st.columns(3)
cols[0].metric("Completed documents", report["documents"].get("done", 0))
cols[1].metric("Error events", report["error_events"])
cols[2].metric("Known model cost", "$" + report["known_cost_usd"])
st.caption(
    f"Status: {report['status']} · Reserved/uncertain cost: ${report['reserved_or_uncertain_usd']} · Errors can include held candidates in an otherwise parsed document."
)
review_tab, error_tab, public_tab = st.tabs(
    ["Claims & evidence", "Errors", "Published catalogue"]
)
with review_tab:
    rows = e.store.rows(claims, run_id=run_id)
    if not rows:
        st.info("No candidate facts. Inspect Errors for failed sources.")
    else:
        pending = st.checkbox("Only pending claims", value=True)
        candidates = [r for r in rows if not pending or r["review"] == "pending"]
        if not candidates:
            st.success("No pending claims.")
        else:
            cid = st.selectbox(
                "Candidate",
                [r["id"] for r in candidates],
                format_func=lambda id: next(
                    r["entity_id"]
                    + " · "
                    + json.loads(r["body"])["field"]
                    + " · "
                    + r["validation"]
                    for r in candidates
                    if r["id"] == id
                ),
            )
            row = e.store.one(claims, id=cid)
            body = json.loads(row["body"])
            job = e.store.one(jobs, id=row["job_id"])
            target = json.loads(job["target"])
            st.subheader(target["programme"])
            st.json(body)
            st.write("Validation:", row["validation"])
            st.json(json.loads(row["quality"]))
            st.markdown("**Original source:**")
            st.link_button("Open official source", target["url"])
            st.code(body["quote"], language=None)
            reviewer = st.text_input("Reviewer name")
            note = st.text_area("Review note / reason for rejection")
            confirmed = st.checkbox(
                "I checked the source, applicability, exceptions and evidence location"
            )
            left, right = st.columns(2)
            if left.button(
                "Approve candidate",
                disabled=not reviewer.strip()
                or not confirmed
                or row["validation"] != "valid"
                or report["status"] != "awaiting_review",
            ):
                review(e.store, cid, reviewer, "approved", note)
                st.rerun()
            if right.button(
                "Reject candidate",
                disabled=not reviewer.strip()
                or not note.strip()
                or report["status"] != "awaiting_review",
            ):
                review(e.store, cid, reviewer, "rejected", note)
                st.rerun()
    if st.button(
        "Publish reviewed run", disabled=report["status"] != "awaiting_review"
    ):
        try:
            st.success("Published release " + publish(e.store, run_id))
        except Exception as exc:
            st.error(str(exc))
with error_tab:
    rows = e.store.rows(errors, run_id=run_id)
    stage = st.selectbox("Stage", ["all"] + sorted({r["stage"] for r in rows}))
    code = st.selectbox("Error code", ["all"] + sorted({r["code"] for r in rows}))
    visible = [
        r
        for r in rows
        if (stage == "all" or r["stage"] == stage)
        and (code == "all" or r["code"] == code)
    ]
    st.dataframe(visible, hide_index=True)
    if visible:
        err = st.selectbox("Diagnostic", [r["id"] for r in visible])
        row = e.store.one(errors, id=err)
        path = e.store.directory / row["diagnostic_path"]
        if path.exists():
            st.json(json.loads(path.read_text()))
        else:
            st.warning("Diagnostic artifact unavailable; index entry is retained.")
        st.caption(
            "Replay runs from saved snapshots. A successful replay does not automatically approve facts."
        )
        st.code(
            f"uv run python -m kb_pipeline replay {err} --from-snapshot --offline",
            language="bash",
        )
with public_tab:
    st.json(catalogue(e.store))
