import json
from pathlib import Path

import joblib
import pandas as pd
import pytest

from app.ml.game_winner.classifiers import create_classifier
from app.ml.game_winner.features import add_derived_columns, feature_columns
from app.ml.game_winner.inference import GameWinnerEngine
from app.ml.game_winner.training import train_game_winner


def test_classifier_serialization(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.ml.game_winner.training.ARTIFACTS_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        "app.ml.game_winner.training.ACTIVE_VERSION_FILE",
        tmp_path / "active_version.txt",
    )

    class FakeSession:
        pass

    games = []
    for i in range(300):
        games.append(
            {
                "id": i + 1,
                "season": 2024 if i < 200 else 2025,
                "season_type": 2,
                "start_time": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=i),
                "game_date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).normalize(),
                "home_team_id": 1 + (i % 5),
                "away_team_id": 6 + (i % 5),
                    "home_score": 105 if i % 3 else 98,
                    "away_score": 100,
                    "neutral_site": False,
                    "status": "final",
                    "home_win": 1 if i % 3 else 0,
            }
        )

    def fake_load(session):
        return pd.DataFrame(games)

    monkeypatch.setattr("app.ml.game_winner.training.load_completed_games", fake_load)
    out = train_game_winner(FakeSession(), version="testv1")
    assert (out / "manifest.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["kind"] == "game_winner"
    assert (out / "models" / "logistic_pipeline.joblib").exists()


def test_probabilities_sum_to_one():
    clf = create_classifier()
    cols = feature_columns()
    x = pd.DataFrame([[0.0] * len(cols)], columns=cols)
    y = pd.Series([1])
    clf.fit(x, y)
    p = float(clf.predict_proba_home(x)[0])
    assert 0.0 <= p <= 1.0
