#!/usr/bin/env python3
"""
Pipeline CLI.

`ROUND2_REVIEW.md` (next-step item 3) asked for an explicit entry point that wires
the NEW judge into the pipeline, keeps the v1 scripts as history without letting
their defaults be used by accident, and makes the output paths unambiguous.

Path convention (stated here once, because the two trees are easy to confuse)
---------------------------------------------------------------------------
  outputs/   working artefacts written by these scripts (never published wholesale)
  results/   the published mirror inside the public repository
             (`ci-steering-reproduction/results/…` = `repo/outputs/…`)

Every command below resolves its output under
  outputs/research_next_round/<run-id>/…
and prints the resolved path plus the exact underlying command before running it.

History is kept, not deleted:
  * v1 judge       src/evaluation/ci_eval.py     (round-1 protocol, do NOT mix)
  * v2 scenarios   src/pilot_scenarios_v2.py     (role overlap + vacuous C4)
  * v2 LDA         src/subspace_selectivity_v2.py (ungrouped folds)
  * v2 blind pkg   src/build_blind_package.py    (no story/prompt in the items)
Those files stay on disk for the historical record; this CLI never calls them.

Usage
-----
  python src/pipeline.py --list
  python src/pipeline.py finalise
  python src/pipeline.py scenarios --policy-mode explicit
  python src/pipeline.py blind --n-random 50
  python src/pipeline.py lda --permutations 200
  python src/pipeline.py judge-tests
  python src/pipeline.py judge-validate --cases 10 --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_RUN = "round3_2026-09-30"

# command -> (module, output sub-path or None, extra fixed args)
COMMANDS = {
    "manifest": {
        "script": "src/run_manifest.py",
        "out": None,
        "help": "record commit/diff/model snapshots/software versions/GPU/input hashes",
    },
    "judge-tests": {
        "script": "tests/test_ci_judge_v2.py",
        "out": "judge_regression_tests.json",
        "help": "offline regression tests for the judge (no API, no GPU)",
    },
    "finalise": {
        "script": "src/finalise_round1.py",
        "out": "final_records",
        "help": "per-sample final record + paired tables + grouped bootstrap",
    },
    "lda": {
        "script": "src/subspace_selectivity_v3.py",
        "out": "lda_v3",
        "help": "cross-projection LDA with JOINT groups across the three parameters",
    },
    "scenarios": {
        "script": "src/pilot_scenarios_v3.py",
        # scenario DATA lives under data/, not under outputs/ (it is an input, not a
        # run artefact). The script default is data/pilot_v3 and the CLI keeps it.
        "out": None,
        "help": "build the v3 explicit-authorization scenario data + contract checks "
                "(writes data/pilot_v3/)",
    },
    "blind": {
        "script": "src/build_blind_package_v2.py",
        "out": "blind_review",
        "help": "human blind-annotation package with full story + prompt",
    },
    "judge-validate": {
        "script": "src/validate_judge_real.py",
        "out": "judge_validation",
        "help": "real-API small-sample check of the judge on hand-labelled cases",
    },
    "verify-grouping": {
        "script": "src/verify_grouping_claims.py",
        "out": None,
        "help": "measure how the three CI parameter stimulus sets overlap",
    },
    "verify-independence": {
        "script": "src/verify_scenario_independence.py",
        "out": None,
        "help": "check whether the 270 evaluation scenarios are independent stories",
    },
    "align-activations": {
        "script": "src/verify_activation_alignment.py",
        "out": "activation_alignment",
        "help": "freeze the input<->state correspondence (token limits, row mapping, truncation)",
    },
    "label-baseline": {
        "script": "src/label_baseline_behavior.py",
        "out": "baseline_labels",
        "help": "full behaviour labels for the baseline replies (needs an API key)",
    },
    "probe": {
        "script": "src/probe_generation_state.py",
        "out": "probe",
        "help": "grouped out-of-fold norm probe on the unsteered generation state",
    },
}

PATH_ARGS = {
    "finalise": ("--out-dir", "final_records"),
    "lda": ("--output-dir", "lda_v3"),
    "blind": ("--out-dir", "blind_review"),
    "judge-validate": ("--out-dir", "judge_validation"),
    "align-activations": ("--out-dir", "activation_alignment"),
    "label-baseline": ("--out-dir", "baseline_labels"),
    "probe": ("--out-dir", "probe"),
}


def print_list():
    print(f"run-id: {DEFAULT_RUN}   (default)")
    print("path convention: outputs/ = working tree, results/ = published mirror\n")
    for name, spec in COMMANDS.items():
        print(f"  {name:<20} {spec['help']}", flush=True)
        print(f"  {'':<20} -> {spec['script']}"
              + (f"   [out: outputs/research_next_round/<run-id>/{spec['out']}]"
                 if spec["out"] else ""))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("command", nargs="?", help="pipeline stage to run")
    ap.add_argument("--run-id", default=DEFAULT_RUN)
    ap.add_argument("--list", action="store_true", help="list available stages")
    ap.add_argument("--dry-run", action="store_true", help="print the command only")
    args, passthrough = ap.parse_known_args()

    if args.list or not args.command:
        print_list()
        return 0

    spec = COMMANDS.get(args.command)
    if spec is None:
        print(f"unknown command: {args.command!r}", file=sys.stderr)
        print_list()
        return 2

    cmd = [sys.executable, str(REPO / spec["script"])]

    run_root = REPO / "outputs" / "research_next_round" / args.run_id
    if args.command in PATH_ARGS:
        flag, sub = PATH_ARGS[args.command]
        out = run_root / sub
        cmd += [flag, str(out)]
    elif args.command == "manifest":
        cmd += ["--run-id", args.run_id]

    cmd += list(passthrough)

    # flush=True so the header appears BEFORE the child process output in logs
    print(f"[pipeline] stage      : {args.command}", flush=True)
    print(f"[pipeline] working dir: {REPO}", flush=True)
    if args.command in PATH_ARGS:
        print(f"[pipeline] output     : {run_root / PATH_ARGS[args.command][1]}", flush=True)
    print(f"[pipeline] command    : {' '.join(cmd)}", flush=True)
    if args.dry_run:
        return 0

    proc = subprocess.run(cmd, cwd=str(REPO))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
