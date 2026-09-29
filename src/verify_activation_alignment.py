#!/usr/bin/env python3
"""
R4-1 — verify that the captured activations really correspond to the inputs that
were generated, and freeze that correspondence.

Why this exists (`ROUND3_REVIEW.md` §4.4)
----------------------------------------
`ModelHelper.get_activations()` tokenises with `max_length=512` while
`ModelHelper.generate()` uses `max_length=1024`.  If any prompt exceeded 512
tokens the pre-generation state would belong to a TRUNCATED input while the reply
belonged to the full input — the activation row and the behaviour would not be
about the same thing.  The review asked for this to be checked rather than
assumed, and for the alignment to be recorded so that later probe work cannot
quietly use mismatched rows.

Also recorded here, at the reviewer's request:
  * the effective token count under BOTH limits, and which prompts truncate;
  * a hash of the effective input ids per row (so a row can be re-matched later);
  * the row index -> input_id mapping;
  * an explicit statement that this single capture is the UNSTEERED input state,
    before any steering hook is attached, so it belongs with the No Steering
    replies and must NOT be described as a post-intervention state.

Outputs
-------
  activation_manifest.json   config, limits, hashes, alignment verdict
  activation_rows.jsonl      one line per activation row: row index, input_id,
                             token count, truncated-under-512 flag, input hash
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RUN_ID = "round3_2026-09-30"
ACT_LIMIT = 512      # ModelHelper.get_activations default
GEN_LIMIT = 1024     # ModelHelper.generate default


def load_jsonl(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="data/pilot_v3/scenarios_v3.jsonl")
    ap.add_argument("--n-scenarios", type=int, default=20)
    ap.add_argument("--responses", default=f"outputs/research_next_round/{RUN_ID}/pilot_run/responses.jsonl")
    ap.add_argument("--act-file", default=f"outputs/research_next_round/{RUN_ID}/pilot_run/pregen_activations/pregen_all_layers.pt")
    ap.add_argument("--out-dir", default=f"outputs/research_next_round/{RUN_ID}/activation_alignment")
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    args = ap.parse_args()

    out_dir = REPO / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows = load_jsonl(REPO / args.scenarios)
    sids = sorted({r["scenario_id"] for r in all_rows})[:args.n_scenarios]
    rows = [r for r in all_rows if r["scenario_id"] in set(sids)]

    # ---- rebuild the exact prompt strings the run used ----------------------
    from transformers import AutoTokenizer
    from src.utils.model_utils import format_chat_prompt

    tok = AutoTokenizer.from_pretrained(args.model, padding_side="left")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    prompts = [format_chat_prompt(tok, r["system"], r["user"]) for r in rows]

    print(f"[R4-1] rows={len(rows)} model={args.model}")

    per_row = []
    for i, (r, p) in enumerate(zip(rows, prompts)):
        # tokenise WITHOUT truncation to learn the true length
        full = tok(p, return_tensors=None)["input_ids"]
        n_full = len(full)
        # and exactly the way each consumer does it
        enc_act = tok([p], return_tensors="pt", padding=True, truncation=True,
                      max_length=ACT_LIMIT)
        enc_gen = tok([p], return_tensors="pt", padding=True, truncation=True,
                      max_length=GEN_LIMIT)
        ids_act = enc_act["input_ids"][0].tolist()
        ids_gen = enc_gen["input_ids"][0].tolist()
        # the activation is taken at the LAST real token; with left padding that is
        # index -1.  What matters for alignment is whether the two consumers saw the
        # same token sequence, and whether the last real token is the same token.
        same_ids = ids_act == ids_gen
        per_row.append({
            "row_index": i,
            "input_id": r["input_id"],
            "scenario_id": r["scenario_id"],
            "group_id": r["group_id"],
            "policy": r["policy"],
            "Y": r["Y"],
            "task_strength": r["task_strength"],
            "n_tokens_true": n_full,
            "n_tokens_act_limit": len(ids_act),
            "n_tokens_gen_limit": len(ids_gen),
            "truncated_under_512": n_full > ACT_LIMIT,
            "truncated_under_1024": n_full > GEN_LIMIT,
            "input_ids_identical_both_limits": same_ids,
            "last_effective_token_id": ids_act[-1],
            "effective_input_sha256_16": hashlib.sha256(
                ",".join(map(str, ids_act)).encode()).hexdigest()[:16],
            "activation_available_in": None,   # filled below
        })

    # ---- check the tensor really has one row per input, in this order --------
    import torch
    act_path = REPO / args.act_file
    act_info = {"file": str(args.act_file), "found": act_path.exists()}
    if act_path.exists():
        acts = torch.load(act_path, map_location="cpu", weights_only=True)
        layers = sorted(acts)
        shapes = {layers[0]: list(acts[layers[0]].shape), layers[-1]: list(acts[layers[-1]].shape)}
        n_rows = acts[layers[0]].shape[0]
        act_info.update({"layers": len(layers), "layer_ids": layers, "end_shapes": shapes,
                         "n_rows": n_rows,
                         "file_sha256_16": hashlib.sha256(act_path.read_bytes()).hexdigest()[:16],
                         "file_bytes": act_path.stat().st_size})
        consistent = all(acts[l].shape[0] == n_rows for l in layers)
        act_info["all_layers_same_n_rows"] = consistent
        for r in per_row:
            r["activation_available_in"] = str(args.act_file)
    else:
        act_info["note"] = "tensor not present in this environment"

    # ---- the alignment verdict ---------------------------------------------
    truncated = [r["input_id"] for r in per_row if r["truncated_under_512"]]
    mismatched = [r["input_id"] for r in per_row if not r["input_ids_identical_both_limits"]]
    n_rows = act_info.get("n_rows")
    verdict = {
        "n_inputs": len(per_row),
        "n_truncated_under_512": len(truncated),
        "truncated_input_ids": truncated[:20],
        "n_input_ids_mismatched_between_limits": len(mismatched),
        "mismatched_input_ids": mismatched[:20],
        "tensor_rows": n_rows,
        "tensor_rows_match_inputs": (n_rows == len(per_row)) if n_rows is not None else None,
        "activations_reusable_as_is": (
            len(truncated) == 0 and len(mismatched) == 0
            and (n_rows == len(per_row) if n_rows is not None else False)),
        "token_position": ("last real token; padding_side='left', so the last real "
                           "token is at index -1 for every row"),
        "state_semantics": ("this capture is the UNSTEERED input state — it is taken "
                            "before any steering hook is attached, so it pairs with the "
                            "No Steering replies ONLY and must not be described as a "
                            "post-intervention state"),
    }
    verdict["conclusion"] = (
        "no prompt reaches the 512-token activation limit and both consumers see the "
        "same input ids, so the existing capture can be reused without re-running "
        "the model"
        if verdict["activations_reusable_as_is"] else
        "at least one input is truncated or misaligned; the affected rows must be "
        "re-captured with the generation limits and must not enter probe analysis")

    # ---- generation-side token accounting ---------------------------------
    gen_info = {"responses_file": str(args.responses), "found": (REPO / args.responses).exists()}
    if gen_info["found"]:
        resp = load_jsonl(REPO / args.responses)
        base = {r["input_id"]: r for r in resp if r["condition"] == "No Steering"}
        lens, est_cap, true_cap, finish = [], [], [], Counter()
        for r in per_row:
            x = base.get(r["input_id"])
            if not x:
                continue
            n = len(tok(x["response"], return_tensors=None)["input_ids"])
            lens.append(n)
            if n >= 256:
                est_cap.append(r["input_id"])
            # prefer the recorded termination reason (run 2 onwards)
            if x.get("hit_max_new_tokens") is not None:
                if x["hit_max_new_tokens"]:
                    true_cap.append(r["input_id"])
                finish[x.get("finish_reason")] += 1
        gen_info.update({
            "n_responses": len(lens),
            "response_token_min": min(lens) if lens else None,
            "response_token_max": max(lens) if lens else None,
            "response_token_mean": round(sum(lens) / len(lens), 1) if lens else None,
            "n_estimated_at_cap_by_re_tokenisation": len(est_cap),
            "n_true_hit_max_new_tokens": len(true_cap) if finish else None,
            "finish_reason_counts": dict(finish) if finish else None,
            "true_cap_ids": true_cap[:20],
            "cap_note": ("re-tokenising a decoded reply UNDERSTATES truncation: decoding "
                         "strips special tokens and re-encoding can merge subwords. The "
                         "recorded termination reason is authoritative. Non-empty output "
                         "cannot rule out truncation, and a truncated reply's disclosure "
                         "and task success are censored."),
        })

    manifest = {
        "run_id": RUN_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tokenizer": args.model,
        "activation_max_length": ACT_LIMIT,
        "generation_max_length": GEN_LIMIT,
        "padding_side": "left",
        "prompt_source": str(args.scenarios),
        "n_scenarios": len(sids), "scenarios": sids,
        "activation_tensor": act_info,
        "generation": gen_info,
        "alignment": verdict,
        "why_this_matters": ("a probe trained on a row whose input was truncated while "
                             "the reply was not would be relating a state to behaviour "
                             "produced under a different input"),
    }
    (out_dir / "activation_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out_dir / "activation_rows.jsonl", "w", encoding="utf-8") as f:
        for r in per_row:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[R4-1] true token length: min={min(r['n_tokens_true'] for r in per_row)} "
          f"max={max(r['n_tokens_true'] for r in per_row)} (activation limit {ACT_LIMIT})")
    print(f"[R4-1] truncated under 512: {len(truncated)}   "
          f"input-id mismatches between limits: {len(mismatched)}")
    print(f"[R4-1] tensor rows: {n_rows} vs inputs: {len(per_row)}")
    print(f"[R4-1] reusable as-is: {verdict['activations_reusable_as_is']}")
    if gen_info["found"]:
        print(f"[R4-1] baseline reply tokens (re-tokenised): min={gen_info['response_token_min']} "
              f"max={gen_info['response_token_max']}")
        print(f"[R4-1] truncated replies — re-tokenisation estimate: "
              f"{gen_info['n_estimated_at_cap_by_re_tokenisation']}, "
              f"recorded termination reason: {gen_info['n_true_hit_max_new_tokens']} "
              f"{gen_info['finish_reason_counts']}")
    print(f"[saved] {out_dir/'activation_manifest.json'}, {out_dir/'activation_rows.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
