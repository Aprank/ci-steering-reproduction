#!/usr/bin/env python3
"""
T8.4 — LDA cross-projection with JOINT groups across the three CI parameters.

What the second review found (`ROUND2_REVIEW.md`, P2 "LDA and bootstrap grouping")
-------------------------------------------------------------------------------
* `subspace_selectivity_v2.py:142` still used `StratifiedKFold`, not a split grouped
  by scenario/template.
* the off-diagonal cell fitted the projection LDA on the OTHER parameter's ENTIRE
  dataset, so a test sample's own base scenario could be in the fit set.

What this script establishes first (not assumed)
------------------------------------------------
`src/verify_grouping_claims.py` measured the three stimulus sets:
  * all three share the same 69 (subject, sender) actor pairs;
  * `recipient` and `transmission_principle` share 94 of 94 base scenarios (100%);
  * `info_type` contains those same 94, out of its 345 base scenarios;
  * 16 identical activation rows between info_type and each of the other two, 16
    between recipient and transmission_principle.
So the three "parameter datasets" are NOT independent samples, and every protocol
here is run under a joint group so that a test scenario and ALL of its parameter
variants stay out of every fit.

Group definitions
-----------------
  group_loose  = (subject, sender)                ->  69 groups
  group_strict = (subject, sender, fact phrase)   -> 345 groups
`group_loose` is the conservative primary because it also holds out variants that
merely share the two actors; `group_strict` is reported alongside it.

Protocols per cell (i projected through a discriminant fitted on j)
-------------------------------------------------------------------
  ungrouped   fit on ALL of j                          (the v2 behaviour — diagnostic only)
  group_excl  fit on j with test groups REMOVED         (primary)
  nested      fit on j restricted to i's train groups   (strictest)

Assertions are recorded, not assumed: for every cell the script checks that no
group present in the test fold was used to fit the projection.

Caveat kept in the output: this supports DISCRIMINATIVE selectivity only. It says
nothing about functional or causal independence.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.extraction.activation_extractor import ActivationExtractor
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import LabelEncoder

CI_PARAMS = ["info_type", "recipient", "transmission_principle"]
RUN_ID = "round3_2026-09-30"

RX = re.compile(
    r"^(?P<sender>.+?) knows that (?P<subject>.+?) has (?P<fact>.+?)\. "
    r"(?P<recip>.+?) asks (?P<sender2>.+?) about (?P<subject2>.+?)'s (?P<topic>.+?)\. "
    r"(?P<tp>.+?)\.$"
)


def load_param(act_dir: Path, p):
    d = ActivationExtractor.load_activations(str(act_dir / f"ci_{p}"))
    return d["activations"], d["varied_values"], d.get("metadata", [])


def percentile_layer(acts):
    layers = sorted(acts.keys())
    return layers[len(layers) * 3 // 4]


def groups_for(meta, level):
    out = []
    for m in meta:
        g = RX.match(m["text"])
        if not g:
            out.append("UNPARSED|" + m["text"][:60])
            continue
        if level == "loose":
            out.append(f"{g.group('subject')}|{g.group('sender')}")
        else:
            out.append(f"{g.group('subject')}|{g.group('sender')}|{g.group('fact')}")
    return np.array(out, dtype=object)


def shared_scenario_check(meta, acts, layer):
    report = {}
    sigs = {p: [json.dumps({k: m.get(k) for k in ("subject", "sender")}, sort_keys=True)
                for m in meta[p]] for p in CI_PARAMS}
    for i, a in enumerate(CI_PARAMS):
        for b in CI_PARAMS[i + 1:]:
            ov = len(set(sigs[a]) & set(sigs[b]))
            report[f"{a} vs {b}"] = {
                "n_a": len(sigs[a]), "n_b": len(sigs[b]),
                "shared_subject_sender_signatures": ov,
                "shared_fraction_of_smaller": ov / max(min(len(sigs[a]), len(sigs[b])), 1),
            }
    arr = {p: acts[p][layer].float().numpy() for p in CI_PARAMS}
    for i, a in enumerate(CI_PARAMS):
        for b in CI_PARAMS[i + 1:]:
            ha = {r.tobytes() for r in arr[a]}
            hb = {r.tobytes() for r in arr[b]}
            report[f"{a} vs {b}"]["identical_activation_rows"] = len(ha & hb)
    return report


def run_cell(Xi, yi, gi, gj, Xj, yj, folds, protocol, test_groups_of_fold):
    """One cross-projection cell with an explicit fold list and grouping policy.

    Returns accuracy plus an assertion record showing that the fit set and the test
    set share no group.  Cells whose fit set cannot support 5 classes are reported
    as unavailable instead of crashing the run.
    """
    accs, preds_all, true_all = [], [], []
    violations = 0
    fit_sizes, fit_class_counts, degenerate = [], [], []
    for k, (tr, te) in enumerate(folds):
        test_groups = test_groups_of_fold[k]
        if protocol == "ungrouped":
            fit_mask = np.ones(len(Xj), dtype=bool)          # v2 behaviour
        elif protocol == "group_excl":
            fit_mask = np.array([g not in test_groups for g in gj])
        elif protocol == "nested":
            # `tr` indexes parameter i's rows, so the TRAIN GROUPS must be read from
            # i's group array — reading them from gj (parameter j) would address the
            # wrong rows and silently let test groups into the fit set
            train_groups = set(gi[tr])
            fit_mask = np.array([g in train_groups for g in gj])
        else:
            raise ValueError(protocol)

        # assertion: no test group survives inside the fit set
        leaked = {g for g in gj[fit_mask]} & test_groups
        if leaked:
            violations += 1
        fit_sizes.append(int(fit_mask.sum()))
        n_fit_classes = len(set(yj[fit_mask].tolist()))
        n_tr_classes = len(set(yi[tr].tolist()))
        fit_class_counts.append(n_fit_classes)
        if n_fit_classes < 5 or n_tr_classes < 2:
            degenerate.append({"fold": k, "fit_classes": n_fit_classes,
                               "train_classes": n_tr_classes})
            continue

        lda = LinearDiscriminantAnalysis(n_components=min(4, n_fit_classes - 1))
        lda.fit(Xj[fit_mask], yj[fit_mask])
        clf = LogisticRegression(max_iter=2000)
        clf.fit(lda.transform(Xi[tr]), yi[tr])
        pred = clf.predict(lda.transform(Xi[te]))
        accs.append(float((pred == yi[te]).mean()))
        preds_all.extend(pred.tolist())
        true_all.extend(yi[te].tolist())

    cm = confusion_matrix(true_all, preds_all, labels=list(range(5))) if true_all else None
    return {"available": bool(accs),
            "accuracy": float(np.mean(accs)) if accs else None,
            "accuracy_std": float(np.std(accs)) if accs else None,
            "fold_accuracies": accs, "confusion_matrix": cm.tolist() if cm is not None else None,
            "n_folds_used": len(accs), "n_folds_total": len(folds),
            "fit_set_sizes": fit_sizes, "fit_set_class_counts": fit_class_counts,
            "degenerate_folds": degenerate,
            "group_leak_violations": violations,
            "assertion_no_test_group_in_fit": violations == 0}



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activations-dir", default="outputs/activations/Qwen2.5-7B-Instruct")
    ap.add_argument("--output-dir", default=f"outputs/research_next_round/{RUN_ID}/lda_v3")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--permutations", type=int, default=200)
    args = ap.parse_args()

    act_dir = Path(args.activations_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    acts, vals, meta = {}, {}, {}
    for p in CI_PARAMS:
        a, v, m = load_param(act_dir, p)
        acts[p], vals[p], meta[p] = a, v, m
        print(f"loaded {p}: {len(v)} samples, classes={sorted(set(v))}")

    layers = sorted(acts[CI_PARAMS[0]])
    layer = percentile_layer(acts[CI_PARAMS[0]])
    print(f"75th-percentile layer = {layer}")

    X = {p: acts[p][layer].float().numpy() for p in CI_PARAMS}
    y = {p: LabelEncoder().fit_transform(vals[p]) for p in CI_PARAMS}

    shared = shared_scenario_check(meta, acts, layer)
    print("\n=== scenario sharing across parameters ===")
    for k, v in shared.items():
        print(f"  {k}: shared actor sigs={v['shared_subject_sender_signatures']} "
              f"({v['shared_fraction_of_smaller']:.1%}), identical rows="
              f"{v.get('identical_activation_rows')}")

    results = {
        "run_id": RUN_ID, "layer": layer, "seed": args.seed,
        "layer_selection_caveat": (
            "the 75th-percentile layer is a hyper-parameter chosen on the SAME data; "
            "the layer_robustness block below repeats the matrix at other layers"),
        "scenario_sharing": shared,
        "grouping": {},
        "matrices": {},
        "layer_robustness": {},
        "permuted_label_control": {},
        "selectivity_caveat": ("supports DISCRIMINATIVE selectivity only; not functional "
                               "or causal independence"),
    }

    protocols = ["ungrouped", "group_excl", "nested"]

    for level in ("loose", "strict"):
        G = {p: groups_for(meta[p], level) for p in CI_PARAMS}
        n_groups = {p: len(set(G[p])) for p in CI_PARAMS}
        joint = set(G[CI_PARAMS[0]]) | set(G[CI_PARAMS[1]]) | set(G[CI_PARAMS[2]])
        inter = set(G[CI_PARAMS[0]]) & set(G[CI_PARAMS[1]]) & set(G[CI_PARAMS[2]])
        results["grouping"][level] = {
            "definition": "(subject, sender)" if level == "loose" else "(subject, sender, fact)",
            "n_groups_per_param": n_groups,
            "n_groups_joint_union": len(joint),
            "n_groups_in_all_three_params": len(inter),
            "sample_counts": {p: len(G[p]) for p in CI_PARAMS},
        }
        print(f"\n=== grouping {level}: {n_groups}  joint union={len(joint)} "
              f"in-all-three={len(inter)} ===")

        # ONE fixed grouped fold assignment per parameter, reused by every protocol
        folds, test_groups_of_fold = {}, {}
        for p in CI_PARAMS:
            np_ = min(5, len(set(G[p])))
            gkf = StratifiedGroupKFold(n_splits=np_, shuffle=True, random_state=args.seed)
            fl, tg = [], []
            for tr, te in gkf.split(X[p], y[p], G[p]):
                fl.append((tr, te))
                tg.append(set(G[p][te]))
            folds[p], test_groups_of_fold[p] = fl, tg
        results["grouping"][level]["fold_protocol"] = (
            f"StratifiedGroupKFold(n_splits=5, shuffle=True, seed={args.seed}) on {level} "
            f"groups — IDENTICAL for every protocol; stratified so no class can vanish "
            f"from a train fold")

        for protocol in protocols:
            M = np.zeros((3, 3))
            cells = {}
            for i, pi in enumerate(CI_PARAMS):
                for j, pj in enumerate(CI_PARAMS):
                    r = run_cell(X[pi], y[pi], G[pi], G[pj], X[pj], y[pj], folds[pi],
                                 protocol, test_groups_of_fold[pi])
                    M[i, j] = r["accuracy"] if r["accuracy"] is not None else np.nan
                    cells[f"{pi}->S_{pj}"] = r
            off = [M[i, j] for i in range(3) for j in range(3) if i != j and not np.isnan(M[i, j])]
            diag = [M[i, i] for i in range(3)]
            results["matrices"][f"{level}_{protocol}"] = {
                "matrix": [[None if np.isnan(x) else float(x) for x in row] for row in M],
                "params": CI_PARAMS,
                "cell_accuracy": {k: v["accuracy"] for k, v in cells.items()},
                "diagonal": [None if np.isnan(x) else float(x) for x in diag],
                "offdiagonal_mean": float(np.mean(off)) if off else None,
                "offdiagonal_max": float(np.max(off)) if off else None,
                "n_cells_available": int(np.sum(~np.isnan(M))),
                "all_assertions_hold": all(v["assertion_no_test_group_in_fit"]
                                           for v in cells.values()),
                "degenerate_cells": {k: v["degenerate_folds"] for k, v in cells.items()
                                     if v["degenerate_folds"]},
                "cells": cells,
            }
            blk = results["matrices"][f"{level}_{protocol}"]
            print(f"  [{level}/{protocol}] diag={[None if x is None else round(x, 4) for x in blk['diagonal']]} "
                  f"offdiag_mean={blk['offdiagonal_mean'] if blk['offdiagonal_mean'] is None else round(blk['offdiagonal_mean'], 4)} "
                  f"cells={blk['n_cells_available']}/9 "
                  f"assert={blk['all_assertions_hold']}")

    # ---- layer robustness (the layer was chosen on the same data) ----------
    print("\n=== layer robustness (loose/group_excl) ===")
    for lyr in [layers[0], layers[len(layers) // 4], layers[len(layers) // 2], layer, layers[-1]]:
        Xl = {p: acts[p][lyr].float().numpy() for p in CI_PARAMS}
        Gl = {p: groups_for(meta[p], "loose") for p in CI_PARAMS}
        fl, tg = {}, {}
        for p in CI_PARAMS:
            gkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=args.seed)
            fl[p], tg[p] = [], []
            for tr, te in gkf.split(Xl[p], y[p], Gl[p]):
                fl[p].append((tr, te))
                tg[p].append(set(Gl[p][te]))
        M = np.full((3, 3), np.nan)
        for i, pi in enumerate(CI_PARAMS):
            for j, pj in enumerate(CI_PARAMS):
                a = run_cell(Xl[pi], y[pi], Gl[pi], Gl[pj], Xl[pj], y[pj], fl[pi],
                             "group_excl", tg[pi])["accuracy"]
                if a is not None:
                    M[i, j] = a
        off = [M[i, j] for i in range(3) for j in range(3) if i != j and not np.isnan(M[i, j])]
        results["layer_robustness"][str(lyr)] = {
            "matrix": [[None if np.isnan(x) else float(x) for x in row] for row in M],
            "diagonal": [None if np.isnan(M[i, i]) else float(M[i, i]) for i in range(3)],
            "offdiagonal_mean": float(np.mean(off)) if off else None,
            "offdiagonal_max": float(np.max(off)) if off else None}
        print(f"  layer {lyr:>3}: diag={[None if np.isnan(M[i,i]) else round(float(M[i,i]),4) for i in range(3)]} "
              f"offdiag_mean={np.mean(off) if off else None}")

    # ---- persist the primary results BEFORE the slow control ----------------
    # The permuted-label control is thousands of LDA fits. Writing the main
    # matrices first means a timeout or a kill cannot cost the primary result.
    def dump():
        (out_dir / "lda_v3.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    dump()
    print(f"[saved early] {out_dir/'lda_v3.json'} (permuted control pending)")

    # ---- permuted-label control, loose/group_excl --------------------------
    rng = np.random.RandomState(args.seed)
    perms = []
    G = {p: groups_for(meta[p], "loose") for p in CI_PARAMS}
    folds, test_groups_of_fold = {}, {}
    for p in CI_PARAMS:
        gkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=args.seed)
        folds[p], test_groups_of_fold[p] = [], []
        for tr, te in gkf.split(X[p], y[p], G[p]):
            folds[p].append((tr, te))
            test_groups_of_fold[p].append(set(G[p][te]))
    t_perm = time.time()
    for it in range(args.permutations):
        yp = {p: rng.permutation(y[p]) for p in CI_PARAMS}
        M = np.full((3, 3), np.nan)

        for i, pi in enumerate(CI_PARAMS):
            for j, pj in enumerate(CI_PARAMS):
                a = run_cell(X[pi], yp[pi], G[pi], G[pj], X[pj], yp[pj], folds[pi],
                             "group_excl", test_groups_of_fold[pi])["accuracy"]
                if a is not None:
                    M[i, j] = a
        row = [M[i, i] for i in range(3)] + [M[i, j] for i in range(3)
                                             for j in range(3) if i != j]
        if any(np.isnan(row)):
            continue
        perms.append([float(x) for x in row])
        if (it + 1) % 40 == 0:
            print(f"  permuted-label control {it+1}/{args.permutations}")
    perms = np.array(perms)
    results["permuted_label_control"] = {
        "seconds_total": round(time.time() - t_perm, 1),
        "seconds_per_permutation": round((time.time() - t_perm) / max(args.permutations, 1), 2),
        "protocol": "loose/group_excl, labels permuted within each parameter",
        "n_permutations": args.permutations,
        "diagonal_mean": perms[:, :3].mean(axis=0).tolist(),
        "offdiagonal_mean": float(perms[:, 3:].mean()),
        "chance_reference": 0.2,
    }
    print(f"  permuted: diag_mean={np.round(perms[:, :3].mean(axis=0), 3).tolist()} "
          f"offdiag_mean={perms[:, 3:].mean():.4f}")

    (out_dir / "lda_v3.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    print(f"\n[saved] {out_dir/'lda_v3.json'}")

    # figure from the SAME object as the JSON (all protocols, loose grouping)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 3, figsize=(16, 5))
        for ax, protocol in zip(axes, protocols):
            blk = results["matrices"][f"loose_{protocol}"]
            im = ax.imshow(np.array(blk["matrix"]), vmin=0, vmax=1, cmap="viridis")
            ax.set_title(f"loose / {protocol}\noff-diag mean "
                         f"{blk['offdiagonal_mean']:.3f}", fontsize=10)
            ax.set_xticks(range(3)); ax.set_yticks(range(3))
            ax.set_xticklabels(CI_PARAMS, rotation=45, ha="right", fontsize=7)
            ax.set_yticklabels(CI_PARAMS, fontsize=7)
            for i in range(3):
                for j in range(3):
                    ax.text(j, i, f"{blk['matrix'][i][j]:.3f}", ha="center", va="center",
                            color="w", fontsize=8)
            fig.colorbar(im, ax=ax, fraction=0.046)
        fig.suptitle("Cross-projection LDA with JOINT groups (row = probe parameter, "
                     "column = discriminant source)", fontsize=11)
        fig.tight_layout()
        fig.savefig(out_dir / "lda_v3.png", dpi=140)
        print(f"[saved] {out_dir/'lda_v3.png'}")
    except Exception as e:
        print(f"[warn] figure not written: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
