#!/usr/bin/env python3
"""Build a deterministic evidence order for an A-share or ETF outlook."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, utc_now


DEFAULT_PRESETS = Path(__file__).resolve().parent.parent / "references" / "a-share-instrument-presets.json"
VALID_HORIZONS = ("5d", "20d", "60d", "12m")
VALID_SESSIONS = ("premarket", "intraday", "after_close", "structural")
VALID_EVENT_STATES = ("unknown", "none", "rumor", "confirmed_material")


def normalize_code(value: str) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) < 6:
        raise ValueError(f"invalid A-share security code: {value}")
    return digits[-6:]


def resolve_instrument(config: dict[str, Any], code: str) -> dict[str, Any]:
    normalized = normalize_code(code)
    item = dict(((config.get("instruments") or {}).get(normalized) or {}))
    if not item:
        return {
            "code": normalized,
            "known": False,
            "asset_type": "unknown",
            "requirements": [
                "verify exchange, official name and asset type",
                "verify underlying index or business exposure",
                "choose a broad-market benchmark",
                "add the verified mapping to a-share-instrument-presets.json when reuse is likely",
            ],
        }
    item.update({"code": normalized, "known": True, "mapping_as_of": config.get("as_of")})
    return item


def stage(key: str, priority: str, purpose: str, tasks: list[str], gate: str = "") -> dict[str, Any]:
    result = {"key": key, "priority": priority, "purpose": purpose, "tasks": tasks}
    if gate:
        result["gate"] = gate
    return result


def identity_stage(instrument: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        "确认证券代码、交易所、资产类型、观察时点和预测周期。",
        "确认跟踪指数或盈利暴露，并选择宽基超额收益基准。",
    ]
    exposure = instrument.get("exposure_model") or {}
    if exposure.get("mode") == "live_holdings_required":
        tasks.extend(
            [
                "读取当前指数成份与生效日，并读取基金最近披露持仓与报告期。",
                "计算行业权重、前十大权重合计与最大成份股权重；不得用产品名称猜行业。",
            ]
        )
    return stage(
        "identity_and_live_exposure",
        "P0_blocking",
        "先确认分析对象，避免把ETF或宽基错当成单一行业。",
        tasks,
        "身份、暴露日期或比较基准缺失时停止方向预测。",
    )


def event_clock_stage() -> dict[str, Any]:
    return stage(
        "event_clock_gate",
        "P1_blocking",
        "用快速扫描决定新闻原稿与本地价格状态谁先进入P2。",
        [
            "扫描过去72小时官方披露、监管发布、指数调整和核心成份股事件。",
            "区分传闻、提案、正式发布、批准、生效和结果；记录首次公开时间。",
            "仅当原始来源可打开、共享变量明确且可能在预测期改变现金流或折现率时，标记confirmed_material。",
        ],
        "unknown必须先完成扫描；转载量和标题情绪不能通过门禁。",
    )


def local_state_stage(horizon: str, *, before_event: bool = False) -> dict[str, Any]:
    prefix = "冻结事件前" if before_event else "计算截至观察日"
    windows = "5/20日" if horizon == "5d" else "20/60日"
    if horizon in ("60d", "12m"):
        windows = "20/60/120日"
    return stage(
        "local_expectation_state",
        "P2_high",
        "读取市场已经定价的预期，并为新闻反应建立基线；这不是因果证明。",
        [
            f"{prefix}绝对收益、相对宽基收益、{windows}动量、均线、量能、波动和回撤。",
            "对ETF加入成份股广度；对个股加入行业ETF相对强弱。",
            "标记利好前已上涨、利空前已下跌、放量冲高回落等预期差信号。",
        ],
    )


def news_stage(*, verification_first: bool = False) -> dict[str, Any]:
    purpose = "先核验来源，避免把传闻变成基本面事实。" if verification_first else "从原稿提取可证伪的触发、约束和传导变量。"
    return stage(
        "original_news_and_mechanism",
        "P2_high",
        purpose,
        [
            "先开交易所/公司/监管/指数机构原稿，再用媒体补充背景与不同观点。",
            "提取谁作出什么决定、何时生效、规模多大、影响订单/价格/成本/现金流还是折现率。",
            "写出共同解释及其局限，并提出至少一个竞争解释或反事实。",
        ],
        "原稿无法核验或传导规模不可估计时降低结论强度。",
    )


def cross_market_stage(instrument: dict[str, Any], *, premarket: bool = False) -> dict[str, Any]:
    cross = instrument.get("cross_market") or {}
    candidates = cross.get("candidate_presets") or []
    candidate_text = "、".join(candidates) if candidates else "按实时暴露选择强映射板块"
    first_task = "读取前一美股收盘和严格早于A股观察日的韩股收盘。" if premarket else "读取严格早于A股观察日的美股/韩股收盘。"
    return stage(
        "cross_market_readthrough",
        "P3_conditional_high",
        "用海外同行检验共享产业变量，不把外盘涨跌机械加进预测分数。",
        [
            first_task,
            f"候选映射：{candidate_text}；只保留达到实时暴露阈值且产业链相连的映射。",
            "每个海外代理先减去本国宽基收益，再检查事件龙头的原始财报或公告。",
            "缺少同日行业权重时分别报告各映射，不合成混合外盘分数。",
        ],
    )


def positioning_stage(instrument: dict[str, Any]) -> dict[str, Any]:
    focus = instrument.get("positioning_focus") or ["成交与换手", "资金流", "融资融券", "市场广度"]
    return stage(
        "a_share_acceptance_and_positioning",
        "P3_supporting",
        "判断A股是否接受海外或新闻冲击，并识别流动性与拥挤修正。",
        [
            "比较标的相对行业/宽基的开盘、收盘和后续窗口，分类确认、拒绝、韧性或分歧。",
            "检查：" + "、".join(focus) + "。",
            "把市场情绪、资金和期权作为确认或风险信号，不作为独立因果或买入理由。",
        ],
    )


def fundamentals_stage() -> dict[str, Any]:
    return stage(
        "fundamentals_valuation_and_policy",
        "P2_high",
        "长周期先验证盈利、估值与政策约束，技术动量只负责择时。",
        [
            "拆解收入、利润率、现金流、资本开支、估值和主要成份股盈利贡献。",
            "验证产业供需、政策生效时间、订单或临床/产品里程碑。",
            "压力测试利率、汇率、价格竞争、监管和融资条件。",
        ],
    )


def synthesis_stage(horizon: str) -> dict[str, Any]:
    return stage(
        "walk_forward_and_scenarios",
        "P4_conclusion",
        "把证据变成条件情景，而不是点位保证。",
        [
            f"对{horizon}使用严格时点一致的信号和扩展窗口回测，披露成本、样本和偏差。",
            "给出基准、上行、下行情景及各自触发、确认、失效和复核日。",
            "分别标注事实、推断、观点和条件预测；数据不足时输出待核验问题。",
        ],
        "不得把未校准方向分数写成概率，也不得由单一新闻、外盘或动量直接给出买卖结论。",
    )


def build_order(
    instrument: dict[str, Any], horizon: str, session: str, event_state: str
) -> list[dict[str, Any]]:
    identity = identity_stage(instrument)
    clock = event_clock_stage()
    local = local_state_stage(horizon)
    news = news_stage(verification_first=event_state == "rumor")
    cross = cross_market_stage(instrument, premarket=session == "premarket")
    positioning = positioning_stage(instrument)
    synthesis = synthesis_stage(horizon)

    if session == "structural" or horizon in ("60d", "12m"):
        return [identity, clock, fundamentals_stage(), news, cross, positioning, local, synthesis]
    if event_state == "confirmed_material":
        return [identity, clock, news, local_state_stage(horizon, before_event=True), cross, positioning, synthesis]
    if event_state == "rumor":
        return [identity, clock, local, news, positioning, cross, synthesis]
    if session == "premarket":
        return [identity, clock, news, cross, local, positioning, synthesis]
    return [identity, clock, local, news, cross, positioning, synthesis]


def command_templates(instrument: dict[str, Any], horizon: str) -> list[str]:
    code = instrument["code"]
    market_code = str((instrument.get("market_benchmark") or {}).get("code") or "000300")
    commands = [
        f"python3 scripts/fetch_price_history.py --code {code} --code {market_code} --days 360 --output work/{code}-history-preliminary.json",
        f"python3 scripts/forecast_sector.py work/{code}-history-preliminary.json --benchmark {code} --market-benchmark {market_code} --output work/{code}-trend.json",
        "python3 scripts/fetch_a_share_sentiment.py --output work/a-share-snapshot.json",
        "python3 scripts/compute_market_mood.py work/a-share-snapshot.json --output work/market-mood.json",
    ]
    for preset in (instrument.get("cross_market") or {}).get("candidate_presets") or []:
        commands.append(
            f"python3 scripts/fetch_cross_market_history.py --preset {preset} --days 360 --output work/{code}-{preset}-cross.json"
        )
    commands.append(
        f"# Replace preliminary history with a current constituent universe before publishing a {horizon} breadth-based forecast."
    )
    return commands


def build_plan(
    config: dict[str, Any], code: str, horizon: str, session: str, event_state: str
) -> dict[str, Any]:
    instrument = resolve_instrument(config, code)
    order = build_order(instrument, horizon, session, event_state)
    warning = None
    if event_state == "unknown":
        warning = "先执行event_clock_gate；若发现confirmed_material，必须把original_news_and_mechanism提升到local_expectation_state之前。"
    return {
        "schema": "a-share.outlook-plan/1",
        "created_at": utc_now(),
        "instrument": instrument,
        "request": {"horizon": horizon, "session": session, "event_state": event_state},
        "decision_rule": {
            "normal": "身份/暴露 -> 本地预期状态 -> 新闻原稿 -> 外盘同变量 -> A股接受与资金 -> 回测与情景",
            "confirmed_material_event": "身份/暴露 -> 事件原稿 -> 事件前定价 -> 外盘同变量 -> A股接受与资金 -> 回测与情景",
            "rumor_or_unverified": "身份/暴露 -> 本地预期状态 -> 追溯原稿 -> 观察接受/反转 -> 外盘旁证 -> 暂缓强结论",
            "principle": "动量用于读取预期和择时，新闻原稿用于因果；外盘用于机制对照，三者均不能单独定方向。",
        },
        "execution_order": [{"sequence": index, **item} for index, item in enumerate(order, start=1)],
        "command_templates": command_templates(instrument, horizon),
        "branch_warning": warning,
        "publication_requirements": [
            "标明观察日、预测周期、成份/持仓日期和比较基准",
            "原始来源支持核心事件与传导链",
            "外盘使用严格更早收盘并剔除本国宽基共同因子",
            "ETF外盘映射按实时暴露选择；缺少权重时不合成",
            "给出情景、触发、失效、复核日、覆盖率和数据偏差",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=False)
    parser.add_argument("--horizon", choices=VALID_HORIZONS, default="20d")
    parser.add_argument("--session", choices=VALID_SESSIONS, default="after_close")
    parser.add_argument("--event-state", choices=VALID_EVENT_STATES, default="unknown")
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--list-instruments", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_json(args.presets)
    if args.list_instruments:
        for code, item in (config.get("instruments") or {}).items():
            print(f"{code}\t{item.get('short_name') or item.get('name')}\t{item.get('asset_type')}")
        return 0
    if not args.code or not args.output:
        parser.error("--code and --output are required unless --list-instruments is used")
    result = build_plan(config, args.code, args.horizon, args.session, args.event_state)
    atomic_write_json(args.output, result)
    keys = " -> ".join(item["key"] for item in result["execution_order"])
    print(f"{result['instrument']['code']} {args.horizon}: {keys}")
    if result.get("branch_warning"):
        print(result["branch_warning"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
