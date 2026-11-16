# claude-trading-skills-indicator-parity

Runs every copy of RSI and EMA that live inside `claude-trading-skills` on the
same price series and reports where they disagree — with a witness series and the
trading decision that flips. **Why now:** the upstream repo has grown to ten
indicator copies with no cross-skill contract test, and one of them reports a
flat series as RSI 100 ("overbought").

Upstream: https://github.com/tradermonty/claude-trading-skills

## What upstream is, and what it is missing

`claude-trading-skills` is a bundle of Claude Code skills for equity research and
trading (5,900+ stars). Each skill vendors its own market-math helpers, so RSI and
EMA exist in several mutually inconsistent versions. The project's own issue
[#663](https://github.com/tradermonty/claude-trading-skills/issues/663) (open,
authored against `origin/main` @ `6d98c9e`) states it directly:

> "Technical indicators are copy-pasted across skills, and the copies have already
> drifted. There are three RSI implementations, and they give different answers for
> the same input. There are seven or more EMA variants, which differ in assumed
> price order and in what they do when data is short."

and asks for one of: a shared module, or "a cross-skill contract test. It feeds
identical fixtures to every copy, including NaN, short-history and flat series, and
asserts identical results." The acceptance criteria are still unchecked. No such
harness exists in the repo (`gh search repos "technical indicator parity"` and
`"rsi ema contract test"` return zero repositories).

Source anchors at the audit commit:

