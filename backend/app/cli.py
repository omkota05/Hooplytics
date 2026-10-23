"""Hooplytics backend command line.

python -m app.cli sync                 # incremental sync of the current season
python -m app.cli backfill             # current + HISTORY_SEASONS previous seasons
python -m app.cli backfill --season 2025 --max-games 200
python -m app.cli backfill --retry-failed   # retry box scores the provider failed to serve
python -m app.cli status
python -m app.cli export-dataset out.parquet
python -m app.cli ml-train
python -m app.cli ml-metrics
python -m app.cli ml-predict --player-id 1 --game-id 2 --stat pts --line 19.5
"""

import json
import logging
from pathlib import Path

import typer
from sqlalchemy.exc import OperationalError

from app.db import DatabaseNotConfiguredError, session_scope
from app.ingestion.http import ProviderError
from app.logging_config import configure_logging
from app.sync.service import SyncAlreadyRunningError

cli = typer.Typer(add_completion=False, no_args_is_help=True)
logger = logging.getLogger("hooplytics.cli")


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _run(fn):
    configure_logging()
    try:
        return fn()
    except DatabaseNotConfiguredError as exc:
        _fail(str(exc))
    except OperationalError as exc:
        _fail(f"Cannot reach PostgreSQL ({exc.orig}). Is it running? Try: make db")
    except SyncAlreadyRunningError as exc:
        _fail(f"{exc}. Wait for it to finish (see `make status`).")
    except ProviderError as exc:
        _fail(f"Data provider error: {exc}")


@cli.command()
def sync() -> None:
    """Incremental sync: new completed games, box scores, schedule, rosters."""
    from app.sync.factory import build_sync_service

    def go():
        service, provider = build_sync_service()
        try:
            run = service.run_incremental()
        finally:
            provider.close()
        typer.echo(
            f"Sync {run.status}: {run.games_updated} games updated, "
            f"{run.boxscores_synced} box scores, {provider.request_count} requests"
        )

    _run(go)


@cli.command()
def backfill(
    season: list[int] = typer.Option(None, "--season", help="Season end year (2025 = 2024-25). Repeatable."),
    max_games: int = typer.Option(None, help="Stop after this many box scores (resumable)."),
    retry_failed: bool = typer.Option(
        False, "--retry-failed", help="Retry box scores that previously failed or gave up."
    ),
) -> None:
    """Download historical schedules and box scores. Safe to interrupt and re-run."""
    from sqlalchemy import update

    from app.models import Game
    from app.sync.factory import build_sync_service

    def go():
        if retry_failed:
            with session_scope() as session:
                reset = session.execute(
                    update(Game)
                    .where(Game.status == "final", Game.boxscore_synced_at.is_(None))
                    .values(boxscore_attempts=0, boxscore_next_attempt_at=None)
                ).rowcount
            typer.echo(f"Reset retry state for {reset} game(s)")
        service, provider = build_sync_service()
        try:
            run = service.run_backfill(seasons=season or None, max_games=max_games)
        finally:
            provider.close()
        typer.echo(
            f"Backfill {run.status}: {run.games_updated} games scheduled, "
            f"{run.boxscores_synced} box scores, {provider.request_count} requests. "
            f"Remaining: {service.pending_backfill_count()}"
        )

    _run(go)


@cli.command()
def status() -> None:
    """Print data freshness and coverage."""
    from app.services.sync_status import get_sync_status

    def go():
        with session_scope() as session:
            typer.echo(json.dumps(get_sync_status(session).model_dump(mode="json"), indent=2))

    _run(go)


@cli.command("export-dataset")
def export_dataset(output: Path = typer.Argument(..., help=".parquet or .csv path")) -> None:
    """Export a leakage-safe player-game feature table for ML experiments."""
    from app.ml.dataset import build_player_game_frame

    def go():
        if output.suffix == ".parquet":
            try:
                import pyarrow  # noqa: F401
            except ImportError:
                _fail("Parquet export needs pyarrow: pip install -r requirements-ml.txt (or use .csv)")
        with session_scope() as session:
            frame = build_player_game_frame(session)
        if output.suffix == ".parquet":
            frame.to_parquet(output, index=False)
        else:
            frame.to_csv(output, index=False)
        typer.echo(f"Wrote {len(frame)} rows to {output}")

    _run(go)


@cli.command("ml-train")
def ml_train(version: str = typer.Option(None, help="Optional artifact version label")) -> None:
    """Train XGBoost player-stat models from synced history."""
    from app.ml.inference import reset_prediction_engine
    from app.ml.training import train_all

    def go():
        with session_scope() as session:
            out = train_all(session, version=version)
        reset_prediction_engine()
        typer.echo(f"Trained models saved to {out}")

    _run(go)


@cli.command("ml-metrics")
def ml_metrics(version: str = typer.Option(None, help="Artifact version (default: active)")) -> None:
    """Print backtest metrics for trained models."""
    from app.ml.backtest import print_metrics_report

    def go():
        typer.echo(print_metrics_report(version))

    _run(go)


@cli.command("ml-train-games")
def ml_train_games(version: str = typer.Option(None, help="Optional artifact version label")) -> None:
    """Train game-winner models from synced game history."""
    from app.ml.game_winner.training import train_game_winner
    from app.services.prediction_service import reload_all_prediction_models

    def go():
        with session_scope() as session:
            out = train_game_winner(session, version=version)
        reload_all_prediction_models()
        typer.echo(f"Game-winner models saved to {out}")

    _run(go)


@cli.command("ml-metrics-games")
def ml_metrics_games(version: str = typer.Option(None, help="Artifact version (default: active)")) -> None:
    """Print held-out metrics for the game-winner model."""
    import json

    from app.ml.game_winner.artifacts import load_game_winner_bundle

    def go():
        bundle = load_game_winner_bundle(version)
        typer.echo(json.dumps(bundle.metrics, indent=2))

    _run(go)


@cli.command("ml-predict-game")
def ml_predict_game(game_id: int = typer.Option(..., "--game-id")) -> None:
    """Predict home-team win probability for one game."""
    from app.services.prediction_service import predict_game_outcome

    def go():
        with session_scope() as session:
            out = predict_game_outcome(session, game_id=game_id)
        typer.echo(out.model_dump_json(indent=2))

    _run(go)


@cli.command("ml-predict")
def ml_predict(
    player_id: int = typer.Option(..., "--player-id"),
    game_id: int = typer.Option(..., "--game-id"),
    stat: str = typer.Option("pts", "--stat"),
    line: float = typer.Option(19.5, "--line"),
) -> None:
    """Generate a prediction for one player/game."""
    from app.services.prediction_service import predict_player_stat

    def go():
        with session_scope() as session:
            out = predict_player_stat(
                session, player_id=player_id, game_id=game_id, category_key=stat, line=line
            )
        typer.echo(out.model_dump_json(indent=2))

    _run(go)


if __name__ == "__main__":
    cli()
