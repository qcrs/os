# Contest CodeAct Showcase Case Selection

This independent entry is fixed to five registered formal cases. The selection
is based on the current task contracts and the current Transform DSL catalog;
historical CodeAct runs are not treated as current-pass evidence.

| case_id | family | operation | backend | constructive capability evidence |
|---|---|---|---|---|
| `formal-trend-001` | `multi_period_trend_analysis_v1` | `compute_trend` | DSL | registered `trend_series` with controller-owned arguments for one ticker and three periods |
| `formal-trend-005` | `multi_period_trend_analysis_v1` | `compute_trend` | DSL | registered `trend_series` with exact ticker, period, metric, value, and output bindings |
| `formal-join-001` | `cross_table_join_analysis_v1` | `compare_metric` | DSL | registered `compare_metric` for the fixed ACME/BETA and quarter alignment; not arbitrary multi-table join |
| `formal-agg-004` | `conditional_aggregation_v1` | `groupby_aggregate` | bounded Python | requires parsing `MM/DD/YYYY HH:MM` month strings and numeric-string `WINDSPEED` values before grouping |
| `formal-anomaly-001` | `anomaly_detection_v1` | `detect_outliers` | bounded Python | requires inclusive linear-interpolation quartiles; the available nearest-rank DSL produces a different outlier set on this case |

The first three cases have a constructive DSL sequence in the current
`transform_dsl.py` catalog. The last two require semantics not represented by
one faithful DSL pipeline. The showcase therefore performs at most one DSL
repair, then uses an explicitly authorized new `LLM_BOUNDED_PYTHON` attempt
only when `--codeact-fallback on` is selected.
