#!/usr/bin/env python3
"""Walk-forward test trade-timing states with next-session execution and stop logic."""

from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path
from typing import Any

from compute_trade_timing import TIMING_MIN_HISTORY, compute_asset_timing
from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import clean_bars


DEFAULT_STATES = ("triggered", "retest")
METHOD_VERSION = "trade-timing-backtest/1.1"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if gains == 0 else 999.0
    return round(gains / losses, 4)


def _trade_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return round(worst * 100.0, 4)


def _gate(metrics: dict[str, Any], trades: int, evaluation_start: str | None) -> dict[str, Any]:
    checks = {
        "predeclared_evaluation_start_supplied": bool(evaluation_start),
        "at_least_20_non_overlapping_trades": trades >= 20,
        "positive_mean_net_return": (_number(metrics.get("mean_net_return_pct")) or 0.0) > 0,
        "positive_mean_excess_return": (_number(metrics.get("mean_excess_return_pct")) or 0.0) > 0,
        "net_hit_rate_at_least_45pct": (_number(metrics.get("hit_rate")) or 0.0) >= 0.45,
        "profit_factor_above_one": (_number(metrics.get("profit_factor")) or 0.0) > 1.0,
    }
    return {
        "status": "usable" if all(checks.values()) else "abstain",
        "checks": checks,
        "reason": "all timing validation checks passed" if all(checks.values()) else "timing setup lacks adequate point-in-time out-of-sample support",
    }


def run_asset_backtest(
    asset: dict[str, Any],
    benchmark: dict[str, Any],
    *,
    horizon: int = 20,
    step: int = 1,
    cost_bps: float = 20.0,
    slippage_bps: float = 10.0,
    states: tuple[str, ...] = DEFAULT_STATES,
    start: str | None = None,
) -> dict[str, Any]:
    rows = clean_bars(asset.get("bars") or [])
    benchmark_rows = clean_bars(benchmark.get("bars") or [])
    benchmark_by_date = {item["date"]: item for item in benchmark_rows}
    code = str(asset.get("code") or "")
    trades: list[dict[str, Any]] = []
    skipped_incomplete_horizon = 0
    decision_index = TIMING_MIN_HISTORY - 1
    slip = slippage_bps / 10000.0
    cost_pct = cost_bps / 100.0

    while decision_index < len(rows) - 1:
        decision = rows[decision_index]
        if start and decision["date"] < start:
            decision_index += max(1, step)
            continue
        sliced_asset = {**asset, "bars": rows[: decision_index + 1]}
        timing = compute_asset_timing(sliced_asset, benchmark, as_of=decision["date"])
        state = str(timing.get("state") or "")
        if state not in states:
            decision_index += max(1, step)
            continue

        entry_index = decision_index + 1
        exit_index = entry_index + horizon - 1
        if exit_index >= len(rows):
            skipped_incomplete_horizon += 1
            decision_index += max(1, step)
            continue
        entry_row = rows[entry_index]
        exit_row = rows[exit_index]
        entry_open = _number(entry_row.get("open"))
        if entry_open is None or entry_open <= 0:
            decision_index += max(1, step)
            continue
        stop = _number(((timing.get("risk") or {}).get("technical_stop_reference")))
        if stop is None or stop <= 0 or stop >= entry_open:
            decision_index += max(1, step)
            continue

        entry_price = entry_open * (1.0 + slip)
        exit_price: float | None = None
        exit_reason = "horizon_close"
        realized_exit_index = exit_index
        for index in range(entry_index, exit_index + 1):
            row = rows[index]
            open_price = _number(row.get("open")) or float(row["close"])
            low_price = _number(row.get("low")) or min(open_price, float(row["close"]))
            if open_price <= stop:
                exit_price = open_price * (1.0 - slip)
                exit_reason = "gap_through_stop"
                realized_exit_index = index
                break
            if low_price <= stop:
                exit_price = stop * (1.0 - slip)
                exit_reason = "intraday_stop"
                realized_exit_index = index
                break
        if exit_price is None:
            exit_price = float(exit_row["close"]) * (1.0 - slip)

        realized_exit = rows[realized_exit_index]
        benchmark_entry = benchmark_by_date.get(entry_row["date"])
        benchmark_exit = benchmark_by_date.get(realized_exit["date"])
        if not benchmark_entry or not benchmark_exit:
            decision_index = realized_exit_index + 1
            continue
        benchmark_entry_price = _number(benchmark_entry.get("open")) or _number(benchmark_entry.get("close"))
        benchmark_exit_price = _number(benchmark_exit.get("close"))
        if not benchmark_entry_price or not benchmark_exit_price:
            decision_index = realized_exit_index + 1
            continue

        gross_return = (exit_price / entry_price - 1.0) * 100.0
        net_return = gross_return - cost_pct
        benchmark_return = (benchmark_exit_price / benchmark_entry_price - 1.0) * 100.0
        trades.append({
            "signal_date": decision["date"],
            "entry_date": entry_row["date"],
            "exit_date": realized_exit["date"],
            "state": state,
            "entry_price": round(entry_price, 6),
            "stop_reference": round(stop, 6),
            "exit_price": round(exit_price, 6),
            "exit_reason": exit_reason,
            "holding_sessions": realized_exit_index - entry_index + 1,
            "gross_return_pct": round(gross_return, 4),
            "net_return_pct": round(net_return, 4),
            "benchmark_return_pct": round(benchmark_return, 4),
            "excess_return_pct": round(net_return - benchmark_return, 4),
        })
        decision_index = realized_exit_index + 1

    net_returns = [float(item["net_return_pct"]) for item in trades]
    excess_returns = [float(item["excess_return_pct"]) for item in trades]
    metrics = {
        "hit_rate": _rate([value > 0 for value in net_returns]),
        "excess_hit_rate": _rate([value > 0 for value in excess_returns]),
        "mean_net_return_pct": _mean(net_returns),
        "median_net_return_pct": round(statistics.median(net_returns), 4) if net_returns else None,
        "mean_excess_return_pct": _mean(excess_returns),
        "profit_factor": _profit_factor(net_returns),
        "trade_sequence_max_drawdown_pct": _trade_drawdown(net_returns),
        "stop_exit_rate": _rate([item["exit_reason"] != "horizon_close" for item in trades]),
    }
    warnings = [
        "Signals are frozen at the close and entered no earlier than the next session open.",
        "Trades are non-overlapping per asset to reduce repeated exposure counting.",
        "The model applies configured costs and slippage but cannot fully reproduce A-share limit locks, queue priority or market impact.",
        "Forward-adjusted histories and a current constituent universe can introduce corporate-action and survivorship bias.",
        "Signals without a complete configured holding horizon at the data boundary are excluded, even if they would have stopped out early.",
    ]
    if not start:
        warnings.append("No predeclared evaluation start was supplied; the gate must abstain because all-history results can hide regime decay.")
    if len(trades) < 20:
        warnings.append(f"only {len(trades)} non-overlapping trades; timing claims must abstain")
    return {
        "code": code,
        "name": asset.get("name"),
        "period": {
            "evaluation_start": start,
            "first_signal": trades[0]["signal_date"] if trades else None,
            "last_signal": trades[-1]["signal_date"] if trades else None,
            "trades": len(trades),
            "skipped_incomplete_horizon": skipped_incomplete_horizon,
        },
        "metrics": metrics,
        "gate": _gate(metrics, len(trades), start),
        "trades": trades,
        "warnings": warnings,
    }


