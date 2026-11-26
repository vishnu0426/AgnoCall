"""
Test fixtures.

Pure-logic tests (test_form_eval.py) need nothing. The integration tests
(test_form_eval_stage.py, test_form_eval_graphql.py) run the real pipeline
stage / GraphQL resolvers against an in-memory SQLite database, so they need
no Postgres, Redis, MinIO or LLM. SQLite can't compile Postgres' UUID/JSONB,
so those are mapped to CHAR/JSON for the test engine only.
"""
import os

# Must be set before app.core.config is first imported anywhere.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ALLOW_INSECURE_DEFAULTS", "true")   # tests use the default signing secret

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    pytest.importorskip("celery")
    from app.core.database import Base
    from app.models import models  # noqa: F401  (registers tables)

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """The settings-override cache is per process; each test has its own database."""
    from app.core import settings_store
    settings_store.invalidate()
    yield
    settings_store.invalidate()
