"""Command line: python3 -m pathcheck.cli "question" (prints the trace, then the answer as JSON)."""
import json
import sys

from .agents import Team


def main():
    q = " ".join(sys.argv[1:]) or "I finished CS 311 and MATH 322. Can I take CS 400 and CS 560 in Spring 2027?"
    r = Team(emit=lambda e: print(f"[{e['agent']}] {e['action']}: {str(e.get('detail') or '')[:110]}"
                              + (f"  <{e['model']}>" if e.get("model") else ""))).run(q)
    print(json.dumps(r["answer"], indent=1))


if __name__ == "__main__":
    main()
