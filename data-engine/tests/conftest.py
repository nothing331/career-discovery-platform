from dataclasses import replace
from pathlib import Path
import json
import httpx
import pytest
from kb_pipeline.config import Settings
from kb_pipeline.contracts import Target
from kb_pipeline.engine import Engine

HTML = b"""<html><main><h1>Computer Science (B.Sc.)</h1><p>A local synthetic programme for extraction tests; not a real admission fact.</p><table><tr><td>Duration and credits</td><td>6 semesters; 180 ECTS credits</td></tr><tr><td>Language of instruction</td><td>English</td></tr><tr><td>Tuition fees</td><td>Not applicable</td></tr><tr><td>Application deadline</td><td>15 July</td></tr></table><p>Applicants must provide a prior qualification; exceptions need manual checking.</p></main></html>"""


@pytest.fixture
def target():
    return Target(
        id="test-bsc",
        institution="Synthetic University",
        programme="Computer Science B.Sc.",
        level="bachelor",
        url="https://university.example/cs",
        allowed_hosts=["university.example"],
    )


@pytest.fixture
def settings(tmp_path, target):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "country": "DE",
                "subject": "CS",
                "institutions": ["Synthetic University"],
                "targets": [target.model_dump(mode="json")],
            }
        )
    )
    return Settings(data_dir=tmp_path / "data", registry=registry, delay=0, retries=2)


@pytest.fixture
def fetch_client():
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def engine(settings, fetch_client):
    return Engine(settings, fetch_client=fetch_client, sleep=lambda _: None)
