import json
import pathlib

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_dir():
    """Return the first available session fixture directory."""
    # Prefer full snapshots (numeric session dirs), fall back to ci/
    dirs = sorted(
        (d for d in FIXTURES_DIR.iterdir() if d.is_dir() and d.name != "ci"),
        reverse=True,
    )
    if dirs:
        return dirs[0]
    ci_dir = FIXTURES_DIR / "ci"
    if ci_dir.is_dir():
        return ci_dir
    pytest.skip("No fixtures found — run: uv run python scripts/snapshot_session.py")


@pytest.fixture
def load_fixture(fixture_dir):
    """Return a function that loads a named fixture JSON file."""

    def _load(name: str) -> list[dict]:
        return json.loads((fixture_dir / f"{name}.json").read_text())

    return _load
