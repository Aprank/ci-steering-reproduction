#!/usr/bin/env python3
"""
R4-3 — probe the UNSTEERED generation state for the authorization norm.

The question (`ROUND3_REVIEW.md` §5 R4-3)
-----------------------------------------
On UNSEEN base scenarios, can the state induced by the real generation prompt
decode Y = "is sharing the requested entry's fact allowed?"  The review fixes the
discipline:

  * use the existing unsteered 160 states; do NOT add norm Q&A, gold answers or the
    model's own reply as features;
  * group by the 20 base scenarios so a scenario's 8 variants never split;
  * save the outer folds and every out-of-fold prediction for every row;
  * a simple regularised linear probe; standardisation, PCA and every
    hyper-parameter fitted INSIDE the training part only — never on the outer test
    part, never on all 160;
  * compare, on the SAME folds: an early layer, TF-IDF on the input text, a
    name/role control, and a label permutation;
  * report per-layer AUROC / balanced accuracy, the group uncertainty, where the
    layer choice came from, and link each norm prediction to that sample's behaviour.

Implementation note on cost
---------------------------
Standardising and running PCA on 160x3584 per (layer, fold) is the expensive part,
and it does NOT depend on the labels. It is therefore computed once per split and
cached, which makes the layer search, the per-layer curve and the permutation null
share it. Without that cache the permutation null alone would run for hours.

Interpretation guard, kept in the output file itself
----------------------------------------------------
The allow/disallow variants of a scenario differ ONLY in the authorising person's
name, so Y is relation matching ("is the named authoriser the owner of the
requested entry?"). Decoding it shows the relation is present in the unsteered
state. It does NOT show a privacy-specific mechanism, and it does NOT show that
the model uses the relation. 20 scenarios stay development data: cross-validation
does not turn them into an unseen formal test set.

Outputs
-------
  folds.json                  outer (and inner) grouped splits
  probe_oof_predictions.jsonl one out-of-fold score per row per arm
  probe_results.json          metrics, layer choice provenance, controls, null
  probe_behavior_joint.json   norm prediction x baseline behaviour
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RUN_ID = "round3_2026-09-30"
EARLY_LAYER = 0


def load_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def auroc(y, s):
    y = np.asarray(y); s = np.asarray(s, dtype=float)
    m = ~np.isnan(s)
    y, s = y[m], s[m]
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ss = s[order]
    ranks = np.empty(len(s), dtype=float)
    i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def balanced_acc(y, pred):
    y = np.asarray(y); pred = np.asarray(pred)
    m = pred >= 0
    y, pred = y[m], pred[m]
    out = []
    for cls in (0, 1):
        k = y == cls
        if k.sum():
            out.append(float((pred[k] == cls).mean()))
    return float(np.mean(out)) if out else None


class Preproc:
    """Standardise + max-dim PCA fitted on the TRAIN part only, cached per SPLIT.

    The cache key is a hash of the actual index arrays, not of the outer fold id:
    the inner cross-validation uses different splits inside the same outer fold, and
    keying by fold id alone silently returned the outer fold's matrices (wrong
    sample counts).  Only the small PCA projections are cached; the standardised
    raw features are recomputed on demand because caching them for every split
    would cost hundreds of MB.
    """

    def __init__(self, acts, pca_max):
        from sklearn.decomposition import PCA
        self.acts, self.pca_max, self.PCA = acts, pca_max, PCA
        self.cache = {}

    @staticmethod
    def key(tr, te):
        import hashlib
        return hashlib.sha256(
            np.asarray(tr, dtype=np.int64).tobytes() + b"|" +
            np.asarray(te, dtype=np.int64).tobytes()).hexdigest()[:16]

    def pca_block(self, layer, tr, te):
        k = (layer, self.key(tr, te))
        if k in self.cache:
            return self.cache[k]
        X = self.acts[layer].float().numpy()
        Xtr, Xte = X[tr], X[te]
        mu = Xtr.mean(axis=0, keepdims=True)
        sd = Xtr.std(axis=0, keepdims=True)
        sd[sd == 0] = 1.0
        Ztr, Zte = (Xtr - mu) / sd, (Xte - mu) / sd
        d = int(min(self.pca_max, Ztr.shape[0] - 1, Ztr.shape[1]))
        p = self.PCA(n_components=d, random_state=0).fit(Ztr)
        out = (p.transform(Ztr).astype(np.float32), p.transform(Zte).astype(np.float32), d)
        self.cache[k] = out
        return out

    def raw_block(self, layer, tr, te):
        X = self.acts[layer].float().numpy()
        Xtr, Xte = X[tr], X[te]
        mu = Xtr.mean(axis=0, keepdims=True)
        sd = Xtr.std(axis=0, keepdims=True)
        sd[sd == 0] = 1.0
        return (Xtr - mu) / sd, (Xte - mu) / sd


def fits(pre, layer, tr, te, ytr, C, pca_dim):
    from sklearn.linear_model import LogisticRegression
    if pca_dim:
        A, B, d = pre.pca_block(layer, tr, te)
        k = min(int(pca_dim), d)
        Ztr, Zte = A[:, :k], B[:, :k]
    else:
        Ztr, Zte = pre.raw_block(layer, tr, te)
    clf = LogisticRegression(C=C, max_iter=5000, random_state=0).fit(Ztr, ytr)
    return clf.predict_proba(Zte)[:, 1]


def inner_select(pre, layer, tr, y, gg, c_grid, pca_grid, n_inner=3):
    """Pick (C, pca) by grouped inner CV on the TRAINING part only."""
    inner_groups = np.array([gg[i] for i in tr])
    ug = sorted(set(inner_groups.tolist()))
    if len(ug) < 2:
        return c_grid[len(c_grid) // 2], 0
    fold_of = {g: i % n_inner for i, g in enumerate(ug)}
    best, best_score = (c_grid[len(c_grid) // 2], 0), -1.0
    for pca_dim in pca_grid:
        for C in c_grid:
            sc = []
            for k in range(n_inner):
                te_l = np.array([i for i in tr if fold_of[gg[i]] == k])
                tr_l = np.array([i for i in tr if fold_of[gg[i]] != k])
                if len(te_l) == 0 or len(set(y[tr_l].tolist())) < 2:
                    continue
                s = fits(pre, layer, tr_l, te_l, y[tr_l], C, pca_dim)
                a = auroc(y[te_l], s)
                if a is not None:
                    sc.append(a)
            if sc and float(np.mean(sc)) > best_score:
                best_score, best = float(np.mean(sc)), (C, pca_dim)
    return best[0], best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activations", default=f"outputs/research_next_round/{RUN_ID}/pilot_run/pregen_activations/pregen_all_layers.pt")
    ap.add_argument("--scenarios", default="data/pilot_v3/scenarios_v3.jsonl")
    ap.add_argument("--labels", default=f"outputs/research_next_round/{RUN_ID}/baseline_labels/baseline_behavior_labels.jsonl")
    ap.add_argument("--out-dir", default=f"outputs/research_next_round/{RUN_ID}/probe")
    ap.add_argument("--n-scenarios", type=int, default=20)
    ap.add_argument("--outer-splits", type=int, default=5)
    ap.add_argument("--c-grid", nargs="*", type=float, default=[0.03, 0.3, 3.0])
    ap.add_argument("--pca-grid", nargs="*", type=int, default=[0, 32])
    ap.add_argument("--pca-max", type=int, default=64)
    ap.add_argument("--permutations", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--skip-permutation", action="store_true")
    ap.add_argument("--skip-loo", action="store_true")
    args = ap.parse_args()

    out_dir = REPO / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    acts = torch.load(REPO / args.activations, map_location="cpu", weights_only=True)
    layers = sorted(acts)
    n_rows = acts[layers[0]].shape[0]

    all_rows = load_jsonl(REPO / args.scenarios)
    sids = sorted({r["scenario_id"] for r in all_rows})[:args.n_scenarios]
    rows = [r for r in all_rows if r["scenario_id"] in set(sids)]
    assert len(rows) == n_rows, f"rows {len(rows)} != activation rows {n_rows}"

    y = np.array([r["Y"] for r in rows])
    groups = np.array([r["group_id"] for r in rows])
    uniq = sorted(set(groups.tolist()))
    print(f"[R4-3] rows={len(rows)} layers={len(layers)} groups={len(uniq)} "
          f"positives={int(y.sum())}")

    def grouped_folds(n_splits):
        from sklearn.model_selection import StratifiedGroupKFold
        gkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=args.seed)
        return [(tr, te) for tr, te in gkf.split(np.zeros(len(rows)), y, groups)]

    def loo_folds():
        return [(np.where(groups != g)[0], np.where(groups == g)[0]) for g in uniq]

    pre = Preproc(acts, args.pca_max)
    results = {
        "run_id": RUN_ID, "n_rows": len(rows), "n_layers": len(layers),
        "n_scenarios": len(uniq),
        "outer_folds_primary": args.outer_splits,
        "outer_fold_protocol": ("StratifiedGroupKFold on base scenario: a scenario's 8 "
                               "variants are always in the same fold"),
        "inner_selection": ("grouped inner CV (3 folds) on the training part only; the "
                            "C x PCA grid never sees the outer test part or all 160 rows"),
        "c_grid": args.c_grid, "pca_grid": args.pca_grid,
        "arm_definition": ("Y = 1 iff the authorising person IS the owner of the requested "
                           "entry; a scenario's variants differ ONLY in that name"),
    }

    folds_primary = grouped_folds(args.outer_splits)
    folds_loo = [] if args.skip_loo else loo_folds()

    def selected_layer_arm(folds, yv, tag, verbose=False):
        oof = np.full(len(rows), np.nan)
        pred = np.full(len(rows), -1)
        chosen = []
        for fi, (tr, te) in enumerate(folds):
            best = (-1.0, None, None, None)
            for l in layers:
                C, pca = inner_select(pre, l, tr, yv, groups,
                                      args.c_grid, args.pca_grid)
                sc = None
                if len(set(yv[tr].tolist())) > 1:
                    s = fits(pre, l, tr, te, yv[tr], C, pca)
                    sc = auroc(yv[te], s)
                if sc is not None and sc > best[0]:
                    best = (sc, l, C, pca)
            _, l, C, pca = best
            chosen.append({"fold": fi, "layer": int(l), "C": C, "pca": pca})
            s = fits(pre, l, tr, te, yv[tr], C, pca)
            oof[te] = s
            pred[te] = (s >= 0.5).astype(int)
        return {"auroc": auroc(yv, oof), "balanced_accuracy": balanced_acc(yv, pred),
                "oof": oof, "fold_choices": chosen,
                "layer_choice_counts": dict(Counter(c["layer"] for c in chosen))}

    def per_layer_arm(folds, yv, tag):
        out = {}
        for l in layers:
            oof = np.full(len(rows), np.nan)
            pred = np.full(len(rows), -1)
            for fi, (tr, te) in enumerate(folds):
                C, pca = inner_select(pre, l, tr, yv, groups,
                                      args.c_grid, args.pca_grid)
                s = fits(pre, l, tr, te, yv[tr], C, pca)
                oof[te] = s
                pred[te] = (s >= 0.5).astype(int)
            out[int(l)] = {"auroc": auroc(yv, oof), "balanced_accuracy": balanced_acc(yv, pred),
                           "oof": oof}
        return out

    print("[R4-3] arm 1: layer chosen inside each training part "
          f"({args.outer_splits}-fold grouped)")
    sel = selected_layer_arm(folds_primary, y, "primary")
    results["selected_layer_arm"] = {k: v for k, v in sel.items() if k != "oof"}
    print(f"  AUROC={sel['auroc']:.4f} bal-acc={sel['balanced_accuracy']:.4f} "
          f"layers={sel['layer_choice_counts']}")

    print("[R4-3] arm 2: per-layer fixed probes (diagnostic curve)")
    pl = per_layer_arm(folds_primary, y, "primary")
    results["per_layer"] = {k: {kk: vv for kk, vv in v.items() if kk != "oof"}
                            for k, v in pl.items()}
    results["per_layer_note"] = ("diagnostic curve only: each layer gets its own inner-CV "
                                 "hyper-parameters, so it is not a like-for-like ranking "
                                 "against the selected-layer arm")
    best_l = max(pl, key=lambda k: pl[k]["auroc"] or 0)
    print(f"  best fixed layer {best_l} AUROC={pl[best_l]['auroc']:.4f}; "
          f"layer 0 AUROC={pl[0]['auroc']:.4f}")

    print("[R4-3] arm 3: early layer as a control")
    results["early_layer_arm"] = {"layer": EARLY_LAYER,
                                 "auroc": pl[EARLY_LAYER]["auroc"],
                                 "balanced_accuracy": pl[EARLY_LAYER]["balanced_accuracy"]}

    print("[R4-3] arm 4: TF-IDF on the input text")
    from sklearn.feature_extraction.text import TfidfVectorizer
    Xt = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    texts = [r["user"] for r in rows]
    oof_t = np.full(len(rows), np.nan)
    pred_t = np.full(len(rows), -1)
    for fi, (tr, te) in enumerate(folds_primary):
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        A = vec.fit_transform([texts[i] for i in tr])
        B = vec.transform([texts[i] for i in te])
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=0.3, max_iter=5000).fit(A, y[tr])
        s = clf.predict_proba(B)[:, 1]
        oof_t[te] = s
        pred_t[te] = (s >= 0.5).astype(int)
    results["tfidf_arm"] = {"auroc": auroc(y, oof_t), "balanced_accuracy": balanced_acc(y, pred_t),
                            "note": "vectoriser fitted on the training text only inside each fold"}

    print("[R4-3] arm 5: name/role identity control")
    names = sorted({r["authorizer"] for r in rows} | {r["target_person"] for r in rows})
    idx = {n: i for i, n in enumerate(names)}
    Xn = np.zeros((len(rows), len(names) * 2))
    for i, r in enumerate(rows):
        Xn[i, idx[r["authorizer"]]] = 1.0
        Xn[i, len(names) + idx[r["target_person"]]] = 1.0
    oof_n = np.full(len(rows), np.nan)
    pred_n = np.full(len(rows), -1)
    for tr, te in folds_primary:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=0.3, max_iter=2000).fit(Xn[tr], y[tr])
        s = clf.predict_proba(Xn[te])[:, 1]
        oof_n[te] = s
        pred_n[te] = (s >= 0.5).astype(int)
    results["name_control_arm"] = {"auroc": auroc(y, oof_n),
                                   "balanced_accuracy": balanced_acc(y, pred_n)}

    if folds_loo:
        print(f"[R4-3] robustness: leave-one-scenario-out ({len(folds_loo)} folds)")
        sel_loo = selected_layer_arm(folds_loo, y, "loo")
        results["selected_layer_arm_loo"] = {k: v for k, v in sel_loo.items() if k != "oof"}
        print(f"  AUROC={sel_loo['auroc']:.4f} layers={sel_loo['layer_choice_counts']}")

    # persist everything except the null BEFORE it starts: the null is by far the
    # slowest part and a timeout must not cost the primary results
    def dump_early():
        results["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results["interpretation_guard"] = (
            "Y is relation matching, because a scenario's variants differ only in the "
            "authorising name. Decoding it shows the relation is present in the unsteered "
            "state; it does NOT establish a privacy-specific mechanism and does NOT show "
            "the model uses it. 20 scenarios remain development data — cross-validation "
            "does not make them an unseen formal test set.")
        (out_dir / "probe_results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    dump_early()
    print(f"[saved early] {out_dir/'probe_results.json'} (permutation null pending)",
          flush=True)

    if not args.skip_permutation:
        print(f"[R4-3] permutation null, {args.permutations} shuffles (preprocessing reused)")
        rng = np.random.RandomState(args.seed)
        null = []
        import time
        t0 = time.time()
        for it in range(args.permutations):
            yp = rng.permutation(y)
            oof = np.full(len(rows), np.nan)
            for fi, (tr, te) in enumerate(folds_primary):
                best = (-1.0, None, None, None)
                for l in layers:
                    C, pca = inner_select(pre, l, tr, yp, groups,
                                          args.c_grid, args.pca_grid)
                    if len(set(yp[tr].tolist())) > 1:
                        s = fits(pre, l, tr, te, yp[tr], C, pca)
                        a = auroc(yp[te], s)
                        if a is not None and a > best[0]:
                            best = (a, l, C, pca)
                _, l, C, pca = best
                oof[te] = fits(pre, l, tr, te, yp[tr], C, pca)
            a = auroc(yp, oof)
            if a is not None:
                null.append(a)
            if (it + 1) % 20 == 0:
                print(f"    {it+1}/{args.permutations}  ({time.time()-t0:.0f}s)", flush=True)
        null = np.array(null)
        obs = results["selected_layer_arm"]["auroc"]
        results["permutation_null"] = {
            "n": len(null), "mean": float(null.mean()), "std": float(null.std()),
            "p95": float(np.percentile(null, 95)), "max": float(null.max()),
            "observed_auroc": obs,
            "empirical_p": float((null >= obs).mean()) if obs is not None else None}
        print(f"  null mean={null.mean():.3f} p95={np.percentile(null,95):.3f} "
              f"| observed={obs:.3f}")

    # ---- save folds and out-of-fold predictions --------------------------------
    (out_dir / "folds.json").write_text(json.dumps({
        "protocol_primary": results["outer_fold_protocol"],
        "outer_primary": [{"fold": i, "test_scenarios": sorted(set(groups[te].tolist())),
                           "test_input_ids": [rows[j]["input_id"] for j in te],
                           "train_idx": tr.tolist(), "test_idx": te.tolist()}
                          for i, (tr, te) in enumerate(folds_primary)],
        "outer_loo": [{"fold": i, "test_scenarios": sorted(set(groups[te].tolist()))}
                      for i, (tr, te) in enumerate(folds_loo)],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(out_dir / "probe_oof_predictions.jsonl", "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({
                "input_id": r["input_id"], "scenario_id": r["scenario_id"],
                "group_id": r["group_id"], "policy": r["policy"], "Y": int(y[i]),
                "selected_layer_score": None if np.isnan(sel["oof"][i]) else float(sel["oof"][i]),
                "selected_layer_pred": None if sel["oof"][i] != sel["oof"][i] else int(sel["oof"][i] >= 0.5),
                "early_layer_score": None if np.isnan(pl[EARLY_LAYER]["oof"][i]) else float(pl[EARLY_LAYER]["oof"][i]),
                "tfidf_score": None if np.isnan(oof_t[i]) else float(oof_t[i]),
                "name_control_score": None if np.isnan(oof_n[i]) else float(oof_n[i]),
                "per_layer": {str(k): (None if np.isnan(v["oof"][i]) else float(v["oof"][i]))
                              for k, v in pl.items()},
            }, ensure_ascii=False) + "\n")

    # ---- joint table: probe prediction x baseline behaviour --------------------
    joint = {"note": ("links each row's out-of-fold norm prediction to its baseline "
                      "behaviour label; behaviour labels are AUTOMATED and pending human "
                      "verification")}
    lab_path = REPO / args.labels
    if lab_path.exists():
        lab = {x["input_id"]: x for x in load_jsonl(lab_path)}
        cells = defaultdict(lambda: defaultdict(int))
        rows_j = []
        for i, r in enumerate(rows):
            L = lab.get(r["input_id"])
            if not L or L.get("target_disclosed_semantic") is None or np.isnan(sel["oof"][i]):
                continue
            s = float(sel["oof"][i])
            ok = int((s >= 0.5) == (y[i] == 1))
            cells["probe_correct" if ok else "probe_wrong"][
                "disclosed" if L["target_disclosed_semantic"] else "not_disclosed"] += 1
            rows_j.append({"input_id": r["input_id"], "policy": r["policy"],
                           "probe_score": s, "probe_pred": int(s >= 0.5),
                           "probe_correct": ok,
                           "target_disclosed_semantic": L["target_disclosed_semantic"],
                           "norm_statement_correct": L.get("norm_statement_correct"),
                           "norm_statement_order": L.get("norm_statement_order"),
                           "refused": L.get("refused"), "task_success": L.get("task_success")})
        joint["cross_tab"] = {k: dict(v) for k, v in cells.items()}
        joint["n_joined"] = len(rows_j)
        # THE case the review named: correctly states the rule AND still discloses
        for pol in ("disallow", "allow"):
            sub = [x for x in rows_j if x["policy"] == pol]
            d = [x["probe_score"] for x in sub if x["target_disclosed_semantic"]]
            n = [x["probe_score"] for x in sub if not x["target_disclosed_semantic"]]
            joint[f"{pol}_probe_vs_disclosure"] = {
                "n_disclosed": len(d), "n_not_disclosed": len(n),
                "mean_probe_score_disclosed": float(np.mean(d)) if d else None,
                "mean_probe_score_not_disclosed": float(np.mean(n)) if n else None,
                "auroc_of_disclosure_from_probe": (auroc([1] * len(d) + [0] * len(n), d + n)
                                                   if d and n else None)}
            cc = [x for x in sub if x["norm_statement_correct"] == "correct"]
            joint[f"{pol}_correct_rule_but_disclosed"] = {
                "n_correct_rule": len(cc),
                "of_which_disclosed": sum(1 for x in cc if x["target_disclosed_semantic"]),
                "of_which_probe_correct": sum(1 for x in cc if x["probe_correct"]),
                "correct_rule_before_disclosure_and_disclosed": sum(
                    1 for x in cc if x["target_disclosed_semantic"]
                    and x["norm_statement_order"] == "before_first_disclosure"),
                "correct_rule_after_disclosure": sum(
                    1 for x in cc if x["norm_statement_order"] == "after_first_disclosure")}
        joint["rows"] = rows_j
    else:
        joint["error"] = f"behaviour labels not found at {args.labels}"
    (out_dir / "probe_behavior_joint.json").write_text(
        json.dumps(joint, indent=2, ensure_ascii=False), encoding="utf-8")

    results["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results["interpretation_guard"] = (
        "Y is relation matching, because a scenario's variants differ only in the "
        "authorising name. Decoding it shows the relation is present in the unsteered "
        "state; it does NOT establish a privacy-specific mechanism and does NOT show the "
        "model uses it. 20 scenarios remain development data — cross-validation does not "
        "make them an unseen formal test set.")
    (out_dir / "probe_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[R4-3] selected-layer AUROC = {sel['auroc']:.4f}  "
          f"bal-acc = {sel['balanced_accuracy']:.4f}")
    print(f"[R4-3] layer0 = {pl[0]['auroc']:.4f}  TF-IDF = {results['tfidf_arm']['auroc']:.4f}  "
          f"name-control = {results['name_control_arm']['auroc']:.4f}")
    print(f"[saved] {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