- RSI, 1-decimal rounding, no NaN/period guard —
  [`screen_dividend_stocks.py#L276-L317`](https://github.com/tradermonty/claude-trading-skills/blob/6d98c9e/skills/value-dividend-screener/scripts/screen_dividend_stocks.py#L276-L317)
- RSI, 2-decimal rounding, strict finite guard —
  [`screen_dividend_growth_rsi.py#L239-L280`](https://github.com/tradermonty/claude-trading-skills/blob/6d98c9e/skills/dividend-growth-pullback-screener/scripts/screen_dividend_growth_rsi.py#L239-L280)
- RSI over the pandas Series API —
  [`etf_scanner.py#L713-L738`](https://github.com/tradermonty/claude-trading-skills/blob/6d98c9e/skills/theme-detector/scripts/etf_scanner.py#L713-L738)
- EMA, newest-first contract —
  [`market_calculator.py#L130-L158`](https://github.com/tradermonty/claude-trading-skills/blob/6d98c9e/skills/canslim-screener/scripts/calculators/market_calculator.py#L130-L158)

## What this tool does / does not do

**Does:** executes the seven upstream function bodies verbatim (AST-extracted, no
rewrite) on deterministic synthetic fixtures; normalises only the declared calling
convention (`oldest-first` vs `newest-first`, list vs `pandas.Series`, scalar vs
series return); and reports, per check, the values each copy produced, the spread,
errors, and the threshold/decision that changes.

**Does not:** fetch market data, judge whether RSI/EMA are *good* indicators, patch
upstream, or install pandas. `pandas.Series` and `read_price` are replaced by
minimal shims (documented in `indicator_parity.py`); nothing else is stubbed.

## Install / run

Python 3.10+, standard library only, no network.

```bash
git clone git@github-linmoxi33:linmoxi33/claude-trading-skills-indicator-parity.git
cd claude-trading-skills-indicator-parity
python3 bin/indicator-parity            # human table, exit 1 when drift is found
python3 bin/indicator-parity --json     # machine-readable report
```

Run against a real checkout instead of the vendored excerpts:

```bash
python3 bin/indicator-parity --repo /path/to/claude-trading-skills --json
```

Override or extend fixtures (`examples/in/series.json` is the default set):

```bash
python3 bin/indicator-parity --fixtures examples/in/series.json --pretty
```

### `--json` shape (trimmed)

```json
{"schema": "indicator-parity/1", "upstream_commit": "6d98c9e",
 "checks": [{"id": "rsi.rounding_precision", "status": "divergent", "spread": 0.05,
             "values": {"rsi.value_dividend": {"value": 70.0},
                        "rsi.dividend_growth": {"value": 69.95}},
             "impact": {"threshold_flips": [{"threshold": 70.0, "value_a": 69.95, "value_b": 70.0}]}}],
 "summary": {"checks": 7, "divergent": 6, "semantic_defects": 1, "verdict": "drift"}}
```

### Exit codes

| code | meaning |
| --- | --- |
| 0 | all copies agree on every fixture (`verdict: "parity"`) |
| 1 | drift or semantic defect found (`verdict: "drift"`) |
| 2 | usage error, missing checkout, or unreadable fixtures |

## What it actually found (reproduced by `python3 bin/indicator-parity`)

1. **Rounding flips a real trading decision.** On a series whose true Wilder RSI is
   `69.9514`, `value_dividend` returns `70.0` (overbought) while `dividend_growth`
   and `theme_detector` return `69.95` (not overbought).
2. **Flat series: all three report `100.0`.** Zero movement makes `avg_loss == 0`,
   so every copy short-circuits to 100. The copies agree, and the answer is wrong:
   the harness records this as `degenerate_agreement` / `semantic_defect`, not as a
   parity pass.
3. **NaN handling diverges.** `value_dividend` and `dividend_growth` return `None`;
   `theme_detector` drops the missing bar and returns `100.0`, so the gap silently
   becomes a bullish reading.
4. **`period=0`:** `value_dividend` and `theme_detector` raise `ZeroDivisionError`;
   `dividend_growth` returns `None`.
5. **EMA seed rule.** On a gap-open series (`200` then 39 bars near `100`), the
   SMA-seeded copies return `101.2045` and the first-value-seeded momentum copy
   returns `102.5402` (+1.32%).
6. **EMA short data.** Below `period`: `ftd_monitor`/`market_calculator` average
   (`11.06`), `math_helpers` returns `None`, `momentum` returns `10.4533` — a caller
   cannot distinguish a real EMA from a fallback.
7. **Declared-order hazard.** `market_calculator` documents "most recent first" and
   reverses internally; passing the chronological list every other copy accepts
   changes its EMA by `+0.19%` on a 40-bar trend — silent, no error.

## 本轮创新

First executable cross-skill indicator contract harness for this repo: it does not
re-describe issue #663, it *runs* all seven real copies offline and turns the issue's
prose into reproducible numbers, including two findings the issue does not contain —
a `70.0` vs `69.95` overbought-threshold flip at the exact same series, and the fact
that all three RSI copies *agree* on the wrong `100.0` for a flat series (so a
parity-only test would pass it). Previous work in this account audited files,
schemas, and streams; this is the first harness whose subject is numeric agreement
between runtime copies of the same formula.

## 与同类项目的差异

`gh search repos "technical indicator parity"`, `"rsi ema contract test"`, and
`"indicator drift"` return no repositories. `gh search code "calculate_rsi"` returns
only trading bots that implement RSI once. TA-Lib and `pandas-ta` are single
implementations, so they cannot answer "do *these* copies agree?" — which is the
question issue #663 asks. This tool deliberately depends on no indicator library.

## Limits

- Seven variants are pinned to commit `6d98c9e`; upstream may add or move copies.
  `--repo` re-extracts by file+function name, so a moved function fails loudly
  (`exit 2`), never silently.
- The `pandas.Series` shim covers `.diff()`, `.where()`, `.iloc[...].mean()`, `len()`,
  negation and comparisons — exactly what `_calculate_rsi` touches, nothing more.
- Fixtures are synthetic and deterministic; no result here says anything about live
  market behaviour or about indicator quality.
- RSI is checked at `period=14` (and `period=0` as an invalid-input probe); other
  periods are untested.

## Tests

```bash
python3 -m unittest discover -s tests -v   # 18 tests, 0 failures
```

## License

MIT for this harness. The vendored excerpts are MIT, Copyright (c) 2026
TraderMonty; see `LICENSE` and `examples/upstream/VENDOR.md`.
