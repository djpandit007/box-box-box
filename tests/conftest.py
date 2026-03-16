import json
import pathlib

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_dir():
    """Return the first available session fixture directory."""
    dirs = sorted(d for d in FIXTURES_DIR.iterdir() if d.is_dir())
    assert dirs, "No fixtures found. Run: uv run python scripts/snapshot_session.py"
    return dirs[0]


@pytest.fixture
def load_fixture(fixture_dir):
    """Return a function that loads a named fixture JSON file."""

    def _load(name: str) -> list[dict]:
        return json.loads((fixture_dir / f"{name}.json").read_text())

    return _load
