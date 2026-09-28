#!/usr/bin/env python3
"""
T3 — corrected LDA cross-projection analysis.

Fixes required by the independent review of the round-1 implementation:
  1. the heat-map used to be drawn from the OLD matrix even when --nested was set;
     here JSON and figure are produced from the same object;
  2. the "original" and "nested" protocols used DIFFERENT folds (cv=5 with the
     default unshuffled split vs StratifiedKFold(shuffle=True)), so the change in
     the off-diagonal could not be attributed to fold-internal fitting. Here BOTH
     protocols share ONE fixed fold assignment, so the only difference is whether
     LDA is re-fit inside each fold;
  3. adds confusion matrices, a permuted-label control, and a check for whether
     the three parameters' stimuli share base scenarios/contexts;
  4. states explicitly that this supports DISCRIMINATIVE SELECTIVITY only, not
     functional or causal independence.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.extraction.activation_extractor import ActivationExtractor
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import LabelEncoder

CI_PARAMS = ["info_type", "recipient", "transmission_principle"]
RUN_ID = "round2_2026-09-29"


def load_param(act_dir: Path, p):
    d = ActivationExtractor.load_activations(str(act_dir / f"ci_{p}"))
    return d["activations"], d["varied_values"], d.get("metadata", [])


def percentile_layer(acts):
    layers = sorted(acts.keys())
    return layers[len(layers) * 3 // 4]


def shared_scenario_check(meta_by_param, acts_by_param, layer):
    """Do the three parameters' stimuli share base scenarios / contexts?"""
    report = {}
    sigs = {}
    for p in CI_PARAMS:
        meta = meta_by_param[p]
        s = []
        for m in meta:
            s.append(json.dumps({k: m.get(k) for k in ("subject", "sender")},
                                sort_keys=True))
        sigs[p] = s
    for i, a in enumerate(CI_PARAMS):
        for b in CI_PARAMS[i + 1:]:
            overlap = len(set(sigs[a]) & set(sigs[b]))
            report[f"{a} vs {b}"] = {
                "n_a": len(sigs[a]), "n_b": len(sigs[b]),
                "shared_subject_sender_signatures": overlap,
                "shared_fraction_of_smaller": overlap / max(min(len(sigs[a]), len(sigs[b])), 1),
            }
    # exact duplicate activation rows across parameters (would indicate shared stimuli)
    arr = {p: acts_by_param[p][layer].float().numpy() for p in CI_PARAMS}
    for i, a in enumerate(CI_PARAMS):
        for b in CI_PARAMS[i + 1:]:
            ha = {hash(r.tobytes()) for r in arr[a]}
            hb = {hash(r.tobytes()) for r in arr[b]}
            report[f"{a} vs {b}"]["identical_activation_rows"] = len(ha & hb)
    return report


