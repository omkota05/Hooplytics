# ML v2 validation — checkpoint

**Completed 2026-11-18 15:15 PT.** The final report is `ML_V2_RESUME_METRICS.md`. Machine-readable results are in
`artifacts/ml/research/{research_results,benchmark_results,resume_metrics}.json`.

All benchmark sections, the full research run (B=2000, including the model-vs-market bootstrap and pooled
walk-forward variants), the full test suites and the production build were run.

Only ongoing work remains:
- Settle the 484 pending prospective forecasts after games finish (`make ml-forecast`).
- Feature version 2.2 (playoff season-progress fix), validated with `scripts/ml_research.py` before any promotion.
