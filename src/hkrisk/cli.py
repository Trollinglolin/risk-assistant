"""`uv run hkrisk ...` convenience commands."""

import argparse
import json


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hkrisk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("var", help="VaR/ES for the current book")
    v.add_argument("--method", default="historical")
    v.add_argument("--alpha", type=float, default=0.99)
    v.add_argument("--as-of")
    a = sub.add_parser("ask", help="ask the agent a question")
    a.add_argument("question")
    a.add_argument("--provider")
    a.add_argument("--model")
    for p in (v, a):
        p.add_argument("--portfolio", default="core", choices=["core", "hsi"],
                       help="core (9 names) or hsi (all 95 Hang Seng Index constituents)")
    args = ap.parse_args(argv)

    from hkrisk.service import get_service

    svc = get_service(args.portfolio)
    if args.cmd == "var":
        print(json.dumps(svc.var(args.method, args.alpha, as_of=args.as_of), indent=2))
    elif args.cmd == "ask":
        from hkrisk.agent.loop import ask

        r = ask(args.question, service=svc, provider=args.provider, model=args.model)
        for c in r.tool_calls:
            print(f"  -> {c.name}({json.dumps(c.input)}){'  [error]' if c.is_error else ''}")
        print(f"\n{r.answer}\n\n[{r.provider}/{r.model}  {r.iterations} rounds  "
              f"{r.input_tokens}+{r.output_tokens} tokens  {r.latency_s}s]")
