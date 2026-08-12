"""Shared paths and helpers for validator tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from impresario.schemas import load_validators

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EXAMPLE_BUNDLE = CONTRACTS_DIR / "examples" / "pp-001"


@pytest.fixture(scope="session")
def validators():
    """Contract validators loaded once per session."""
    return load_validators(CONTRACTS_DIR)
