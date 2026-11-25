"""
Run independent read queries at the same time.

When the database is a network hop away every statement costs a full round trip (~35 ms here), and a
page that needs 8 independent answers used to pay for them one after another. Each task gets its own
read-only session (a session is not thread-safe) from the shared connection pool, so the page costs
about as much as its slowest query instead of the sum.

Only used for PostgreSQL; with anything else (SQLite in tests) the tasks simply run in order, so
behaviour and results are identical.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Sequence, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")

_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="read-query")


def run_parallel(db: Session, tasks: Sequence[Callable[[Session], T]]) -> List[T]:
    """Run each task(session) and return the results in the same order. A task that raises re-raises here."""
    bind = db.get_bind()
    if len(tasks) < 2 or bind.dialect.name != "postgresql":
        return [task(db) for task in tasks]

    def _run(task: Callable[[Session], T]) -> T:
        session = Session(bind=bind, autoflush=False)
        try:
            return task(session)
        finally:
            session.close()

    futures = [_executor.submit(_run, task) for task in tasks]
    return [f.result() for f in futures]
