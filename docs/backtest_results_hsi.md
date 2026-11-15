# Backtest: Hang Seng Index book (95 names, index-weighted, HKD 10m)

2020-06-11 to 2026-10-30 (1571 days, 6.28 years), 99% 1-day VaR, 500-day window. 44 late listings use beta x HSI returns before their first real price.

| Model | Exceptions (exp.) | Kupiec p | Christoffersen ind. p | Cond. cov. p | Rolling 250d windows G / Y / R |
|---|---|---|---|---|---|
| historical | 12 (15.7) | 0.326 | 0.002 | 0.006 | 1322 / 0 / 0 |
| normal | 16 (15.7) | 0.942 | 0.009 | 0.033 | 1051 / 271 / 0 |
| t | 10 (15.7) | 0.121 | 0.001 | 0.001 | 1322 / 0 / 0 |
| garch | 12 (15.7) | 0.326 | 0.002 | 0.006 | 1322 / 0 / 0 |
| evt | 12 (15.7) | 0.326 | 0.002 | 0.006 | 1322 / 0 / 0 |
