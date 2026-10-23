import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from app.ml.artifacts import load_bundle
from app.ml.features import enrich_player_game_frame
from app.ml.inference import PredictionEngine
from app.ml.training import train_all
from tests.test_ml_features import _row


def test_train_save_load_roundtrip(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("app.ml.training.ARTIFACTS_ROOT", tmp_path)
    monkeypatch.setattr("app.ml.artifacts.ARTIFACTS_ROOT", tmp_path)
    monkeypatch.setattr("app.ml.artifacts.ACTIVE_VERSION_FILE", tmp_path / "active_version.txt")

    rows = []
    start = date(2099, 1, 1)
    for offset in range(320):
        day = start + timedelta(days=offset)
        for player in (1, 2, 3):
            rows.append(
                {
                    **_row(player, 1, 10 + offset % 5 + player, opp=2 + player % 2),
                    "game_date": day,
                    "start_time": datetime(2099, 1, 1, tzinfo=UTC) + timedelta(days=offset),
                    "game_id": 5000 + offset * 10 + player,
                }
            )
    # duplicate game ids per team - use unique game ids
    frame = pd.DataFrame(rows)
    frame["game_id"] = range(5000, 5000 + len(frame))
    enriched = enrich_player_game_frame(frame)
    assert len(enriched) >= 40

    class FakeSession:
        pass

    # Patch build_training_frame to return synthetic enriched data
    monkeypatch.setattr(
        "app.ml.training.build_training_frame",
        lambda _session: enriched,
    )
    out = train_all(FakeSession(), version="test_v1")
    bundle = load_bundle("test_v1")
    assert bundle.version == "test_v1"
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["categories"]

    row = enriched.iloc[-1:]
    engine = PredictionEngine(bundle)
    proj = engine.project_row(
        row, "pts_reb_ast", player_id=int(row["player_id"].iloc[0]), game_id=int(row["game_id"].iloc[0])
    )
    assert proj.mean > 0
    lp = engine.line_probability_row(
        row, "pts_reb_ast", 25.5, player_id=int(row["player_id"].iloc[0]), game_id=int(row["game_id"].iloc[0])
    )
    assert lp.p_over is not None
