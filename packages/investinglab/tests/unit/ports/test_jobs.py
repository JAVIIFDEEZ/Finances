"""The rules of a background job, whatever store keeps it (SYNTHETIC values)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investinglab.domain.errors import DomainError
from investinglab.ports import (
    Job,
    JobError,
    JobStatus,
    canonical_json,
    check_submission,
    job_outcome,
)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _job(**changes: object) -> Job:
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": "owner",
        "kind": "simulation",
        "status": JobStatus.QUEUED,
        "parameters": {"n_paths": 500},
        "created_at": NOW,
    }
    values.update(changes)
    return Job(**values)  # type: ignore[arg-type]


def test_only_the_last_three_states_are_finished() -> None:
    assert [status for status in JobStatus if status.finished] == [
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ]


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"kind": ""}, "kind"),
        ({"progress": 1.5}, "progress"),
        ({"progress": float("nan")}, "progress"),
        ({"status": JobStatus.SUCCEEDED, "finished_at": NOW}, "result exactly when"),
        ({"result": {"early": True}}, "result exactly when"),
        (
            {"status": JobStatus.FAILED, "finished_at": NOW},
            "error exactly when",
        ),
        ({"status": JobStatus.CANCELLED}, "finishing instant"),
        ({"finished_at": NOW}, "finishing instant"),
        ({"attempts": -1}, "negative"),
    ],
    ids=[
        "kind",
        "progress",
        "nan-progress",
        "no-result",
        "early-result",
        "no-error",
        "no-finish",
        "early-finish",
        "attempts",
    ],
)
def test_a_job_that_breaks_its_life_rules_cannot_exist(
    changes: dict[str, object], problem: str
) -> None:
    with pytest.raises(DomainError, match=problem):
        _job(**changes)


def test_an_error_needs_a_code_and_a_title() -> None:
    with pytest.raises(DomainError, match="code and a title"):
        JobError("", "Failed", "detail")


def test_a_submission_must_be_plain_json_of_a_known_size() -> None:
    check_submission("simulation", {"nested": [1, 2.5, "ñ", None, {"ok": True}]})
    with pytest.raises(DomainError, match="kind"):
        check_submission("", {})
    with pytest.raises(DomainError, match="plain JSON"):
        check_submission("simulation", {"value": float("inf")})


def test_the_audit_keeps_the_outcome_and_a_digest_of_the_result() -> None:
    result = {"paths": [1.0, 2.0]}
    done = _job(status=JobStatus.SUCCEEDED, result=result, finished_at=NOW)
    failed = _job(
        status=JobStatus.FAILED,
        error=JobError("data-not-found", "Data not found", "NOPE"),
        finished_at=NOW,
    )

    outcome = job_outcome(done)

    expected = hashlib.sha256(canonical_json({"result": result}).encode()).hexdigest()
    assert outcome == {
        "id": str(done.id),
        "kind": "simulation",
        "status": "succeeded",
        "result_sha256": expected,
    }
    assert job_outcome(failed)["error"] == "data-not-found"
    assert "result_sha256" not in job_outcome(failed)
