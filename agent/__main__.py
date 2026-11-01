"""命令行对话：uv run python -m agent "我的持仓今天怎么样" [--fast] [--think]"""
import argparse

from agent.server import ask


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m agent")
    parser.add_argument("message")
    parser.add_argument("--fast", action="store_true", help="用快模型（LLM_FAST）")
    parser.add_argument("--think", action="store_true", help="开启思考（reasoning_effort=medium）")
    args = parser.parse_args()

    result = ask(args.message, model="fast" if args.fast else "main", reasoning="medium" if args.think else None)
    for s in result["steps"]:
        print(f"  [{'ok' if s['ok'] else 'ERR'}] {s['tool']}({s['args']}) {s['ms']}ms")
    print(f"\n{result['reply']}\n")
    u = result["usage"]
    print(f"— {result['model']} | {result['elapsed_sec']}s | 输入 {u['prompt_tokens']} / 输出 {u['completion_tokens']} tokens")


if __name__ == "__main__":
    main()
