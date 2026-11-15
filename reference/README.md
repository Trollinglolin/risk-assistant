# Python vs R validation (Step 8)

Inputs: `input.csv` = the 500-day hypothetical P&L of the current book at the snapshot
`as_of` 2026-10-30 (exported by `scripts/export_reference_input.py`, so both sides use
identical numbers). `exceptions.csv` = the Python historical-VaR backtest exception series.

> **Status:** `validate_reference.R` is an independent R implementation written as a stand-in.
> The RMSC4002 coursework scripts still need to be dropped into this folder and adapted to
> write the same `metric,value` format into `r_results.csv`.

Run: `uv run python scripts/export_reference_input.py && Rscript reference/validate_reference.R && uv run pytest tests/test_matches_r.py`

| Metric (99%, HKD) | R | Python | Gap | Why |
|---|---|---|---|---|
| Historical VaR | 107,763.09 | 107,763.09 | < 1e-8 | `quantile(type=7)` == numpy `linear` |
| Historical ES | 229,023.03 | 229,023.03 | < 1e-8 | same tail set |
| Normal VaR / ES | 133,792.95 / 153,799.65 | same | < 1e-8 | `sd()` == `ddof=1` |
| t (nu=5) VaR / ES | 150,331.01 / 200,064.78 | same | < 1e-8 | closed form |
| Kupiec LR (1493 days, 18 exc.) | 0.59835 | 0.59835 | < 1e-8 | closed form |
| GARCH alpha / beta | 0.0341 / 0.8584 | 0.0335 / 0.8604 | 1.9% / 0.2% | rugarch `hybrid` (solnp) vs arch SLSQP; flat likelihood near optimum |
| GARCH omega / nu | 0.1486 / 8.02 | 0.1468 / 8.11 | 1.2% / 1.1% | same |
| EVT xi / beta | 0.5688 / 16,856 | 0.5685 / 16,859 | 0.06% / 0.02% | both ML, loc fixed at threshold; optimiser tolerance |
| EVT 99% VaR | 120,682.76 | 120,678.13 | 0.004% | follows from xi, beta |