def run_timing_backtest(
    history: dict[str, Any],
    asset_codes: list[str],
    benchmark_code: str,
    *,
    horizon: int = 20,
    step: int = 1,
    cost_bps: float = 20.0,
    slippage_bps: float = 10.0,
    states: tuple[str, ...] = DEFAULT_STATES,
    start: str | None = None,
) -> dict[str, Any]:
    series = {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}
    benchmark = series.get(benchmark_code)
    if not benchmark:
        raise ValueError(f"benchmark {benchmark_code} is missing from history")
    assets: list[dict[str, Any]] = []
    for code in dict.fromkeys(asset_codes):
        asset = series.get(code)
        if not asset:
            assets.append({
                "code": code,
                "period": {"first_signal": None, "last_signal": None, "trades": 0},
                "metrics": {},
                "gate": {"status": "abstain", "checks": {}, "reason": "asset series is missing"},
                "trades": [],
                "warnings": ["asset series is missing from history"],
            })
            continue
        assets.append(run_asset_backtest(
            asset,
            benchmark,
            horizon=horizon,
            step=step,
            cost_bps=cost_bps,
            slippage_bps=slippage_bps,
            states=states,
            start=start,
        ))
    return {
        "schema": "model.timing-backtest/1",
        "method_version": METHOD_VERSION,
        "created_at": utc_now(),
        "settings": {
            "benchmark_code": benchmark_code,
            "horizon_trading_days": horizon,
            "step_trading_days": step,
            "round_trip_cost_bps": cost_bps,
            "per_side_slippage_bps": slippage_bps,
            "eligible_states": list(states),
            "minimum_history_days": TIMING_MIN_HISTORY,
            "execution": "next_session_open_non_overlapping",
            "start": start,
            "usable_gate_requires_predeclared_start": True,
            "terminal_incomplete_horizons": "excluded",
        },
        "assets": assets,
        "warnings": list(dict.fromkeys(list(history.get("warnings") or []) + [
            "A timing state is usable only when its asset-specific gate is usable; otherwise the mandatory action is abstain/watch.",
        ])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--asset-code", action="append", required=True)
    parser.add_argument("--benchmark-code", help="defaults to the sector benchmark embedded in history")
    parser.add_argument("--horizon", type=int, choices=(5, 10, 20, 60), default=20)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--state", action="append", choices=("triggered", "retest", "triggered_unconfirmed"))
    parser.add_argument(
        "--start",
        help="predeclared first signal date for the out-of-sample gate; without it the gate always abstains",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    benchmark_code = args.benchmark_code or ((((history.get("universe_context") or {}).get("benchmark") or {}).get("code")))
    if not benchmark_code:
        parser.error("--benchmark-code is required when history has no embedded sector benchmark")
    result = run_timing_backtest(
        history,
        args.asset_code,
        str(benchmark_code),
        horizon=args.horizon,
        step=max(1, args.step),
        cost_bps=max(0.0, args.cost_bps),
        slippage_bps=max(0.0, args.slippage_bps),
        states=tuple(args.state or DEFAULT_STATES),
        start=args.start,
    )
    result["inputs"] = {
        "history_sha256": sha256_file(args.history),
        "history_path": str(args.history),
        "asset_codes": list(dict.fromkeys(args.asset_code)),
    }
    atomic_write_json(args.output, result)
    statuses = {item["code"]: item["gate"]["status"] for item in result["assets"]}
    print(f"timing_gates={statuses}")
    return 0 if any(item["period"]["trades"] for item in result["assets"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
