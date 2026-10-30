# Probability calibration readiness

Hooplytics does **not** store a timestamped archive of historical pregame sportsbook lines with settled results per import snapshot. Current `prop_line_hit_cache` rows evaluate **today's posted line** against **past NBA box scores**, which is appropriate for descriptive consistency ranking but **not** valid training data for Beta calibration of true pregame hit probabilities.

Therefore:

- `enable_probability_calibration` defaults to **false** in `app/config.py`.
- No Beta `logit(p) = c + a ln(s) - b ln(1-s)` coefficients are loaded in production.
- HCS and PCS are labeled as descriptive indexes, not win probabilities.
- EV, fair odds, and joint parlay probability remain unavailable in the UI.

To enable calibration in the future you would need a reproducible dataset of `(player, category, side, line, sportsbook, pregame_timestamp, outcome)` from archived odds, chronological train/val/test splits, and out-of-sample Brier/log-loss gates before any feature flag change.
