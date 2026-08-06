from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = REPO_ROOT / "data" / "synthetic"


@pytest.fixture(scope="session")
def ground_truth() -> list[dict]:
    path = SYNTHETIC / "ground_truth.json"
    if not path.exists():
        pytest.fail(
            "data/synthetic/ground_truth.json is missing — "
            "run `python scripts/generate_leases.py` first."
        )
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    return SYNTHETIC


def iter_documents():
    """(lease, document) pairs for parametrization, read at collection time."""
    path = SYNTHETIC / "ground_truth.json"
    if not path.exists():
        return []
    return [(lease, doc) for lease in json.loads(path.read_text()) for doc in lease["documents"]]
