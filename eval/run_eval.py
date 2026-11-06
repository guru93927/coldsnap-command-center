"""Evaluate the agent with and without Building Memory on labelled tenant messages.

    python -m eval.run_eval            # summary table
    python -m eval.run_eval --misses   # also print every wrong decision
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from app.agent import triage
from app.ingest import build_memory

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 5)
FIELDS = ["category", "urgency", "cost_bearer", "vendor"]


def run(file="cases.jsonl"):
    mem = build_memory(ROOT / "data", TODAY)
    cases = [json.loads(l) for l in (ROOT / "eval" / file).read_text(encoding="utf-8").splitlines() if l.strip()]
    report, misses = {}, []
    for mode in ("baseline", "context"):
        score = {f: 0 for f in FIELDS + ["all_correct", "flags"]}
        n_flags = 0
        for c in cases:
            r = triage(c["message"], c["unit"], mem, TODAY, mode)
            got = {"category": r["understanding"]["category"], "urgency": r["understanding"]["urgency"],
                   "cost_bearer": r["cost_bearer"], "vendor": (r["vendor"] or {}).get("id")}
            ok = {f: got[f] == c[f] for f in FIELDS}
            for f in FIELDS:
                score[f] += ok[f]
            score["all_correct"] += all(ok.values())
            if c.get("expect_flag"):
                n_flags += 1
                score["flags"] += any(c["expect_flag"].lower() in fl["text"].lower() for fl in r["flags"])
            if mode == "context" and not all(ok.values()):
                misses.append((c, got))
        report[mode] = {k: v for k, v in score.items()} | {"n": len(cases), "n_flags": n_flags}
    return report, misses


def main():
    file = "holdout.jsonl" if "--holdout" in sys.argv else "cases.jsonl"
    report, misses = run(file)
    b, c = report["baseline"], report["context"]
    n = c["n"]
    pct = lambda x, d=n: f"{100 * x / d:5.1f}%" if d else "   n/a"
    print(f"\nEval [{file}]: {n} synthetic tenant messages (DE/EN/TR), demo date {TODAY}\n")
    print(f"{'metric':<34}{'no context':>12}{'with memory':>14}")
    rows = [("Issue category", "category"), ("Urgency", "urgency"), ("Who pays (cost bearer)", "cost_bearer"),
            ("Right vendor", "vendor"), ("Fully correct decision", "all_correct")]
    for label, k in rows:
        print(f"{label:<34}{pct(b[k]):>12}{pct(c[k]):>14}")
    print(f"{'Proactive flags caught':<34}{pct(b['flags'], b['n_flags']):>12}{pct(c['flags'], c['n_flags']):>14}"
          f"   ({c['n_flags']} cases)")
    out = ROOT / "eval" / f"results_{file.split('.')[0]}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if "--misses" in sys.argv:
        print("\nMisses (with memory):")
        for case, got in misses:
            diff = {f: (case[f], got[f]) for f in FIELDS if case[f] != got[f]}
            print(f"  #{case['id']} {case['unit']} \"{case['message']}\" -> expected/got {diff}")


if __name__ == "__main__":
    main()
