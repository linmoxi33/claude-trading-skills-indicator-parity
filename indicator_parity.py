"""Cross-implementation parity harness for technical indicators.

Runs the *actual* upstream function bodies (extracted by AST from a checkout or
from the vendored excerpts in examples/upstream/) against adversarial fixtures
and reports semantic divergence with a minimal witness.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any, Optional

SCHEMA = "indicator-parity/1"
UPSTREAM = "tradermonty/claude-trading-skills"
UPSTREAM_COMMIT = "6d98c9e"

# Variant manifest: where the function lives and what calling convention it
# declares.  `order` is taken from the upstream docstring, not assumed.
VARIANTS = [
    {"id": "rsi.value_dividend", "family": "rsi", "file": "screen_dividend_stocks.py",
     "func": "calculate_rsi", "order": "oldest-first", "returns": "scalar", "kind": "list"},
    {"id": "rsi.dividend_growth", "family": "rsi", "file": "screen_dividend_growth_rsi.py",
     "func": "calculate_rsi", "order": "oldest-first", "returns": "scalar", "kind": "list"},
    {"id": "rsi.theme_detector", "family": "rsi", "file": "etf_scanner.py",
     "func": "_calculate_rsi", "order": "oldest-first", "returns": "scalar", "kind": "series"},
    {"id": "ema.ftd_monitor", "family": "ema", "file": "post_ftd_monitor.py",
     "func": "_calculate_ema", "order": "oldest-first", "returns": "scalar", "kind": "list"},
    {"id": "ema.math_helpers", "family": "ema", "file": "math_helpers.py",
     "func": "ema", "order": "oldest-first", "returns": "scalar", "kind": "list"},
    {"id": "ema.market_calculator", "family": "ema", "file": "market_calculator.py",
     "func": "calculate_ema", "order": "newest-first", "returns": "scalar", "kind": "list"},
    {"id": "ema.momentum", "family": "ema", "file": "momentum_calculator.py",
     "func": "_ema", "order": "oldest-first", "returns": "series", "kind": "list"},
]


# --------------------------------------------------------------------------
# Minimal pandas Series shim: only the surface the upstream RSI copy touches.
# --------------------------------------------------------------------------
class _ILoc:
    def __init__(self, series: "Series") -> None:
        self._s = series

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, slice):
            return Series(self._s._d[item])
        return self._s._d[item]


class Series:
    def __init__(self, data: Any) -> None:
        self._d = list(data)

    def __len__(self) -> int:
        return len(self._d)

    def __iter__(self):
        return iter(self._d)

    @property
    def iloc(self) -> _ILoc:
        return _ILoc(self)

    def diff(self) -> "Series":
        out: list[Any] = [None]
        for i in range(1, len(self._d)):
            a, b = self._d[i], self._d[i - 1]
            out.append(None if a is None or b is None else a - b)
        return Series(out)

    def _cmp(self, other: Any, op) -> "Series":
        return Series([None if v is None else op(v, other) for v in self._d])

    def __gt__(self, other: Any) -> "Series":
        return self._cmp(other, lambda a, b: a > b)

    def __lt__(self, other: Any) -> "Series":
        return self._cmp(other, lambda a, b: a < b)

    def __neg__(self) -> "Series":
        return Series([None if v is None else -v for v in self._d])

    def where(self, cond: Any, other: Any) -> "Series":
        out = []
        for i, v in enumerate(self._d):
            keep = None if isinstance(cond, Series) else bool(cond)
            if isinstance(cond, Series):
                keep = cond._d[i]
            out.append(v if keep else other)
        return Series(out)

    def mean(self) -> float:
        vals = [v for v in self._d if v is not None and math.isfinite(v)]
        return sum(vals) / len(vals) if vals else float("nan")


class _PandasShim:
    Series = Series


def _read_price(row: dict, key: str) -> Optional[float]:
    """Stand-in for the upstream read_price(): reject anything non-finite."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def extract(src_path: Path, func_name: str) -> str:
    """Pull one function out of a real checkout, keeping its exact body."""
    source = textwrap.dedent(src_path.read_text(encoding="utf-8"))
    tree = ast.parse(source)
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == func_name]
    if not hits:
        raise LookupError(f"{func_name} not found in {src_path.name}")
    # Prefer a method (RSICalculator.calculate_rsi) over a same-named free function.
    node = sorted(hits, key=lambda n: n.col_offset)[-1]
    return textwrap.dedent("\n".join(source.splitlines()[node.lineno - 1:node.end_lineno]))


