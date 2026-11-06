"""The v1 tenant-triage agent must keep its accuracy on the labelled sets."""
from eval.run_eval import run


def test_dev_set_fully_correct():
    report, misses = run("cases.jsonl")
    assert report["context"]["all_correct"] == report["context"]["n"], misses


def test_holdout_fully_correct():
    report, misses = run("holdout.jsonl")
    assert report["context"]["all_correct"] == report["context"]["n"], misses


def test_context_beats_baseline_on_cost_bearer():
    report, _ = run("cases.jsonl")
    assert report["context"]["cost_bearer"] > report["baseline"]["cost_bearer"] * 2
