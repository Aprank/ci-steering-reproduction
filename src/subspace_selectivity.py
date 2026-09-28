#!/usr/bin/env python3
"""
Subspace Selectivity Test — faithful implementation of paper Appendix G / Figure 7.

Verifies Finding 3 ("Privacy Lives in a CI-Aligned Subspace"): the three CI
parameters (info_type, recipient, transmission_principle) occupy functionally
independent subspaces.

The official `ci_decomposition.py` only implements a cosine-similarity +
permutation approximation (and computes the cosine matrix at layer 0, where
the embedding dominates). It does NOT implement the paper's LDA cross-projection.
This script adds the paper's actual test:

  1. Per CI parameter, fit LDA on the full hidden states at the 75th-percentile
     layer -> a 4-dimensional discriminant subspace (5 classes => 4 discriminants).
  2. Cross-projection: project parameter i's stimuli into parameter j's subspace,
     then train a 5-class logistic regression (5-fold CV).
     - diagonal ~100% (own subspace separates own categories)
     - off-diagonal ~20% = 1/5 chance (subspace is NOT informative about other params)
  3. Permutation test on PCA directions at the SAME 75th-percentile layer:
     random partition of all 1500 examples into 3 groups vs. real CI-parameter
     directions (paper: real |cos| should be significantly below the null mean).
"""

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.extraction.activation_extractor import ActivationExtractor
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.decomposition import PCA

CI_PARAMS = ["info_type", "recipient", "transmission_principle"]


def load_param(act_dir: Path, param: str):
    """Load activations + category labels for one CI parameter."""
    data = ActivationExtractor.load_activations(str(act_dir / f"ci_{param}"))
    acts = data["activations"]           # {layer_idx: torch.Tensor (500, d)}
    vals = data["varied_values"]         # list of 500 category strings
    return acts, vals


