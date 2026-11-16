# Vendored upstream excerpts

Every file in this directory is a **verbatim** function body copied out of
`tradermonty/claude-trading-skills` at commit `6d98c9e` (the audit baseline named
in upstream issue #663). They exist so the parity harness can run offline with no
network, no `pip install`, and no pandas.

| file | upstream path | upstream lines (at 6d98c9e) |
| --- | --- | --- |
| `screen_dividend_stocks.py` | `skills/value-dividend-screener/scripts/screen_dividend_stocks.py` | 276-317 |
| `screen_dividend_growth_rsi.py` | `skills/dividend-growth-pullback-screener/scripts/screen_dividend_growth_rsi.py` | 239-280 |
| `screen_dividend_growth_rsi__finite_number.py` | same file | module-level helper |
| `etf_scanner.py` | `skills/theme-detector/scripts/etf_scanner.py` | 713-738 |
| `post_ftd_monitor.py` | `skills/ftd-detector/scripts/post_ftd_monitor.py` | 565-575 |
| `math_helpers.py` | `skills/parabolic-short-trade-planner/scripts/math_helpers.py` | 31-48 |
| `market_calculator.py` | `skills/canslim-screener/scripts/calculators/market_calculator.py` | 130-158 |
| `momentum_calculator.py` | `skills/uptrend-analyzer/scripts/calculators/momentum_calculator.py` | 89-109 |

Upstream is MIT licensed, Copyright (c) 2026 TraderMonty. The license text is
reproduced in `../../LICENSE` under "Upstream notice". Nothing here is modified:
only surrounding module code, imports, and the `read_price`/`pandas` surface used
by these functions are stubbed by the harness.
