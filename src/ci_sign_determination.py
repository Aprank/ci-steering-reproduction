#!/usr/bin/env python3
"""
Determine the correct orientation (sign) of the three CI steering directions.

The official ci_decomposition.py sets the PCA direction sign arbitrarily
("mean projection > 0"), which does NOT guarantee the direction points toward
privacy protection. To verify Finding 3's *functional* claim (steering reduces
leakage), we exhaustively test all 2^3 = 8 sign combinations of the three
per-parameter directions on the synthetic behavioral stimuli, using a fast
keyword-based leakage metric (secret_keywords) instead of the LLM judge.

This answers: does ANY consistent orientation of the three PCA directions make
CI-parametric steering reduce leakage vs. the unsteered baseline?
"""

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from src.utils.model_utils import load_model, ModelHelper, format_chat_prompt
from src.data.stimulus_generation import PrivacyStimulusGenerator
from src.control.ci_steering import CICompositionalSteering

PARAMS = ["info_type", "recipient", "transmission_principle"]
STEERING_LAYERS = [23, 24, 25, 26, 27]   # Qwen2.5-7B: top-5 deep layers


def keyword_leakage(outputs, stimuli):
    """Fraction of outputs that contain any of the stimulus's secret keywords."""
    n_leak = 0
    for out, s in zip(outputs, stimuli):
        kws = s.get("secret_keywords", [])
        low = out.lower()
        if any(k.lower() in low for k in kws):
            n_leak += 1
    return n_leak / max(len(outputs), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--ci-dir", default="outputs/ci_decomposition/Qwen2.5-7B-Instruct")
    ap.add_argument("--stimuli-dir", default="data/stimuli")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--output-dir", default="outputs/ci_sign_test")
    ap.add_argument("--layers", type=int, nargs="+", default=STEERING_LAYERS)
    args = ap.parse_args()

    model_short = args.model.split("/")[-1]
    out_dir = Path(args.output_dir) / model_short
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading model ...")
    model, tok = load_model(args.model)
    helper = ModelHelper(model, tok)

    # ---- load balanced stimuli; keep only the 100 "protect" (inappropriate) ones ----
    stim = PrivacyStimulusGenerator.load(str(Path(args.stimuli_dir) / "function_stimuli_balanced.json"))
    protect = [s for s in stim if not s["is_appropriate"]][:100]
    prompts = [format_chat_prompt(tok, s["system_msg"], s["user_msg"]) for s in protect]
    print(f"{len(protect)} protect scenarios")

    # ---- load CI directions ----
    dirs = {}
    for p in PARAMS:
        raw = torch.load(f"{args.ci_dir}/ci_{p}_directions.pt", map_location="cpu", weights_only=True)
        dirs[p] = {int(k): v for k, v in raw.items()}

    # ---- baseline ----
    print("\nGenerating unsteered baseline ...")
    base_out = helper.generate(prompts, max_new_tokens=args.max_new_tokens, batch_size=args.batch_size)
    base_leak = keyword_leakage(base_out, protect)
    print(f"baseline keyword-leakage = {base_leak:.3f}")

    # ---- 8 sign combinations ----
    results = {"baseline_keyword_leakage": base_leak, "sign_combos": {}}
    for signs in itertools.product([1.0, -1.0], repeat=3):
        label = {p: ("+" if s > 0 else "-") for p, s in zip(PARAMS, signs)}
        flipped = {
            p: {l: s * d for l, d in dirs[p].items()}
            for p, s in zip(PARAMS, signs)
        }
        steerer = CICompositionalSteering(
            model_helper=helper,
            ci_directions=flipped,
            alphas={p: args.alpha for p in PARAMS},
            steering_layers=args.layers,
            normalize=True,
        )
        outs = steerer.generate(prompts, max_new_tokens=args.max_new_tokens, batch_size=args.batch_size)
        leak = keyword_leakage(outs, protect)
        print(f"  signs {label} -> leakage={leak:.3f} (Δ={leak - base_leak:+.3f})")
        results["sign_combos"][json.dumps(label)] = {
            "leakage": leak,
            "delta_vs_baseline": leak - base_leak,
        }

    # ---- also: single-axis steering for each parameter, both signs ----
    print("\nSingle-axis steering (each param alone, both signs):")
    results["single_axis"] = {}
    for p in PARAMS:
        for s in (1.0, -1.0):
            flipped = {
                q: {l: (s if q == p else 0.0) * d for l, d in dirs[q].items()}
                for q in PARAMS
            }
            steerer = CICompositionalSteering(
                model_helper=helper,
                ci_directions=flipped,
                alphas={q: 1.0 for q in PARAMS},
                steering_layers=args.layers,
                normalize=True,
            )
            outs = steerer.generate(prompts, max_new_tokens=args.max_new_tokens, batch_size=args.batch_size)
            leak = keyword_leakage(outs, protect)
            key = f"{p}{'+' if s > 0 else '-'}"
            print(f"  {key} -> leakage={leak:.3f} (Δ={leak - base_leak:+.3f})")
            results["single_axis"][key] = {
                "leakage": leak,
                "delta_vs_baseline": leak - base_leak,
            }

    with open(out_dir / "sign_test.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_dir / 'sign_test.json'}")


if __name__ == "__main__":
    main()