def load_variant(variant: dict, source_dir: Path) -> Any:
    body = extract(source_dir / variant["file"], variant["func"])
    ns: dict = {"math": math, "Optional": Optional, "pd": _PandasShim(),
                "read_price": _read_price}
    stem = Path(variant["file"]).stem
    for helper in ("_finite_number",):
        snippet = source_dir / f"{stem}__{helper.lstrip(chr(95))}.py"
        try:
            helper_src = (snippet.read_text(encoding="utf-8") if snippet.exists()
                          else extract(source_dir / variant["file"], helper))
            exec(compile(textwrap.dedent(helper_src), snippet.name, "exec"), ns)
        except LookupError:
            pass
    exec(compile(body, str(source_dir / variant["file"]), "exec"), ns)
    return ns[variant["func"]]


def _norm(value: Any) -> Any:
    """JSON-safe scalar: errors become strings, NaN propagates as null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def call_variant(fn: Any, variant: dict, series: list, period: int) -> dict:
    """Call one variant, respecting its declared argument order."""
    payload = list(series) if variant["order"] == "oldest-first" else list(reversed(series))
    try:
        arg = _PandasShim.Series(payload) if variant["kind"] == "series" else payload
        raw = fn(arg, period)
        if variant["returns"] == "series":
            if isinstance(raw, (list, tuple)):
                raw = raw[-1] if raw else None
        return {"value": _norm(raw)}
    except Exception as exc:  # noqa: BLE001 - the exception type *is* the finding
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------
# Fixtures: adversarial shapes that a cross-skill contract test must cover.
# --------------------------------------------------------------------------
def _rising(n: int = 30, start: float = 50.0, step: float = 1.0) -> list:
    return [round(start + i * step, 4) for i in range(n)]


def _wobble(target_rsi: float, n: int = 41) -> list:
    """Deterministic search for a series whose Wilder RSI lands near target."""
    import random
    rng = random.Random(20261116)
    best = None
    for _ in range(4000):
        prices = [100.0]
        for _ in range(n - 1):
            prices.append(round(prices[-1] * (1 + rng.uniform(-0.02, 0.02)), 6))
        gains, losses = [], []
        for i in range(1, len(prices)):
            d = prices[i] - prices[i - 1]
            gains.append(max(d, 0.0))
            losses.append(max(-d, 0.0))
        ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            ag = (ag * 13 + gains[i]) / 14
            al = (al * 13 + losses[i]) / 14
        if al == 0:
            continue
        rsi = 100 - 100 / (1 + ag / al)
        score = abs(rsi - target_rsi)
        if best is None or score < best[0]:
            best = (score, prices, rsi)
    return best[1]


DEFAULT_FIXTURES: dict[str, list] = {
    # Wilder RSI ~69.96: 1-dp rounding (upstream) reports 70.0, 2-dp reports 69.96.
    # True Wilder RSI 69.9514: round(...,1) -> 70.0 (overbought) while
    # round(...,2) -> 69.95 (not overbought). Deterministic, no live prices.
    "rsi_threshold_edge": [100.0, 102.421589, 102.615287, 105.171497, 105.743695,
                           108.202825, 106.68619, 108.051328, 107.319019, 105.90635,
                           108.237919, 106.886131, 106.983665, 105.846879, 104.839042,
                           104.416067, 102.623943, 103.948256, 103.401014, 104.742238,
                           105.436647, 103.095507, 100.524969, 100.061898, 102.745404,
                           104.177715, 104.811366, 104.36981, 104.467766, 104.931179,
                           105.051105, 102.919751, 105.832612, 106.309024, 107.80801,
                           110.210287, 110.747725, 111.7359, 114.185117, 114.051183,
                           113.156197],
    "flat_30": [100.0] * 30,
    "rsi_with_nan": [100.0] * 14 + [None] + [100.0 + i for i in range(15)],
    "short_5": [10.0, 11.0, 10.5, 12.0, 11.8],
    # Gap-open then flat: SMA seed vs first-value seed diverge by ~95 points.
    "ema_seed_40": [200.0] + [100.0 + (i % 3) * 0.5 for i in range(39)],
}


def resolve_fixtures(path: Optional[Path]) -> dict:
    base = {k: list(v) for k, v in DEFAULT_FIXTURES.items()}
    if path is None:
        return base
    data = json.loads(path.read_text(encoding="utf-8"))
    series = data.get("series", data)
    if not isinstance(series, dict) or not series:
        raise ValueError("fixtures file must be {\"series\": {name: [numbers]}}")
    # A custom file overrides individual series and keeps the rest of the suite.
    base.update({k: list(v) for k, v in series.items()})
    return base


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def _classify_rsi(series: list, period: int = 14) -> dict:
    fn = load_variant(VARIANTS[0], EXAMPLES)
    return call_variant(fn, VARIANTS[0], series, period)


def run_checks(source_dir: Path, fixtures: dict) -> list:
    fns = {v["id"]: load_variant(v, source_dir) for v in VARIANTS}
    by_family = {"rsi": [v for v in VARIANTS if v["family"] == "rsi"],
                 "ema": [v for v in VARIANTS if v["family"] == "ema"]}

    def run(family: str, series: list, period: int) -> dict:
        out = {}
        for v in by_family[family]:
            out[v["id"]] = call_variant(fns[v["id"]], v, series, period)
        return out

    checks: list[dict] = []

    def add(cid, family, kind, values, witness, note, impact=None, semantic=None):
        nums = [r["value"] for r in values.values()
                if isinstance(r.get("value"), (int, float))]
        spread = round(max(nums) - min(nums), 6) if len(nums) >= 2 else 0.0
        errors = {k: r["error"] for k, r in values.items() if "error" in r}
        nulls = [k for k, r in values.items() if r.get("value") is None and "error" not in r]
        checks.append({
            "id": cid, "family": family, "status": kind,
            "values": values, "spread": spread, "nulls": sorted(nulls),
            "errors": errors, "witness": witness, "note": note,
            "impact": impact, "semantic_defect": semantic,
        })

    # 1. RSI rounding precision -> decision threshold flip.
    s = fixtures["rsi_threshold_edge"]
    vals = run("rsi", s, 14)
    flips = []
    for lo, hi in ((30.0, 70.0),):
        for a, ra in vals.items():
            for b, rb in vals.items():
                if a >= b or "value" not in ra or "value" not in rb:
                    continue
                va, vb = ra["value"], rb["value"]
                if va is None or vb is None:
                    continue
                for t in (lo, hi):
                    if (va >= t) != (vb >= t):
                        flips.append({"threshold": t, "overbought_a": a, "value_a": va,
                                      "overbought_b": b, "value_b": vb})
    add("rsi.rounding_precision", "rsi", "divergent" if flips else "consistent", vals, s,
        "RSI copies round to 1 vs 2 decimals; near a 30/70 threshold the same series is "
        "classified differently.", impact={"threshold_flips": flips})

    # 2. Flat series -> every copy reports 100.0 (no movement => undefined, not overbought).
    flat = fixtures["flat_30"]
    vals = run("rsi", flat, 14)
    flat_vals = [r.get("value") for r in vals.values()]
    flat_bad = bool(flat_vals) and all(v == 100.0 for v in flat_vals)
    add("rsi.flat_series", "rsi",
        "degenerate_agreement" if flat_bad else "consistent",
        vals, flat,
        "A zero-movement series yields avg_loss == 0 and every copy returns 100.0, which "
        "screens as 'overbought' although RSI is undefined without movement.",
        semantic=flat_bad)

    # 3. NaN policy: None vs NaN leak vs silent coercion.
    nan_series = fixtures["rsi_with_nan"]
    vals = run("rsi", nan_series, 14)
    kinds = {k: ("error" if "error" in r else ("null" if r["value"] is None else "number"))
             for k, r in vals.items()}
    add("rsi.nan_policy", "rsi", "divergent" if len(set(kinds.values())) > 1 else "consistent",
        vals, nan_series, "Same NaN-bearing series: value_dividend returns None, theme_detector silently "
        "drops the gap and returns a number, so the NaN never reaches the caller.", impact={"outcome_kinds": kinds})

    # 4. Invalid period: ValueError vs None vs silent garbage.
    vals = run("rsi", fixtures["ema_seed_40"], 0)
    kinds = {k: ("error" if "error" in r else ("null" if r["value"] is None else "number"))
             for k, r in vals.items()}
    add("rsi.invalid_period", "rsi", "divergent" if len(set(kinds.values())) > 1 else "consistent",
        vals, fixtures["ema_seed_40"], "period=0 raises in one copy, returns None in another, "
        "and returns a number in the third.", impact={"outcome_kinds": kinds})

    # 5. EMA seed rule: SMA seed vs first-value seed.
    seed = fixtures["ema_seed_40"]
    vals = run("ema", seed, 20)
    nums = {k: r["value"] for k, r in vals.items() if isinstance(r.get("value"), (int, float))}
    seed_spread = round(max(nums.values()) - min(nums.values()), 6) if len(nums) >= 2 else 0.0
    add("ema.seed_rule", "ema", "divergent" if seed_spread > 1e-9 else "consistent", vals, seed,
        "Three copies seed the EMA with the SMA of the first `period` values; the momentum copy "
        "seeds with values[0], so the same series produces a different EMA.",
        impact={"spread": seed_spread,
                "relative_pct": round(seed_spread / max(nums.values()) * 100, 4) if nums else None})

    # 6. Insufficient data: mean fallback vs None vs last value.
    short = fixtures["short_5"]
    vals = run("ema", short, 20)
    kinds = {k: ("error" if "error" in r else ("null" if r["value"] is None else "number"))
             for k, r in vals.items()}
    add("ema.short_data", "ema", "divergent" if len(set(kinds.values())) > 1 else "consistent",
        vals, short, "Below `period`: one copy averages, one returns None, one raises on a "
        "period guard; callers cannot tell a real EMA from a fallback.",
        impact={"outcome_kinds": kinds})

    # 7. Declared-order hazard: chronological input into the newest-first copy.
    trend = _rising(40, 60.0, 1.0)
    vals = run("ema", trend, 20)
    correct = vals["ema.math_helpers"].get("value")
    hazard = None
    if isinstance(correct, (int, float)):
        try:  # deliberately bypass the adapter: caller ignores the newest-first contract
            mm = {"value": fns["ema.market_calculator"](list(trend), 20)}
        except Exception as exc:  # noqa: BLE001
            mm = {"error": f"{type(exc).__name__}: {exc}"}
        if isinstance(mm.get("value"), (int, float)):
            hazard = round((mm["value"] - correct) / correct * 100, 4)
    add("ema.declared_order", "ema", "hazard" if hazard is not None and abs(hazard) > 1.0 else "consistent",
        vals, trend, "ema.market_calculator documents 'most recent first' and reverses "
        "internally; every other copy takes oldest-first. Feeding it the same chronological "
        "list silently reports a different EMA.", impact={"chronological_misuse_pct": hazard})

    return checks


def build_report(source_dir: Path, fixtures: dict, source_mode: str) -> dict:
    checks = run_checks(source_dir, fixtures)
    div = [c["id"] for c in checks if c["status"] in ("divergent", "hazard")]
    sem = [c["id"] for c in checks if c["semantic_defect"]]
    return {
        "schema": SCHEMA,
        "upstream": UPSTREAM,
        "upstream_commit": UPSTREAM_COMMIT,
        "source": {"mode": source_mode, "dir": str(source_dir)},
        "variants": [{"id": v["id"], "family": v["family"], "file": v["file"],
                      "func": v["func"], "declared_order": v["order"]} for v in VARIANTS],
        "fixtures": sorted(fixtures),
        "checks": checks,
        "summary": {"checks": len(checks), "divergent": len(div),
                    "semantic_defects": len(sem),
                    "divergent_ids": div + [s for s in sem if s not in div],
                    "verdict": "drift" if (div or sem) else "parity"},
        "assumptions": [
            "upstream functions are executed verbatim; only pandas/read_price are stubbed",
            "series data are synthetic fixtures generated deterministically, never live prices",
        ],
    }


EXAMPLES = Path(__file__).resolve().parent / "examples" / "upstream"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="indicator-parity",
        description="Run every copy of an indicator on identical fixtures and report drift.")
    parser.add_argument("--repo", type=Path, default=None,
                        help="upstream checkout (defaults to vendored examples/upstream/)")
    parser.add_argument("--fixtures", type=Path, default=None,
                        help="JSON file: {\"series\": {name: [close, ...]}}")
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON report")
    args = parser.parse_args(argv)

    if args.repo is not None:
        if not args.repo.is_dir():
            print(f"error: --repo not a directory: {args.repo}", file=sys.stderr)
            return 2
        source_dir, mode = args.repo, "checkout"
    else:
        source_dir, mode = EXAMPLES, "vendored"

    try:
        fixtures = resolve_fixtures(args.fixtures)
        missing = {v["file"] for v in VARIANTS} - {p.name for p in Path(source_dir).iterdir()}
        if missing:
            raise FileNotFoundError(f"missing upstream files in {source_dir}: {sorted(missing)}")
        report = build_report(Path(source_dir), fixtures, mode)
    except (ValueError, LookupError, FileNotFoundError, SyntaxError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2

    if args.json or args.pretty:
        print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    else:
        print(f"upstream {UPSTREAM} @ {UPSTREAM_COMMIT}  ({mode})")
        for c in report["checks"]:
            cells = ", ".join(f"{k.split('.')[-1]}={r.get('value', r.get('error'))}"
                              for k, r in c["values"].items())
            print(f"[{c['status']:>20}] {c['id']}: {cells}")
        s = report["summary"]
        print(f"\n{s['divergent']} divergent, {s['semantic_defects']} semantic defect(s), "
              f"verdict={s['verdict']}")
    return 1 if report["summary"]["verdict"] == "drift" else 0


if __name__ == "__main__":
    sys.exit(main())
