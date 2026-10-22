from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from app.config import BACKEND_DIR, get_settings
from app.db import make_engine

TABLES = "player_team_seasons, player_game_stats, games, players, teams, sync_runs, sync_state"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping database tests")
    if url == get_settings().database_url:
        pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL (tests truncate tables)")
    engine = make_engine(url)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.skip(f"Test database unreachable ({exc.orig}); start it with `make db`")

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s
