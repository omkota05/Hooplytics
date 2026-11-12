import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.analytics.categories import UnknownCategoryError
from app.analytics.lines import InvalidLineError
from app.analytics.windows import InvalidWindowError
from app.api.routes import games, hit_streaks, parlay_builder, players, predictions, prop_finder, recommendations, stats, sync
from app.config import get_settings
from app.db import DatabaseNotConfiguredError, get_engine
from app.logging_config import configure_logging
from app.services.errors import BadRequestError, NotFoundError
from app.services.prediction_service import ModelNotReadyError
from app.sync.odds_scheduler import OddsImportScheduler
from app.sync.scheduler import SyncScheduler

logger = logging.getLogger("hooplytics")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1 FROM alembic_version"))
    except DatabaseNotConfiguredError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Database not ready. Start PostgreSQL (`make db`) and run migrations "
            f"(`make migrate`). Underlying error: {exc}"
        ) from exc

    try:
        from app.db import session_scope
        from app.services.prop_offer_maintenance import deactivate_past_game_offers

        with session_scope() as session:
            n = deactivate_past_game_offers(session)
            if n:
                logger.info("Deactivated %s past-game prop offers on startup", n)
    except Exception:
        logger.exception("Prop offer startup maintenance failed (non-fatal)")

    scheduler = SyncScheduler(settings)
    app.state.scheduler = scheduler
    scheduler.start()
    odds_scheduler = OddsImportScheduler(settings)
    app.state.odds_scheduler = odds_scheduler
    odds_scheduler.start()
    yield
    scheduler.stop()
    odds_scheduler.stop()


app = FastAPI(title="Hooplytics API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(NotFoundError)
async def not_found(_: Request, exc: NotFoundError):
    return _error(404, str(exc))


@app.exception_handler(UnknownCategoryError)
@app.exception_handler(InvalidWindowError)
@app.exception_handler(InvalidLineError)
@app.exception_handler(BadRequestError)
async def bad_request(_: Request, exc: Exception):
    return _error(400, str(exc))


@app.exception_handler(ModelNotReadyError)
async def model_not_ready(_: Request, exc: ModelNotReadyError):
    return _error(503, str(exc))


@app.exception_handler(OperationalError)
async def db_unavailable(_: Request, exc: OperationalError):
    logger.error("Database error: %s", exc.orig)
    return _error(503, "Database unavailable. Is PostgreSQL running? (make db)")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


for router in (
    players.router,
    games.router,
    stats.router,
    sync.router,
    predictions.router,
    recommendations.router,
    prop_finder.router,
    hit_streaks.router,
    parlay_builder.router,
):
    app.include_router(router, prefix="/api")
