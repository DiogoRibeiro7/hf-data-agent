"""Nightly rebuild of the agent's knowledge base.

This is the diagram's "pre-processed offline" arrow made concrete: the vector
store is rebuilt on a schedule, and the request path only ever reads it.

Copy this file into your Airflow `dags/` folder. The workers need the package
installed (`pip install hf-data-agent`, plus any connector extras) and the same
`DA_*` environment the agent uses — the store path or Qdrant URL in particular
must be the one the API reads, or this will diligently rebuild a store nobody
queries.

**Not run against a real Airflow instance.** The scheduling and operator wiring
follow the documented API, and the work it performs is the same
`data_agent.entrypoints.ingest.main` covered by the test suite, but no
scheduler has parsed this file. Its own tests are static (see
tests/test_airflow_dag.py).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator

#: Where the filesystem source reads from, on the worker.
INGEST_ROOT = os.environ.get("DA_INGEST_ROOT", "data/seed")
#: Extra ingest flags, space separated — for example "--notion --slack".
INGEST_FLAGS = os.environ.get("DA_INGEST_FLAGS", "").split()

DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


def rebuild_knowledge_base(**_: object) -> int:
    """Rebuild the vector store, failing the task if ingestion reports an error.

    The agent is imported *inside* the task rather than at module scope. DAG
    files are re-parsed by the scheduler constantly, and importing the whole
    agent there would tax every parse for something only the worker needs.
    """
    from data_agent.entrypoints.ingest import run_or_raise

    # run_or_raise turns a non-zero exit into an exception, which is how a
    # scheduler learns the task failed. Returning quietly would leave a stale
    # knowledge base behind a green DAG run — the worst of both.
    run_or_raise([INGEST_ROOT, *INGEST_FLAGS])
    return 0


with DAG(
    dag_id="data_agent_ingest",
    description="Rebuild the hf-data-agent knowledge base from its sources",
    default_args=DEFAULT_ARGS,
    # 03:00 UTC: after daily_revenue lands at 02:00, so a rebuild triggered by
    # new warehouse documentation sees the current state.
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    # Ingestion always rebuilds from the sources as they are *now*, so replaying
    # missed intervals would run the identical job N times to the same effect.
    catchup=False,
    # Two concurrent rebuilds would race on the same store: one clears it while
    # the other is writing, and the result is a partial knowledge base.
    max_active_runs=1,
    tags=["hf-data-agent", "rag"],
) as dag:
    PythonOperator(
        task_id="rebuild_knowledge_base",
        python_callable=rebuild_knowledge_base,
    )