def percentile_layer(acts) -> int:
    """Return the 75th-percentile layer index (paper Appendix G)."""
    layers = sorted(acts.keys())
    return layers[len(layers) * 3 // 4]


def top_pc(X: np.ndarray) -> np.ndarray:
    """First principal component direction (unit-norm), fast randomized SVD."""
    pca = PCA(n_components=1, svd_solver="randomized", random_state=42)
    pca.fit(X)
    d = pca.components_[0].astype(np.float64)
    return d / np.linalg.norm(d)


def main():
    ap = argparse.ArgumentParser(description="LDA cross-projection selectivity test")
    ap.add_argument("--activations-dir", required=True)
    ap.add_argument("--output-dir", default="outputs/subspace_selectivity")
    ap.add_argument("--n-permutations", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--nested", action="store_true",
                    help="also compute fold-internal (nested) LDA: no test-fold leakage")
    args = ap.parse_args()

    act_dir = Path(args.activations_dir)
    model_name = act_dir.name
    out_dir = Path(args.output_dir) / model_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- load per-parameter activations ----
    acts_by_param, vals_by_param = {}, {}
    for p in CI_PARAMS:
        a, v = load_param(act_dir, p)
        acts_by_param[p] = a
        vals_by_param[p] = v
        print(f"Loaded {p}: {len(v)} samples, {len(set(v))} classes: {sorted(set(v))}")

    # ---- 75th-percentile layer (paper Appendix G) ----
    layer = percentile_layer(acts_by_param[CI_PARAMS[0]])
    print(f"\n75th-percentile layer = {layer}\n")

    # ---- (N, d) matrices at that layer + integer labels ----
    X = {p: acts_by_param[p][layer].float().numpy() for p in CI_PARAMS}
    y = {}
    for p in CI_PARAMS:
        y[p] = LabelEncoder().fit_transform(vals_by_param[p])   # 0..4

    # ================= 1. LDA per parameter =================
    lda_models = {}
    print("Fitting LDA (4-dim discriminant subspace) per parameter ...")
    for p in CI_PARAMS:
        lda = LinearDiscriminantAnalysis(n_components=4)
        lda.fit(X[p], y[p])
        lda_models[p] = lda
        print(f"  {p:>22s}: scalings_.shape={lda.scalings_.shape}")

    # ================= 2. Cross-projection matrix =================
    # (a) ORIGINAL protocol: LDA fit once on all 500 samples, then 5-fold CV on the
    #     projection. For the DIAGONAL this lets LDA see the CV test folds, so the
    #     diagonal is optimistically biased. Kept for comparison.
    # (b) NESTED protocol (--nested): LDA is re-fit inside every fold, so no fold's
    #     test labels ever touch the projection. This is the unbiased estimate.
    print("\nCross-projection selectivity matrix (5-class logistic regression, 5-fold CV):")
    matrix = np.zeros((3, 3))
    matrix_nested = np.zeros((3, 3)) if args.nested else None
    for i, pi in enumerate(CI_PARAMS):
        for j, pj in enumerate(CI_PARAMS):
            proj = lda_models[pj].transform(X[pi])   # project i's data into j's subspace
            clf = LogisticRegression(max_iter=2000)
            acc = cross_val_score(clf, proj, y[pi], cv=5, scoring="accuracy").mean()
            matrix[i, j] = acc
            msg = f"  S_{pi:>22s}  ->  classify {pj:>22s} : acc={acc:.4f}"

            if args.nested:
                skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
                fold_accs = []
                for tr_idx, te_idx in skf.split(X[pi], y[pi]):
                    # diagonal: LDA must be fit on the TRAIN fold only.
                    # off-diagonal: LDA_j uses j's own samples (disjoint from i's).
                    if i == j:
                        Xj, yj = X[pi][tr_idx], y[pi][tr_idx]
                    else:
                        Xj, yj = X[pj], y[pj]
                    lda_in = LinearDiscriminantAnalysis(n_components=4)
                    lda_in.fit(Xj, yj)
                    Ptr = lda_in.transform(X[pi][tr_idx])
                    Pte = lda_in.transform(X[pi][te_idx])
                    clf_in = LogisticRegression(max_iter=2000)
                    clf_in.fit(Ptr, y[pi][tr_idx])
                    fold_accs.append(clf_in.score(Pte, y[pi][te_idx]))
                matrix_nested[i, j] = float(np.mean(fold_accs))
                msg += f" | nested={matrix_nested[i, j]:.4f} (std={np.std(fold_accs):.4f})"
            print(msg)

    # ================= 3. Permutation test (same layer) =================
    print(f"\nPermutation test ({args.n_permutations} permutations, PCA directions) ...")
    real_dirs = [top_pc(X[p]) for p in CI_PARAMS]
    real_cos = [abs(float(np.dot(real_dirs[a], real_dirs[b])))
                for a, b in itertools.combinations(range(3), 2)]
    real_mean = float(np.mean(real_cos))

    pooled = np.concatenate([X[p] for p in CI_PARAMS], axis=0)  # (1500, d)
    n = pooled.shape[0]
    sizes = [X[p].shape[0] for p in CI_PARAMS]
    rng = np.random.RandomState(args.seed)
    null_means = []
    for _ in range(args.n_permutations):
        idx = rng.permutation(n)
        dirs = []
        start = 0
        for sz in sizes:
            dirs.append(top_pc(pooled[idx[start:start + sz]]))
            start += sz
        cs = [abs(float(np.dot(dirs[a], dirs[b])))
              for a, b in itertools.combinations(range(3), 2)]
        null_means.append(float(np.mean(cs)))
    null = np.array(null_means)
    p_value = float(np.mean(null <= real_mean))          # real < null => independence
    effect = float((null.mean() - real_mean) / (null.std() + 1e-10))

    print(f"  real mean |cos| = {real_mean:.4f}")
    print(f"  null mean |cos| = {null.mean():.4f} ± {null.std():.4f}")
    print(f"  p-value (real < null) = {p_value:.4f}")
    print(f"  effect size = {effect:.2f} sigma")

    results = {
        "model": model_name,
        "layer": int(layer),
        "layer_note": "75th-percentile layer (paper Appendix G)",
        "chance_level_5class": 0.2,
        "selectivity_matrix": {
            CI_PARAMS[i]: {CI_PARAMS[j]: float(matrix[i, j]) for j in range(3)}
            for i in range(3)
        },
        "selectivity_matrix_nested": (
            {CI_PARAMS[i]: {CI_PARAMS[j]: float(matrix_nested[i, j]) for j in range(3)}
             for i in range(3)} if matrix_nested is not None else None
        ),
        "protocol": ("nested = LDA re-fit inside every fold (unbiased); "
                     "selectivity_matrix = LDA fit on full data (optimistic diagonal)"),
        "permutation_test": {
            "real_mean_abs_cosine": real_mean,
            "null_mean": float(null.mean()),
            "null_std": float(null.std()),
            "p_value": p_value,
            "effect_size_sigma": effect,
            "n_permutations": args.n_permutations,
            "seed": args.seed,
        },
    }

    with open(out_dir / "subspace_selectivity.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_dir / 'subspace_selectivity.json'}")

    # ---- heatmap (Figure 7 style) ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6.5, 5))
        im = ax.imshow(matrix, vmin=0, vmax=1, cmap="viridis")
        ax.set_xticks(range(3)); ax.set_yticks(range(3))
        ax.set_xticklabels([p.replace("_", " ").title() for p in CI_PARAMS])
        ax.set_yticklabels([p.replace("_", " ").title() for p in CI_PARAMS])
        ax.set_xlabel("Subspace used for projection")
        ax.set_ylabel("Parameter being classified")
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{matrix[i, j]*100:.0f}%", ha="center", va="center",
                        color="white" if matrix[i, j] > 0.5 else "black")
        ax.set_title(f"LDA Cross-Projection Selectivity (layer {layer})")
        fig.colorbar(im, ax=ax, label="5-class accuracy")
        fig.tight_layout()
        fig.savefig(out_dir / "subspace_selectivity.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {out_dir / 'subspace_selectivity.png'}")
    except Exception as e:
        print(f"  (heatmap skipped: {e})")


if __name__ == "__main__":
    main()
