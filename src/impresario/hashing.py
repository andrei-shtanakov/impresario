"""Canonical document hashing for CAS checks (stale-input detection)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_doc_hash(data: dict[str, Any]) -> str:
    """Hash of the parsed document, independent of YAML formatting/comments.

    Canonical form: JSON with sorted keys, no whitespace, unicode preserved.
    An assessment's input_hash must equal this hash of the Idea it scored;
    a mismatch means the card changed after evaluation (stale input).
    """
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
