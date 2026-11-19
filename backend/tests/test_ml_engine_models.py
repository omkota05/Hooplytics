
import numpy as np
import pytest

from app.ml.engine import artifacts as art
from app.ml.engine.data import TARGETS, validate_and_clean
from app.ml.engine.distribution import JointResidualDistribution, normal_over_probability
from app.ml.engine.evaluation import prob_metrics, regression_metrics, vectorized_category_probs
from app.ml.engine.features import build_features
from app.ml.engine.models import BaselineModel, CandidateSpec, ComponentModel, baseline_predict
from app.ml.engine.training import _probability_gates, split_by_date
from tests.ml_engine_factory import make_raw


@pytest.fixture(scope="module")
def frame():
    clean, _ = validate_and_clean(make_raw())
    f = build_features(clean)
    return f[f["usable_target"] & (f["appearances"] >= 1)].copy()


@pytest.fixture(scope="module")
def dist():
    rng = np.random.default_rng(1)
    pred = np.column_stack([rng.uniform(5, 30, 3000), rng.uniform(2, 10, 3000), rng.uniform(1, 8, 3000), rng.uniform(0, 3, 3000)])
    shared = rng.normal(0, 1, 3000)
    actual = np.clip(np.rint(pred + np.column_stack([4 * shared + rng.normal(0, 4, 3000), 1.5 * shared + rng.normal(0, 2, 3000), rng.normal(0, 1.5, 3000), rng.normal(0, 1, 3000)])), 0, None)
    return JointResidualDistribution.fit(pred, actual)


