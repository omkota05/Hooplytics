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
def ml_train(
    quick: bool = typer.Option(False, "--quick", help="Smoke test: subsample train rows, 2 candidates, never promoted"),
    no_promote: bool = typer.Option(False, "--no-promote", help="Save artifacts without changing ACTIVE"),
    val_start: str = typer.Option(None, help="Validation start date YYYY-MM-DD"),
    test_start: str = typer.Option(None, help="Test start date YYYY-MM-DD"),
) -> None:
    """Train + evaluate the v2 player-stat engine (offline). Promotes only if acceptance checks pass."""
    from datetime import date

    from app.ml.engine.service import get_engine_service
    from app.ml.engine.training import DEFAULT_TEST_START, DEFAULT_VAL_START, train_engine

    def go():
        with session_scope() as session:
            out = train_engine(
                session,
                val_start=date.fromisoformat(val_start) if val_start else DEFAULT_VAL_START,
                test_start=date.fromisoformat(test_start) if test_start else DEFAULT_TEST_START,
                quick=quick,
                promote_if_valid=not no_promote,
                progress=typer.echo,
            )
        get_engine_service().reset()
        typer.echo(_format_eval(out["manifest"], out["metrics"]))

    _run(go)


def _format_eval(manifest: dict, metrics: dict) -> str:
    sp = manifest["split"]
    lines = [
        f"Model {manifest['version']}  promoted={manifest.get('promoted')}  trained_at={manifest['trained_at']}",
        f"Train {sp['train_dates']}  Val {sp['val_dates']}  Test {sp['test_dates']}  rows {sp['rows']}",
        "",
        f"{'category':12s} {'model MAE':>9s} {'RMSE':>7s} {'best base':>18s} {'L10':>6s} {'season':>7s} {'old v1':>7s} {'Δ vs best':>9s}  selected",
    ]
    for cat, d in metrics["test"].items():
        base = d["baselines"]
        old = d.get("old_model", {}).get("old", {}).get("mae")
        sel = manifest["selected_models"].get(cat, "sum of components")
        lines.append(
            f"{cat:12s} {d['model']['mae']:9.3f} {d['model']['rmse']:7.3f} "
            f"{d['best_baseline'] + ' ' + format(base[d['best_baseline']]['mae'], '.3f'):>18s} "
            f"{base['last_10']['mae']:6.3f} {base['season_avg']['mae']:7.3f} "
            f"{(format(old, '.3f') if old else '-'):>7s} {d['mae_improvement_vs_best_baseline_pct']:8.2f}%  {sel}"
        )
    lines.append("")
    lines.append("Probability status: " + ", ".join(f"{k}={v}" for k, v in manifest["probability_status"].items()))
    lines.append(f"Acceptance checks: {manifest['acceptance_checks']}")
    return "\n".join(lines)


@cli.command("ml-eval")
def ml_eval(version: str = typer.Option(None, help="v2 artifact version (default: ACTIVE)")) -> None:
    """Show held-out evaluation of a saved v2 model (no retraining)."""
    from app.ml.engine.artifacts import load_bundle

    def go():
        b = load_bundle(version)
        typer.echo(_format_eval(b.manifest, b.metrics))
        for cat, d in b.metrics["synthetic_thresholds"].items():
            e, n = d["empirical_joint"], d["normal_legacy"]
            typer.echo(
                f"  {cat:12s} synthetic Brier {e['brier']:.4f} ECE {e['ece']:.4f} (normal: {n['brier']:.4f}/{n['ece']:.4f}) "
                f"80% interval coverage {d['interval_80_coverage']:.3f}"
            )
        rl = b.metrics.get("real_lines", {})
        for cat, d in (rl.get("categories") or {}).items():
            typer.echo(f"  {cat:12s} archived real lines n={d['unique_lines']} Brier {d['model']['brier']:.4f} ECE {d['model']['ece']:.4f}")

    _run(go)


@cli.command("ml-status")
def ml_status() -> None:
    """Active v2 model, rollback target, gates, warnings, and odds archive size."""
    from app.services.ml_engine_service import status

    def go():
        with session_scope() as session:
            typer.echo(status(session).model_dump_json(indent=2, exclude={"data_validation", "probability_gates"}))

    _run(go)


@cli.command("ml-rollback")
def ml_rollback() -> None:
    """Point ACTIVE back at the previously active v2 model."""
    from app.ml.engine.artifacts import rollback

    typer.echo(f"ACTIVE -> {rollback()}")


@cli.command("odds-archive")
def odds_archive(
    backfill: bool = typer.Option(False, "--backfill", help="Archive existing prop_offers rows last seen before tip-off"),
    settle: bool = typer.Option(True, "--settle/--no-settle", help="Settle snapshots for final games"),
) -> None:
    """Maintain the historical sportsbook odds archive (no Unabated API calls)."""
    from app.services.odds_archive_service import archive_status, backfill_last_seen_pregame, settle_snapshots

    def go():
        with session_scope() as session:
            if backfill:
                typer.echo(f"Backfilled {backfill_last_seen_pregame(session)} pregame observations")
            if settle:
                typer.echo(f"Settled: {settle_snapshots(session)}")
            typer.echo(json.dumps(archive_status(session), indent=2, default=str))

    _run(go)


@cli.command("ml-forecast")
def ml_forecast(
    settle_only: bool = typer.Option(False, "--settle-only", help="Only grade finished forecasts"),
    horizon_hours: int = typer.Option(36, help="Record games tipping off within this many hours"),
) -> None:
    """Settle finished forecasts and record pregame forecasts (no training, no Unabated calls)."""
    from app.services.forecast_archive_service import forecast_summary, record_forecasts, settle_forecasts

    def go():
        with session_scope() as session:
            typer.echo(f"Settled: {settle_forecasts(session)}")
        if not settle_only:
            with session_scope() as session:
                typer.echo(f"Recorded: {record_forecasts(session, horizon_hours=horizon_hours)}")
        with session_scope() as session:
            s = forecast_summary(session)
            typer.echo(json.dumps({k: s[k] for k in ("forecasts_recorded", "by_status", "games_forecast", "lines_recorded", "warnings")}, indent=2, default=str))

    _run(go)


@cli.command("ml-train-v1")
def ml_train_v1(version: str = typer.Option(None, help="Optional artifact version label")) -> None:
    """Legacy v1 trainer (kept for rollback/comparison)."""
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
