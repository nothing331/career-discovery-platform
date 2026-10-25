# Connected project workspace

Open `index.html` directly in a browser. It contains the editable product workspace, consolidated research, strategy, Germany data POC plan and historical archive. The reference reader includes Markdown and structured JSON sources. No server, package install or network is needed to use these embedded pages; external websites still require internet access.

Use **Export all pages** to share one HTML file with the current brief, notes, experiment progress, references and calculator settings. Brief and note forms retain their Save buttons and browser-local draft behavior. Export also captures any current unsaved form text. The archive is a read-only snapshot. **Print section** uses the active page's print layout.

## Editing and rebuilding

The main HTML is a generated, portable artifact. Edit its sources and rebuild rather than editing generated markup:

| Source | Purpose |
| --- | --- |
| `src/shell.html`, `src/shell.css`, `src/shell.js` | Shared navigation, routing, saving and complete export |
| `src/child-bridge.js` | Embedded-page sizing, links and state handoff |
| `src/workspace.html` | Editable brief, startup plan, reader, experiments and decisions |
| `research-data.json`, `build-research.py` | Consolidated research report |
| `strategy.html` | Strategy page |
| `poc-plan.html` | POC proposal and cost calculator |
| `research-findings/*.json` and repository Markdown/JSON | Embedded reference library |
| `archive-before-planning-2026-10-25.html` | Preserved historical source; do not overwrite |

Install the build-only dependency and generate the complete workspace from the repository root:

```sh
python3 -m pip install -r product-workspace/requirements-documents.txt
python3 product-workspace/build-workspace.py
```

The builder refreshes the embedded reference library, rebuilds research, adds navigation back to the workspace on the standalone research/strategy/POC pages, then writes `index.html`. Running only the individual document/research builders does not refresh the complete workspace. No build dependency is required by the resulting HTML.

An exported HTML copy contains browser edits; it does not automatically rewrite the source files. If incorporating those edits into a source rebuild, copy the exported workspace's `workspace-data` record into `src/workspace.html`, retaining its revision and updated timestamp. Preserve founder-confirmed answers and prior draft compatibility when changing defaults.
