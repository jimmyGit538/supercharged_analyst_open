"""Shared fixtures for the extractor unit tests.

The extractors live in `01_extraction/<source>/main.py`. That directory name
is not an importable package (it starts with a digit, and there is no
__init__.py by design — each source is a self-contained Docker build context),
so tests load each `main.py` by path.

Nothing here touches the network or BigQuery. Tests patch `_request`,
`requests.get`, `time.sleep` and the BigQuery helpers on the loaded module.

The tests must also not depend on the developer's `.env`: every extractor calls
`load_dotenv()` at import, so this file disables it and clears the pipeline
variables before any extractor is loaded. Configuration a test needs is set
explicitly on the module by the `fake_bigquery` fixture.
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import dotenv
import pytest

dotenv.load_dotenv = lambda *args, **kwargs: False  # never read a developer's .env
for _var in ("BQ_PROJECT", "BQ_PROJECT_EXTRACTION", "BQ_DATASET_EXTRACTION", "FRED_API_KEY"):
    os.environ.pop(_var, None)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTION_DIR = REPO_ROOT / "01_extraction"


def load_extractor(source: str) -> ModuleType:
    """Import `01_extraction/<source>/main.py` as a module named `extractor_<source>`."""
    path = EXTRACTION_DIR / source / "main.py"
    name = f"extractor_{source}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    """Minimal stand-in for `requests.Response`."""

    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def no_sleep(monkeypatch):
    """Make `time.sleep` a no-op on any module the test loads, and record calls."""
    calls: list[float] = []

    def patch(module: ModuleType) -> list[float]:
        monkeypatch.setattr(module.time, "sleep", lambda s: calls.append(s))
        return calls

    return patch


@pytest.fixture
def fake_bigquery(monkeypatch):
    """Replace the BigQuery side of a loaded extractor with in-memory stand-ins.

    Also supplies the configuration `validate_environment()` requires — a
    project id and any `*_API_KEY` constant — so `main()` can run with no
    environment at all.

    Returns a dict the test can inspect: `appended` holds every row passed to
    `append_rows`, and `watermarks` is what `load_watermarks` will return.
    """
    state = {"appended": [], "watermarks": {}}

    def patch(module: ModuleType, watermarks: dict | None = None) -> dict:
        state["watermarks"] = watermarks or {}
        monkeypatch.setattr(module, "BQ_PROJECT", "test-project")
        for name in dir(module):
            if name.endswith("_API_KEY"):
                monkeypatch.setattr(module, name, "test-key")
        monkeypatch.setattr(module.bigquery, "Client", lambda project=None: object())
        monkeypatch.setattr(module, "ensure_table", lambda client: None)
        monkeypatch.setattr(module, "load_watermarks", lambda client: dict(state["watermarks"]))
        monkeypatch.setattr(
            module, "append_rows", lambda client, rows: state["appended"].extend(rows)
        )
        return state

    return patch
