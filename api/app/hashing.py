"""Hashes deterministas de criterios y evidencia.

Los dos hashes acaban anclados on-chain, asi que la serializacion es fija:
claves ordenadas, sin espacios y sin escapar no-ASCII. El mismo estado tecnico
tiene que producir siempre el mismo digest, hoy y dentro de un ano.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any, Protocol

from app.schemas import PullRequestVerificationResult

EVIDENCE_SCHEMA = "mergepay-evidence-v1"

HASH_HEX_LENGTH = 64

HEX_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


class CriterionLike(Protocol):
    """Lo unico que necesita un criterio para entrar en el hash."""

    description: str
    required: bool


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_hex(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_criteria_hash(criteria: Sequence[CriterionLike]) -> str:
    """Digest de los criterios y su orden, nada mas.

    Deja fuera ids, timestamps, titulo y repo: dos bounties con los mismos
    criterios en el mismo orden comparten hash a proposito.
    """
    payload = [
        {
            "position": position,
            "description": criterion.description,
            "required": criterion.required,
        }
        for position, criterion in enumerate(criteria)
    ]

    return _sha256_hex(payload)


def compute_evidence_hash(
    *,
    bounty_id: int,
    repo_owner: str,
    repo_name: str,
    base_branch: str,
    base_sha: str,
    criteria_hash: str,
    developer_github: str,
    pull_request_number: int,
    pull_request_url: str,
    verification: PullRequestVerificationResult,
) -> str:
    """Digest del estado tecnico que justifica un payout.

    Sin el id de la Verification, sin timestamps y sin el hash de la
    transaccion: reverificar el mismo commit reproduce el mismo digest.
    """
    if not HEX_HASH_PATTERN.fullmatch(criteria_hash):
        raise ValueError(
            "criteria_hash must be 64 hex characters representing 32 bytes"
        )

    payload = {
        "schema": EVIDENCE_SCHEMA,
        "bounty_id": bounty_id,
        "repository": f"{repo_owner}/{repo_name}",
        "base_branch": base_branch,
        "base_sha": base_sha,
        "criteria_hash": criteria_hash.lower(),
        "developer_github": developer_github,
        "pull_request_number": pull_request_number,
        "pull_request_url": pull_request_url,
        "verification": verification.model_dump(mode="json"),
    }

    return _sha256_hex(payload)
