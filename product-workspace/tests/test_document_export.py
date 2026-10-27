"""Run with: python3 -m unittest discover -s product-workspace/tests"""
from pathlib import Path
import importlib.util
import json
import re
import tempfile
import unittest


class DocumentExportTests(unittest.TestCase):
    def test_runtime_files_stay_out_of_shareable_library(self):
        builder_path = Path(__file__).resolve().parents[1] / "build-documents.py"
        spec = importlib.util.spec_from_file_location("document_export_builder", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "product-workspace"
            (workspace / "src").mkdir(parents=True)
            (workspace / "research-findings").mkdir()
            page = workspace / "src" / "workspace.html"
            page.write_text('<script id="workspace-data" type="application/json">{}</script>')
            (root / "plan.md").write_text("# Public plan\nShareable reference.")
            (root / "source.json").write_text('{"title":"Public source"}')
            logs = root / "data" / "logs" / "example-run"
            logs.mkdir(parents=True)
            (logs / "diagnostic.md").write_text("# LOCAL_ONLY_SENTINEL\nPrivate traceback.")
            # Deliberately malformed: runtime data must be excluded before parsing.
            (logs / "run_summary.json").write_text("LOCAL_ONLY_SENTINEL, not JSON")

            builder.ROOT, builder.HERE = root, workspace
            builder.build()

            html = page.read_text()
            payload = re.search(
                r'<script id="document-data" type="application/json">(.*?)</script>',
                html, re.S,
            )[1]
            documents = json.loads(payload)["documents"]
            self.assertEqual(set(documents), {"plan.md", "source.json"})
            self.assertNotIn("LOCAL_ONLY_SENTINEL", html)


if __name__ == "__main__":
    unittest.main()
