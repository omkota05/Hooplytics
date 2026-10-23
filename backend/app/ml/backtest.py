"""Backtest reporting helpers."""

from __future__ import annotations

import json

from app.ml.artifacts import bundle_dir


def print_metrics_report(version: str | None = None) -> str:
    root = bundle_dir(version)
    metrics = json.loads((root / "metrics.json").read_text())
    lines = [f"Model version: {root.name}", ""]
    for row in metrics.get("categories", []):
        lines.append(f"## {row['category']}")
        lines.append(
            f"  samples train/val/test: {row['n_train']}/{row['n_val']}/{row['n_test']} "
            f"(test {row['test_start']} .. {row['test_end']})"
        )
        lines.append(f"  baseline MAE={row['mae_baseline']:.3f} RMSE={row['rmse_baseline']:.3f}")
        mae_ml = row.get("mae_ml", row.get("mae_xgb"))
        rmse_ml = row.get("rmse_ml", row.get("rmse_xgb"))
        lines.append(f"  ml       MAE={mae_ml:.3f} RMSE={rmse_ml:.3f}")
        lines.append(f"  selected: {row['selected_model']}")
        if row.get("brier_test_pregame_line") is not None:
            lines.append(
                f"  Brier test (pregame model half-line, normal): {row['brier_test_pregame_line']:.4f}"
            )
        if row.get("brier_test_calibrated") is not None:
            lines.append(f"  Brier test (isotonic calibrated): {row['brier_test_calibrated']:.4f}")
        lines.append("")
    return "\n".join(lines)