def run_protocol(Xi, yi, Xj, yj, folds, nested):
    """One cross-projection cell using an EXPLICIT fold list."""
    accs, cms, preds_all, true_all = [], [], [], []
    for tr, te in folds:
        if nested:
            # LDA re-fit inside the fold: diagonal uses only the train fold;
            # off-diagonal uses parameter j's own (disjoint) samples.
            if Xi is Xj:
                Xj_fit, yj_fit = Xi[tr], yi[tr]
            else:
                Xj_fit, yj_fit = Xj, yj
        else:
            Xj_fit, yj_fit = Xj, yj
        lda = LinearDiscriminantAnalysis(n_components=4)
        lda.fit(Xj_fit, yj_fit)
        Ptr, Pte = lda.transform(Xi[tr]), lda.transform(Xi[te])
        clf = LogisticRegression(max_iter=2000)
        clf.fit(Ptr, yi[tr])
        pred = clf.predict(Pte)
        accs.append(float((pred == yi[te]).mean()))
        cms.append(confusion_matrix(yi[te], pred, labels=list(range(5))).tolist())
        preds_all.extend(pred.tolist())
        true_all.extend(yi[te].tolist())
    cm = confusion_matrix(true_all, preds_all, labels=list(range(5)))
    return {"accuracy": float(np.mean(accs)), "accuracy_std": float(np.std(accs)),
            "fold_accuracies": accs, "confusion_matrix": cm.tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activations-dir", default="outputs/activations/Qwen2.5-7B-Instruct")
    ap.add_argument("--output-dir", default=f"outputs/research_next_round/{RUN_ID}/lda_v2")
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

    layer = percentile_layer(acts[CI_PARAMS[0]])
    print(f"75th-percentile layer = {layer}")

    X = {p: acts[p][layer].float().numpy() for p in CI_PARAMS}
    y = {p: LabelEncoder().fit_transform(vals[p]) for p in CI_PARAMS}

    # ---- do the parameters share scenarios? ----
    shared = shared_scenario_check(meta, acts, layer)
    print("\n=== scenario sharing across parameters ===")
    for k, v in shared.items():
        print(f"  {k}: shared sigs={v['shared_subject_sender_signatures']} "
              f"({v['shared_fraction_of_smaller']:.1%}), identical rows="
              f"{v.get('identical_activation_rows')}")

    # ---- ONE fixed fold assignment reused by both protocols ----
    folds = {}
    for p in CI_PARAMS:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
        folds[p] = list(skf.split(X[p], y[p]))

    results = {
        "run_id": RUN_ID, "layer": layer, "seed": args.seed,
        "folds": "StratifiedKFold(n_splits=5, shuffle=True, random_state=seed) — IDENTICAL for both protocols",
        "protocol_note": ("original = LDA fit once on all data then CV on the projection; "
                          "nested = LDA re-fit inside every fold. Same folds in both, so any "
                          "difference is attributable to fold-internal fitting."),
        "scenario_sharing": shared,
        "matrices": {},
        "permuted_label_control": {},
    }

    print("\n=== cross-projection (same folds for both protocols) ===")
    for tag, nested in (("original", False), ("nested", True)):
        M = np.zeros((3, 3))
        cells = {}
        for i, pi in enumerate(CI_PARAMS):
            for j, pj in enumerate(CI_PARAMS):
                r = run_protocol(X[pi], y[pi], X[pj], y[pj], folds[pi], nested)
                M[i, j] = r["accuracy"]
                cells[f"{pi}->S_{pj}"] = r
                print(f"  [{tag}] {pi:>22s} -> S_{pj:<22s} acc={r['accuracy']:.4f}")
        results["matrices"][tag] = {
            "matrix": M.tolist(),
            "cells": cells,
            "params": CI_PARAMS,
        }

    # ---- permuted-label control (same protocol, shuffled y) ----
    rng = np.random.RandomState(args.seed)
    print("\n=== permuted-label control ===")
    for tag, nested in (("original", False), ("nested", True)):
        M = np.zeros((3, 3))
        for i, pi in enumerate(CI_PARAMS):
            for j, pj in enumerate(CI_PARAMS):
                accs = []
                for rep in range(args.permutations // 20 or 1):
                    yperm = y[pi].copy()
                    rng.shuffle(yperm)
                    f = list(StratifiedKFold(n_splits=5, shuffle=True,
                                             random_state=args.seed + rep)
                             .split(X[pi], yperm))
                    accs.append(run_protocol(X[pi], yperm, X[pj], y[pj], f, nested)["accuracy"])
                M[i, j] = float(np.mean(accs))
        results["permuted_label_control"][tag] = {
            "matrix": M.tolist(), "params": CI_PARAMS,
            "n_permuted_repetitions": (args.permutations // 20 or 1),
            "note": "labels shuffled within the classified parameter; expect ~0.20 everywhere"}
        print(f"  [{tag}] permuted mean acc = {M.mean():.4f}")

    results["interpretation"] = {
        "supports": ("discriminative selectivity of each parameter's LDA subspace within this "
                     "dataset, layer and classifier family"),
        "does_not_support": ("functional independence or causal independence; those require "
                            "intervention experiments that have not been run"),
        "off_diagonal_below_chance": ("investigate via the confusion matrices: systematic "
                                      "misassignment by another parameter's subspace is not "
                                      "'stronger independence'"),
    }

    (out_dir / "lda_v2.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- figure from the SAME matrices as the JSON ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        for ax, tag in zip(axes[:2], ["original", "nested"]):
            M = np.array(results["matrices"][tag]["matrix"])
            im = ax.imshow(M, vmin=0, vmax=1, cmap="viridis")
            ax.set_xticks(range(3)); ax.set_yticks(range(3))
            ax.set_xticklabels([p.replace("_", " ")[:10] for p in CI_PARAMS], rotation=20)
            ax.set_yticklabels([p.replace("_", " ")[:10] for p in CI_PARAMS])
            for i in range(3):
                for j in range(3):
                    ax.text(j, i, f"{M[i,j]*100:.1f}%", ha="center", va="center",
                            color="white" if M[i, j] > 0.5 else "black")
            ax.set_title(f"{tag} protocol (layer {layer})\nsame folds in both panels")
            fig.colorbar(im, ax=ax)
        Mp = np.array(results["permuted_label_control"]["nested"]["matrix"])
        im = axes[2].imshow(Mp, vmin=0, vmax=1, cmap="magma")
        axes[2].set_title("permuted-label control (nested)")
        for i in range(3):
            for j in range(3):
                axes[2].text(j, i, f"{Mp[i,j]*100:.1f}%", ha="center", va="center",
                             color="white" if Mp[i, j] > 0.5 else "black")
        fig.colorbar(im, ax=axes[2])
        fig.tight_layout()
        fig.savefig(out_dir / "lda_v2.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"\n[saved] {out_dir/'lda_v2.png'} (drawn from the same matrices as the JSON)")
    except Exception as e:
        print(f"  (figure skipped: {e})")

    print(f"[saved] {out_dir/'lda_v2.json'}")


if __name__ == "__main__":
    main()
