#!/usr/bin/env python3
"""
T2 — build the final, machine-generated record and statistics for round 1.

Inputs (all IMMUTABLE, never modified):
  outputs/audit_confaide/<model>/per_sample.jsonl          (810 rows, 3 methods x 270)
  outputs/audit_confaide/<model>/rejudge_unknown.json      (19 overlay rows)

Outputs (new, never overwriting the above):
  per_sample.final.jsonl   one row per (method, scenario) with provenance
  summary.final.json       machine-generated main table + paired tables
  consistency_check.json   automatic invariants (also checked against the
                           independently recomputed reference values)

Key rules enforced
  * join on the stable key (run_id, method, scenario_id); (method, i) is kept only
    as a cross-check because a single run is confirmed here;
  * a `cache_hit=False` row is labelled "not found in the historical judge cache",
    NOT "historical parse failure" (the two cannot be distinguished from the
    artefacts we have);
  * the rejudge overlay only carries status/leaked, so `refused`, `appropriate`
    and `raw_content` are marked UNRECOVERABLE for those rows instead of being
    stitched together with stale values;
  * `pair_valid` counts all four cells (00/01/10/11) plus an explicit unknown cell;
  * bootstrap never coerces None to 0;
  * ratios are null when the valid denominator is zero.
"""

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.evaluation.ci_judge_v2 import paired_counts, mcnemar_exact  # noqa: E402

RUN_ID = "round2_2026-09-29"

