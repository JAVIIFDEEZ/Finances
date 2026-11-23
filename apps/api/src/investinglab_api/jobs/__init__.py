"""Background jobs: the kinds the workers run and how they run them (ADR-0046).

The API submits jobs through the :class:`~investinglab.ports.JobRepository`; a worker
(``investinglab-api worker``) takes them from the queue and runs them with
:func:`~investinglab_api.jobs.runner.run_job`.
"""

from investinglab_api.jobs.kinds import HANDLERS, SIMULATION, Stage
from investinglab_api.jobs.runner import (
    FLUSH_SECONDS,
    MAX_ATTEMPTS,
    Handler,
    JobCancelledError,
    JobContext,
    Progress,
    job_error,
    run_job,
)

__all__ = [
    "FLUSH_SECONDS",
    "HANDLERS",
    "MAX_ATTEMPTS",
    "SIMULATION",
    "Handler",
    "JobCancelledError",
    "JobContext",
    "Progress",
    "Stage",
    "job_error",
    "run_job",
]
