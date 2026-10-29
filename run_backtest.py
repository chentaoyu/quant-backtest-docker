"""用法：
  uv run run_backtest.py --symbol 600519                        # 默认参数回测
  uv run run_backtest.py --symbol 600519 --optimize             # 全样本优化
  uv run run_backtest.py --symbol 600519 --split 20230101       # 样本外验证：split 前优化，split 后检验
  uv run run_backtest.py --symbol 600519 --source tushare       # 显式指定数据源
  uv run run_backtest.py --symbol 600519 --refresh              # 忽略缓存重新取数

网页版：uv run uvicorn web.app:app --reload
"""
import argparse
import sys

import pandas as pd

from backtest_engine import REPORTS_DIR, BacktestError, RunConfig, run
from data_loader import DataError
from strategies import STRATEGIES

# A 股费用近似：佣金万 2.5 + 卖出印花税千 0.5，这里合并为单边 0.0005
COMMISSION = 0.0005
METRICS = ["Start", "End", "Return [%]", "Buy & Hold Return [%]", "Return (Ann.) [%]",
           "Sharpe Ratio", "Max. Drawdown [%]", "# Trades", "Win Rate [%]"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A 股日线策略回测")
    parser.add_argument("--symbol", default="600519")
    parser.add_argument("--strategy", default="sma_cross", choices=list(STRATEGIES),
                        help=f"策略：{', '.join(STRATEGIES)}")
    parser.add_argument("--source", default="auto", choices=["auto", "tushare", "akshare"],
                        help="数据源，auto 表示有 TUSHARE_TOKEN 用 tushare，否则 akshare")
    parser.add_argument("--start", default="20180101")
    parser.add_argument("--end", default="20261231")
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--commission", type=float, default=COMMISSION)
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--split", help="样本外切分日期 YYYYMMDD")
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新拉取数据")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = RunConfig(
        symbol=args.symbol,
        strategy=args.strategy,
        source=args.source,
        start=args.start,
        end=args.end,
        cash=args.cash,
        commission=args.commission,
        # 样本外模式默认在训练段做网格优化（与旧版行为一致）
        optimize=args.optimize or bool(args.split),
        split=args.split,
        refresh=args.refresh,
    )
    try:
        result = run(
            config,
            report_dir=REPORTS_DIR,
            report_name=f"{args.symbol}_{args.strategy}",
            write_manifest=False,
        )
    except (BacktestError, DataError) as exc:
        print(f"回测失败：{exc}", file=sys.stderr)
        return 2

    data = result["data"]
    print(f"[data] {data['source']} · {data['adjust']} · {data['start']} ~ {data['end']} · "
          f"{data['rows']} 根 · {'缓存' if data['cached'] else '新拉取'}")
    for warning in result["warnings"]:
        print(f"[warn] {warning}")
    print(f"[params] {result['params']}")

    metrics = pd.Series(result["metrics"])
    oos = result["oos"]
    if oos:
        table = pd.DataFrame({
            f"训练段·优化 {oos['train']['params']}": pd.Series(oos["train"]["metrics"])[METRICS],
            "测试段·沿用训练参数": pd.Series(oos["test_params"]["metrics"])[METRICS],
            "测试段·默认参数": pd.Series(oos["test_default"]["metrics"])[METRICS],
        })
        if oos["test_oracle"]:
            table[f"测试段·事后最优 {oos['test_oracle']['params']}"] = pd.Series(
                oos["test_oracle"]["metrics"])[METRICS]
        print("\n=== 样本外验证 ===")
        print(table.to_string())
        decay = oos["sharpe_decay"]
        if decay is None:
            print(f"\n夏普衰减比：不适用（{oos['sharpe_decay_note']}）")
        else:
            print(f"\n夏普衰减比（测试/训练）：{decay:.2f}  （>0.5 较稳健，<0 说明样本外失效）")
    else:
        print(metrics.to_string())

    report = result["report_file"]
    print(f"\n图表已生成：{REPORTS_DIR / report}  （运行编号 {result['run_id']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