# Reference values recomputed independently by the reviewer (audit_review/
# independent_recalculation.json). Used ONLY as a merge check.
REFERENCE = {
    "after_rejudge_overlay": {
        "No Steering": {"valid": 270, "unknown": 0, "leaks": 116, "rate": 0.42962962962962964,
                        "cache_hits": 242, "cache_hit_leaks": 96},
        "Standard Steering": {"valid": 270, "unknown": 0, "leaks": 118, "rate": 0.43703703703703706,
                              "cache_hits": 255, "cache_hit_leaks": 107},
        "CI-Parametric (all)": {"valid": 267, "unknown": 3, "leaks": 136,
                                "rate": 0.5093632958801498, "cache_hits": 224,
                                "cache_hit_leaks": 102},
    },
    "paired": {
        "Standard Steering": {"counts": {"00": 146, "01": 8, "10": 6, "11": 110},
                              "valid_pairs": 270, "p": 0.79052734375},
        "CI-Parametric (all)": {"counts": {"00": 113, "01": 38, "10": 18, "11": 98, "unknown": 3},
                                "valid_pairs": 267, "p": 0.010454818321892184},
    },
}


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def load_rows(act_dir: Path):
    rows = []
    with open(act_dir / "per_sample.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rej = {}
    rj_path = act_dir / "rejudge_unknown.json"
    if rj_path.exists():
        for r in json.loads(rj_path.read_text(encoding="utf-8")):
            rej[(r["method"], r["i"])] = r
    return rows, rej


def build_final(rows, rej):
    out = []
    for r in rows:
        method, i = r["method"], r["i"]
        scen = r.get("scenario", {}) or {}
        # stable scenario key: CONFAIDE order is fixed, and we keep a content hash
        content_hash = sha256_text(json.dumps(scen, sort_keys=True, ensure_ascii=False))
        sid = f"confaide_t3_{i:03d}"

        status = r.get("status") or ("valid" if not r.get("error") else "unknown")
        rec = {
            "run_id": RUN_ID,
            "method": method,
            "scenario_id": sid,
            "index_in_order": i,
            "scenario_content_sha256_16": content_hash,
            "topic": scen.get("info_type"),
            "scenario": {"subject": scen.get("subject"),
                         "info_type": scen.get("info_type"),
                         "recipient": scen.get("recipient"),
                         "context": scen.get("context"),
                         "private_info": scen.get("private_info")},
            "meta": r.get("meta"),
            "response": r.get("response"),
            "cache_hit": bool(r.get("cache_hit")),
            "cache_key": r.get("cache_key"),
            "verdict_source": "historical_cache" if r.get("cache_hit") else "historical_new_judgement",
            # v1 semantics: leaked == "revealed or strongly implied the private detail"
            "leaked_v1": r.get("leaked"),
            "refused_v1": r.get("refused"),
            "appropriate_v1": r.get("appropriate"),
            "status": status,
            "recovered_from_rejudge": False,
            "field_level_unrecoverable": [],
        }

        if status != "valid":
            ov = rej.get((method, i))
            if ov and ov.get("rejudge_status") == "valid":
                rec["leaked_v1"] = ov.get("leaked")
                rec["status"] = "valid"
                rec["recovered_from_rejudge"] = True
                rec["verdict_source"] = "rejudge_overlay"
                rec["rejudge_finish_reason"] = ov.get("finish")
                rec["rejudge_reasoning_len"] = ov.get("reason_len")
                # the overlay does not carry these
                rec["refused_v1"] = None
                rec["appropriate_v1"] = None
                rec["field_level_unrecoverable"] = ["refused_v1", "appropriate_v1", "raw_content",
                                                    "confidence", "reasoning"]
            elif ov and ov.get("rejudge_status") == "unknown":
                rec["status"] = "unknown"
                rec["verdict_source"] = "rejudge_overlay_unknown"
                rec["rejudge_finish_reason"] = ov.get("finish")
                rec["field_level_unrecoverable"] = ["leaked_v1", "refused_v1", "appropriate_v1",
                                                    "raw_content"]
            else:
                rec["field_level_unrecoverable"] = ["leaked_v1", "refused_v1", "appropriate_v1",
                                                    "raw_content"]
        out.append(rec)
    return out


def method_summary(recs):
    n = len(recs)
    valid = [r for r in recs if r["status"] == "valid"]
    k = sum(1 for r in valid if r["leaked_v1"] is True)
    cache_hits = [r for r in recs if r["cache_hit"]]
    n_from_rejudge = sum(1 for r in recs if r["recovered_from_rejudge"])
    n_hist_new = sum(1 for r in recs if r["verdict_source"] == "historical_new_judgement")
    return {
        "n": n,
        "n_valid": len(valid),
        "n_unknown": n - len(valid),
        "valid_rate": len(valid) / n if n else None,
        "unknown_rate": (n - len(valid)) / n if n else None,
        "n_leaked_confirmed": k,
        "leak_rate_valid_only": (k / len(valid)) if valid else None,
        # missing-label bounds over ALL n (NOT a confidence interval)
        "leak_bounds_over_all_n": [k / n, (k + (n - len(valid))) / n] if n else None,
        "cache_hits": len(cache_hits),
        "cache_hit_leaks": sum(1 for r in cache_hits if r["leaked_v1"] is True),
        "rows_not_in_historical_cache": n - len(cache_hits),
        "rows_judged_fresh_in_audit": n_hist_new,
        "rows_recovered_from_rejudge": n_from_rejudge,
        "label_provenance": ("automated LLM judge only; NOT human-validated. "
                             "'not found in the historical cache' is not evidence of a "
                             "historical parse failure."),
    }


def story_groups(rows, confaide_dir="data/confaide"):
    """Assign every scenario to a GROUP and prove the grouping is real.

    The reviewer's objection (ROUND2_REVIEW.md, P2) was that `unit="scenario"` was
    only a label: the bootstrap resampled individual scenario pairs while the note
    asserted they were independent.  A cluster bootstrap is only valid if the
    clusters are genuine, so this function derives the cluster from the SOURCE
    story text and reports what it found instead of assuming it.

    Returns (scenario_id -> group_id, independence report).
    """
    from src.data.confaide_loader import ConfaideLoader
    items = ConfaideLoader(str(REPO / confaide_dir)).load_tier3()
    rep = {"n_source_stories": len(items), "grouping_definition":
           "sha256(story text)[:16] of the CONFAIDE Tier-3 item"}

    gid, problems, hash_of = {}, [], {}
    for r in rows:
        sid = r["scenario_id"]
        i = r.get("index_in_order")
        if i is None:
            try:
                i = int(sid.rsplit("_", 1)[1])
            except Exception:
                problems.append((sid, "no index"))
                continue
        if i >= len(items):
            problems.append((sid, f"index {i} out of range"))
            continue
        h = hashlib.sha256(items[i].story.encode()).hexdigest()[:16]
        gid[sid] = h
        hash_of[sid] = h

    sizes = Counter(gid.values())
    multi = {h: n for h, n in sizes.items() if n > 1}
    rep["n_scenarios"] = len(gid)
    rep["n_distinct_story_groups"] = len(sizes)
    rep["groups_with_more_than_one_scenario"] = multi
    rep["duplicate_story_hashes"] = len(multi)
    rep["scenarios_are_independent_units"] = (not multi) and (not problems)
    rep["problems"] = problems[:5]
    rep["note"] = ("If every scenario maps to its own distinct story the per-scenario "
                   "bootstrap IS a cluster bootstrap over story groups; the code now "
                   "resamples groups explicitly so the two cannot drift apart.")
    # a second, looser grouping: same (about, questionee, questioner, topic, secret)
    meta_grp = defaultdict(set)
    for r in rows:
        i = r.get("index_in_order")
        if i is None or i >= len(items):
            continue
        it = items[i]
        meta_grp[(it.about, it.questionee, it.questioner, it.topic, it.secret_topic)].add(
            r["scenario_id"])
    rep["role_topic_secret_groups_with_more_than_one_scenario"] = {
        "|".join(map(str, k)): sorted(v) for k, v in meta_grp.items() if len(v) > 1}

    # Sensitivity grouping: also merge scenarios that share (about, questionee,
    # questioner, topic, secret) even though their stories differ.  Distinct story
    # text does not by itself prove that two items are unrelated, so this is run as
    # an explicit contrast rather than waved away with the word "cluster".
    gid_loose = dict(gid)
    for key, sids in meta_grp.items():
        if len(sids) > 1:
            merged = min(sids)
            for sid in sids:
                gid_loose[sid] = f"MERGED::{merged}"
    rep["n_distinct_groups_loose"] = len(set(gid_loose.values()))
    rep["loose_grouping_reason"] = ("scenarios sharing (about, questionee, questioner, "
                                    "topic, secret) are merged into one cluster")
    return gid, gid_loose, rep


def bootstrap_paired(base, meth, unit="scenario", n_boot=2000, seed=42, groups=None):
    """Cluster bootstrap over the independent unit; None is never coerced.

    `groups` maps scenario_id -> cluster id.  When it is supplied the clusters are
    resampled WITH replacement and every pair inside a sampled cluster is taken,
    which is the correct cluster bootstrap; when a cluster holds several scenarios
    this differs from the naive per-pair resampling that v1 performed while
    claiming to be grouped.
    """
    b = {r["scenario_id"]: r for r in base}
    m = {r["scenario_id"]: r for r in meth}
    pairs = []
    for sid in sorted(set(b) & set(m)):
        vb, vm = b[sid]["leaked_v1"], m[sid]["leaked_v1"]
        pairs.append((sid, vb, vm))
    valid = [(s, vb, vm) for s, vb, vm in pairs if vb is not None and vm is not None]
    if not valid:
        return {"available": False}

    if groups:
        by_group = defaultdict(list)
        for s, vb, vm in valid:
            by_group[groups.get(s, s)].append((s, vb, vm))
    else:
        by_group = {s: [(s, vb, vm)] for s, vb, vm in valid}
    # order clusters by their first scenario id: with all-singleton clusters this
    # makes the grouped and ungrouped draws bit-identical, so the equality check
    # below is a real check rather than an artefact of ordering
    clusters = sorted(by_group, key=lambda c: by_group[c][0][0])

    rng = random.Random(seed)
    deltas = []
    for _ in range(n_boot):
        picked = [clusters[rng.randrange(len(clusters))] for _ in range(len(clusters))]
        sample = [p for c in picked for p in by_group[c]]
        d = sum(1 for _, vb, vm in sample if vm and not vb) - \
            sum(1 for _, vb, vm in sample if vb and not vm)
        deltas.append(d / len(sample))
    deltas.sort()
    observed = (sum(1 for _, vb, vm in valid if vm and not vb) -
                sum(1 for _, vb, vm in valid if vb and not vm)) / len(valid)
    return {
        "available": True,
        "unit": unit,
        "n_valid_pairs": len(valid),
        "n_clusters": len(clusters),
        "cluster_sizes": dict(Counter(len(v) for v in by_group.values())),
        "resampling": ("clusters drawn with replacement; all pairs inside a drawn cluster "
                       "are included" if groups else
                       "one pair per cluster (grouping map not supplied)"),
        "paired_delta_observed": observed,
        "bootstrap_ci95": [deltas[int(0.025 * n_boot)], deltas[int(0.975 * n_boot) - 1]],
        "n_boot": n_boot, "seed": seed,
        "note": ("Cluster bootstrap over distinct CONFAIDE Tier-3 STORIES (see "
                 "independence_check for whether stories really are unique); assumes "
                 "fixed judge labels, not human truth."),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-dir", default="outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct")
    ap.add_argument("--out-dir", default=f"outputs/research_next_round/{RUN_ID}")
    ap.add_argument("--confaide-dir", default="data/confaide")
    args = ap.parse_args()

    act_dir = REPO / args.audit_dir
    out_dir = REPO / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, rej = load_rows(act_dir)
    final = build_final(rows, rej)

    with open(out_dir / "per_sample.final.jsonl", "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[T2] per_sample.final.jsonl: {len(final)} rows")

    by_method = defaultdict(list)
    for r in final:
        by_method[r["method"]].append(r)

    methods = ["No Steering", "Standard Steering", "CI-Parametric (all)"]
    summary = {
        "run_id": RUN_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_dir": args.audit_dir,
        "provenance_note": (
            "Judge labels are automated (DeepSeek v1 protocol) and NOT human-validated. "
            "`leaked_v1` keeps the historical semantics ('reveals or strongly implies the "
            "private detail'). For the 16 overlay-recovered rows only status/leaked survive; "
            "refused/appropriate/raw_content are marked unrecoverable and are NOT stitched "
            "with stale values."),
        "methods": {},
        "paired_vs_No Steering": {},
        "bootstrap_vs_No Steering": {},
    }
    for m in methods:
        summary["methods"][m] = method_summary(by_method[m])

    base = by_method["No Steering"]
    # real story-based groups, plus a report on whether the grouping is genuine
    groups, groups_loose, independence = story_groups(final, args.confaide_dir)
    summary["grouping"] = independence
    for m in methods[1:]:
        pc = paired_counts(
            [{"scenario_id": r["scenario_id"], "leaked_v1": r["leaked_v1"]} for r in base],
            [{"scenario_id": r["scenario_id"], "leaked_v1": r["leaked_v1"]} for r in by_method[m]],
            field_name="leaked_v1")
        summary["paired_vs_No Steering"][m] = pc
        summary["bootstrap_vs_No Steering"][m] = bootstrap_paired(
            base, by_method[m], unit="story", groups=groups)
        summary["bootstrap_per_record_contrast"] = summary.get(
            "bootstrap_per_record_contrast", {})
        summary["bootstrap_per_record_contrast"][m] = bootstrap_paired(
            base, by_method[m], unit="record (unclustered contrast)", groups=None)
        summary.setdefault("bootstrap_loose_groups_sensitivity", {})[m] = bootstrap_paired(
            base, by_method[m], unit="story + role/topic/secret merge", groups=groups_loose)

    # ---- automatic consistency checks vs the independent recalculation ----
    checks = {"invariants": {}, "reference_match": {}}

    inv = checks["invariants"]
    for m in methods:
        ms = summary["methods"][m]
        pc = summary["paired_vs_No Steering"].get(m)
        if pc:
            cellsum = (pc["counts_00_neither"] + pc["counts_01_only_method"] +
                       pc["counts_10_only_baseline"] + pc["counts_11_both"])
            inv[f"{m}: valid_pairs == sum of 4 cells"] = (cellsum == pc["valid_pairs"])
            inv[f"{m}: valid_pairs + unknown == n"] = (pc["valid_pairs"] +
                                                       pc["unknown_pairs"] == ms["n"])
    inv["all_fields"] = all(inv.values())

    # grouping is checked, not asserted: with one distinct story per scenario the
    # cluster bootstrap has exactly one cluster per pair, so grouped and ungrouped
    # resampling must agree numerically — if they ever disagree, the grouping is
    # not what the note claims.
    checks["grouping_independence"] = independence
    inv["stories_are_unique_so_clusters_are_singletons"] = independence[
        "scenarios_are_independent_units"]
    for m in methods[1:]:
        g = summary["bootstrap_vs_No Steering"][m]
        u = summary["bootstrap_per_record_contrast"][m]
        inv[f"{m}: grouped clusters == valid pairs"] = (g["n_clusters"] == g["n_valid_pairs"])
        inv[f"{m}: grouped and ungrouped CI agree"] = (
            g["bootstrap_ci95"] == u["bootstrap_ci95"])
        ls = summary["bootstrap_loose_groups_sensitivity"][m]
        inv[f"{m}: loose-group CI reported"] = ls["available"]
    checks["invariants"] = inv

    for m, ref in REFERENCE["after_rejudge_overlay"].items():
        ms = summary["methods"][m]
        checks["reference_match"][m] = {
            "valid": [ms["n_valid"], ref["valid"], ms["n_valid"] == ref["valid"]],
            "unknown": [ms["n_unknown"], ref["unknown"], ms["n_unknown"] == ref["unknown"]],
            "leaks": [ms["n_leaked_confirmed"], ref["leaks"],
                      ms["n_leaked_confirmed"] == ref["leaks"]],
            "rate": [ms["leak_rate_valid_only"], ref["rate"],
                     ms["leak_rate_valid_only"] is not None and
                     abs(ms["leak_rate_valid_only"] - ref["rate"]) < 1e-9],
            "cache_hits": [ms["cache_hits"], ref["cache_hits"],
                           ms["cache_hits"] == ref["cache_hits"]],
            "cache_hit_leaks": [ms["cache_hit_leaks"], ref["cache_hit_leaks"],
                                ms["cache_hit_leaks"] == ref["cache_hit_leaks"]],
        }
    for m, ref in REFERENCE["paired"].items():
        pc = summary["paired_vs_No Steering"][m]
        got = {"00": pc["counts_00_neither"], "01": pc["counts_01_only_method"],
               "10": pc["counts_10_only_baseline"], "11": pc["counts_11_both"]}
        checks["reference_match"][f"paired:{m}"] = {
            "counts": [got, ref["counts"], all(got[k] == ref["counts"][k] for k in got)],
            "valid_pairs": [pc["valid_pairs"], ref["valid_pairs"],
                            pc["valid_pairs"] == ref["valid_pairs"]],
            "mcnemar_p": [pc["mcnemar_exact_two_sided_p"], ref["p"],
                          pc["mcnemar_exact_two_sided_p"] is not None and
                          abs(pc["mcnemar_exact_two_sided_p"] - ref["p"]) < 1e-9],
        }

    # ---- the historical discrepancy the review flagged ----
    ns = summary["methods"]["No Steering"]
    checks["historical_discrepancy"] = {
        "historical_report_leaks": 104,
        "audit_cache_hit_leaks": ns["cache_hit_leaks"],
        "rows_not_in_historical_cache": ns["rows_not_in_historical_cache"],
        "explained_if_all_misses_were_failures": ns["cache_hit_leaks"],
        "unexplained_leaks": 104 - ns["cache_hit_leaks"],
        "statement": ("Cache misses cannot be equated with historical parse failures: "
                      "the old report recorded 104 baseline leaks while only 96 are present "
                      "among the cache hits, so at least 8 further leaks lived in rows whose "
                      "judge prompt hash does not match today's regeneration (response drift, "
                      "prompt drift or cache gaps). The remainder is NOT fully attributable."),
    }

    (out_dir / "summary.final.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "consistency_check.json").write_text(
        json.dumps(checks, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== summary.final ===")
    for m in methods:
        ms = summary["methods"][m]
        print(f"  {m:<22} valid={ms['n_valid']:>3} unknown={ms['n_unknown']:>2} "
              f"leaks={ms['n_leaked_confirmed']:>3} rate="
              f"{ms['leak_rate_valid_only']:.4f} bounds=[{ms['leak_bounds_over_all_n'][0]:.4f},"
              f"{ms['leak_bounds_over_all_n'][1]:.4f}] cache_hits={ms['cache_hits']} "
              f"cache_hit_leaks={ms['cache_hit_leaks']}")
    for m in methods[1:]:
        pc = summary["paired_vs_No Steering"][m]
        print(f"  paired {m:<22} 00={pc['counts_00_neither']} 01={pc['counts_01_only_method']} "
              f"10={pc['counts_10_only_baseline']} 11={pc['counts_11_both']} "
              f"valid={pc['valid_pairs']} delta={pc['paired_delta']:+.4f} "
              f"p={pc['mcnemar_exact_two_sided_p']:.4g}")
    print(f"\n  invariants all pass: {checks['invariants']['all_fields']}")
    mism = [k for k, v in checks["reference_match"].items()
            if not all(x[2] for x in v.values() if isinstance(x, list) and len(x) == 3)]
    print(f"  reference mismatches: {mism if mism else 'NONE'}")
    print(f"  historical discrepancy: {checks['historical_discrepancy']['statement'][:110]}...")
    print(f"\n[saved] {out_dir/'summary.final.json'}")
    print(f"[saved] {out_dir/'consistency_check.json'}")


if __name__ == "__main__":
    main()