def test_chronological_split_keeps_games_together(frame):
    dates = sorted(frame["game_date"].dt.date.unique())
    tr, va, te = split_by_date(frame, dates[len(dates) // 2], dates[3 * len(dates) // 4])
    assert tr["start_time"].max() < va["start_time"].min() < te["start_time"].min()
    assert not (set(tr["game_id"]) & set(va["game_id"])) and not (set(va["game_id"]) & set(te["game_id"]))
    assert len(tr) + len(va) + len(te) == len(frame)


@pytest.mark.parametrize("kind,loss", [("hgb", "poisson"), ("ridge", None), ("two_stage", "poisson")])
def test_models_are_reproducible_nonnegative_and_order_independent(frame, kind, loss):
    params = {"alpha": 10.0} if kind == "ridge" else {"loss": loss}
    spec = CandidateSpec("t", kind, "core" if kind == "ridge" else "full", params)
    y = frame["target_pts"].to_numpy()
    mins = frame["target_minutes"].to_numpy()
    a = ComponentModel(spec, "pts").fit(frame, y, minutes=mins).predict(frame)
    m2 = ComponentModel(spec, "pts").fit(frame, y, minutes=mins)
    b = m2.predict(frame)
    np.testing.assert_allclose(a, b)
    assert (a >= 0).all() and np.isfinite(a).all()
    shuffled_cols = frame[list(reversed(frame.columns))]
    np.testing.assert_allclose(m2.predict(shuffled_cols), b)


def test_missing_features_do_not_crash_and_baselines_fall_back(frame):
    sparse = frame.copy()
    sparse["pts_season"] = np.nan
    sparse["pts_l5"] = np.nan
    pred = baseline_predict(sparse, "pts", "weighted")
    assert np.isfinite(pred[sparse["pts_l10"].notna()]).all()
    m = ComponentModel(CandidateSpec("t", "hgb", "full", {"loss": "squared_error"}), "pts").fit(frame, frame["target_pts"].to_numpy())
    assert np.isfinite(m.predict(sparse.drop(columns=["fga_share_l10"]))).all()
    assert (BaselineModel("pts", "last_10").predict(sparse) >= 0).all()


def test_regression_metrics():
    m = regression_metrics(np.array([10.0, 20.0]), np.array([12.0, 18.0]))
    assert m["mae"] == 2 and m["rmse"] == 2 and m["bias"] == 0


def test_combined_samples_are_sum_of_component_samples(dist):
    means = np.array([24.0, 7.0, 5.0, 2.0])
    comp = dist.samples(means)
    pra = dist.category_samples(means, "pts_reb_ast")
    np.testing.assert_allclose(pra, comp[:, 0] + comp[:, 1] + comp[:, 2])
    assert (comp >= 0).all() and np.all(comp == np.rint(comp))
    # Dependence preserved: pts/reb residual correlation survives in simulated outcomes.
    assert np.corrcoef(comp[:, 0], comp[:, 1])[0, 1] > 0.1
    var_sum = comp[:, 0].var() + comp[:, 1].var() + comp[:, 2].var()
    assert pra.var() > var_sum  # positive covariance widens PRA vs an independence assumption


def test_half_line_has_no_push_and_integer_line_can_push(dist):
    s = dist.category_samples(np.array([20.0, 6.0, 4.0, 1.0]), "pts")
    half = JointResidualDistribution.line_probabilities(s, 19.5)
    assert half.p_push == 0
    assert half.p_over + half.p_under + half.p_push == pytest.approx(1.0)
    whole = JointResidualDistribution.line_probabilities(s, 20.0)
    assert whole.p_push > 0
    assert whole.p_over + whole.p_under + whole.p_push == pytest.approx(1.0)


def test_extreme_lines_never_yield_exact_zero_or_one(dist):
    s = dist.category_samples(np.array([20.0, 6.0, 4.0, 1.0]), "pts")
    lo = JointResidualDistribution.line_probabilities(s, 0.5)
    hi = JointResidualDistribution.line_probabilities(s, 120.5)
    assert 0 < hi.p_over < 0.01 and 0.99 < lo.p_over < 1


def test_vectorized_probs_match_single_row(dist):
    means = np.array([[20.0, 6.0, 4.0, 1.0], [8.0, 3.0, 2.0, 0.5]])
    lines = np.array([19.5, 12.5])
    po, pu, pp, q10, q90 = vectorized_category_probs(dist, means, "pts_reb", lines)
    for i in range(2):
        s = dist.category_samples(means[i], "pts_reb")
        lp = JointResidualDistribution.line_probabilities(s, lines[i])
        assert po[i] == pytest.approx(lp.p_over) and pu[i] == pytest.approx(lp.p_under)
        assert q10[i] <= np.median(s) <= q90[i]


def test_interval_and_calibration_metrics(dist):
    rng = np.random.default_rng(3)
    p = rng.uniform(0.2, 0.8, 5000)
    y = (rng.uniform(size=5000) < p).astype(float)
    m = prob_metrics(p, y)
    assert m["ece"] < 0.03 and 0.15 < m["brier"] < 0.25
    bad = prob_metrics(np.clip(p * 1.5, 0, 1), y)
    assert bad["ece"] > m["ece"]
    assert normal_over_probability(20, 5, 19.5) > 0.5


def test_probability_gates_require_evidence():
    synth = {c: {"empirical_joint": {"ece": 0.02, "brier": 0.22}, "climatology_constant": {"brier": 0.24}} for c in ("pts", "reb", "ast", "fg3m", "pts_reb", "pts_ast", "reb_ast", "pts_reb_ast")}
    synth["fg3m"]["empirical_joint"]["ece"] = 0.08
    status, _ = _probability_gates(synth, {"available": False})
    assert status["pts"] == "experimental" and status["fg3m"] == "unavailable"
    real = {"categories": {"pts": {"unique_lines": 500, "model": {"ece": 0.02, "brier": 0.23}, "constant_half": {"brier": 0.25}},
                           "reb": {"unique_lines": 50, "model": {"ece": 0.01, "brier": 0.2}, "constant_half": {"brier": 0.25}}}}
    status, _ = _probability_gates(synth, real)
    assert status["pts"] == "validated_real_lines"
    assert status["reb"] == "experimental"  # too few real lines


def test_artifact_roundtrip_and_incompatibility(tmp_path, monkeypatch, frame, dist):
    monkeypatch.setattr(art, "ROOT", tmp_path)
    monkeypatch.setattr(art, "ACTIVE", tmp_path / "ACTIVE")
    monkeypatch.setattr(art, "PREVIOUS", tmp_path / "PREVIOUS")
    models = {s: BaselineModel(s, "last_10") for s in TARGETS}
    mins = ComponentModel(CandidateSpec("m", "ridge", "core", {"alpha": 1.0}), "minutes").fit(frame, frame["target_minutes"].to_numpy())
    from app.ml.engine.features import FEATURE_VERSION

    manifest = {"schema_version": art.SCHEMA_VERSION, "feature_version": FEATURE_VERSION, "library_versions": art.library_versions(), "trained_at": "x"}
    art.save_bundle(tmp_path / "v_a", manifest=manifest, metrics={}, models=models, minutes_model=mins, distribution=dist)
    b = art.load_bundle("v_a")
    np.testing.assert_allclose(b.distribution.residuals[0], dist.residuals[0])
    art.promote("v_a")
    art.save_bundle(tmp_path / "v_b", manifest=manifest, metrics={}, models=models, minutes_model=mins, distribution=dist)
    art.promote("v_b")
    assert art.active_version() == "v_b" and art.previous_version() == "v_a"
    assert art.rollback() == "v_a"
    bad = {**manifest, "feature_version": "old"}
    art.save_bundle(tmp_path / "v_bad", manifest=bad, metrics={}, models=models, minutes_model=mins, distribution=dist)
    with pytest.raises(art.EngineArtifactsIncompatibleError):
        art.load_bundle("v_bad")
    with pytest.raises(art.EngineArtifactsMissingError):
        art.load_bundle("does_not_exist")
