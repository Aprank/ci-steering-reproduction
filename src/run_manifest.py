#!/usr/bin/env python3
"""
T0 — freeze the run: version, environment, inputs, and traceable manifest.

Produces `outputs/research_next_round/<run_id>/run_manifest.json` plus a hash
inventory of immutable inputs. Never writes credentials.

Principles (from the round-2 task list):
  * separate IMMUTABLE inputs from TEMPORARY results and FINAL artifacts;
  * record commit + diff + model/tokenizer revision + software versions +
    generation params + layer/token definitions;
  * list anything that cannot be found as MISSING rather than guessing.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sh(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, cwd=cwd or REPO, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=120)
        return (p.stdout or "").strip(), (p.stderr or "").strip(), p.returncode
    except Exception as e:  # pragma: no cover
        return "", str(e), -1


def sha256_file(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path, patterns=("*.json", "*.jsonl"), max_files=500):
    """Hash matching files under root; return list of {path,size,sha256}."""
    out = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if not any(p.match(pat) for pat in patterns):
            continue
        out.append({
            "path": str(p.relative_to(REPO)),
            "size": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                              .isoformat(timespec="seconds"),
            "sha256": sha256_file(p),
        })
        if len(out) >= max_files:
            break
    return out


def hf_revisions():
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    wanted = {
        "Qwen/Qwen2.5-7B-Instruct": "models--Qwen--Qwen2.5-7B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3": "models--mistralai--Mistral-7B-Instruct-v0.3",
        "meta-llama/Llama-3.1-8B-Instruct": "models--meta-llama--Llama-3.1-8B-Instruct",
        "meta-llama/Llama-2-7b-chat-hf": "models--meta-llama--Llama-2-7b-chat-hf",
    }
    res = {}
    for label, d in wanted.items():
        snaps = hub / d / "snapshots"
        if snaps.exists():
            revs = sorted(x.name for x in snaps.iterdir() if x.is_dir())
            size = sum(f.stat().st_size for f in (hub / d).rglob("*") if f.is_file())
            res[label] = {"revisions": revs, "bytes_on_disk": size}
        else:
            res[label] = "MISSING (not in local HF cache)"
    return res


def gpu_state():
    out, err, rc = sh("nvidia-smi --query-gpu=index,name,memory.total,memory.used,"
                      "memory.free,utilization.gpu --format=csv,noheader")
    if rc != 0 or not out:
        return {"available": False, "note": "nvidia-smi failed (no /dev/nvidia* in this sandbox?)",
                "stderr": err[:300]}
    gpus = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 6:
            gpus.append({"index": int(parts[0]), "name": parts[1],
                         "total_mib": int(parts[2].split()[0]),
                         "used_mib": int(parts[3].split()[0]),
                         "free_mib": int(parts[4].split()[0]),
                         "util_pct": int(parts[5].split()[0])})
    free = [g for g in gpus if g["util_pct"] == 0 and g["free_mib"] > 20000]
    return {"available": True, "gpus": gpus,
            "idle_candidates": [g["index"] for g in free]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="round2_" + datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--out-root", default="outputs/research_next_round")
    args = ap.parse_args()

    run_dir = REPO / args.out_root / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    commit, _, _ = sh(["git", "rev-parse", "HEAD"])
    branch, _, _ = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status, _, _ = sh(["git", "status", "--porcelain"])
    diff, _, _ = sh(["git", "diff", "HEAD"])
    remote, _, _ = sh(["git", "remote", "-v"])

    # model / tokenizer revisions actually used by the pipeline
    models = {}
    for label in ["Qwen/Qwen2.5-7B-Instruct", "mistralai/Mistral-7B-Instruct-v0.3"]:
        try:
            from transformers import AutoConfig
            cfg = AutoConfig.from_pretrained(label)
            models[label] = {"architectures": getattr(cfg, "architectures", None),
                             "n_layers": getattr(cfg, "num_hidden_layers", None),
                             "hidden_size": getattr(cfg, "hidden_size", None),
                             "_commit_hash": getattr(cfg, "_commit_hash", None)}
        except Exception as e:
            models[label] = f"MISSING / not loadable here: {type(e).__name__}"

    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for mod in ["torch", "transformers", "sklearn", "numpy", "openai", "peft", "accelerate"]:
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, "__version__", "?")
        except Exception:
            versions[mod] = "MISSING"
    try:
        import torch
        versions["cuda_available"] = bool(torch.cuda.is_available())
        versions["torch_cuda"] = torch.version.cuda
    except Exception:
        pass

    immutable_inputs = {
        "stimuli": hash_tree(REPO / "data" / "stimuli"),
        "pilot": hash_tree(REPO / "data" / "pilot"),
    }
    immutable_inputs["pilot_scenarios_script"] = (
        sha256_file(REPO / "src" / "pilot_scenarios.py")
        if (REPO / "src" / "pilot_scenarios.py").exists() else "MISSING")

    previous_artifacts = {
        "audit_per_sample_jsonl": "outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct/per_sample.jsonl",
        "audit_summary_json": "outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct/summary.json",
        "audit_rejudge_json": "outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct/rejudge_unknown.json",
        "audit_judge_cache": "outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct/judge_cache/gpt_judge_cache.json",
        "confaide_ci_transfer_results": "outputs/confaide_ci_transfer/Qwen2.5-7B-Instruct/confaide_ci_transfer_results.json",
        "origin_judge_cache": "outputs/confaide_ci_transfer/Qwen2.5-7B-Instruct/judge_cache/gpt_judge_cache.json",
    }
    prev = {}
    for k, rel in previous_artifacts.items():
        p = REPO / rel
        if p.exists():
            prev[k] = {"path": rel, "size": p.stat().st_size, "sha256": sha256_file(p)}
        else:
            prev[k] = "MISSING"

    manifest = {
        "run_id": args.run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": {
            "path": str(REPO),
            "commit": commit, "branch": branch,
            "dirty_files": status.splitlines() if status else [],
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff else None,
            "diff_bytes": len(diff),
            "remote": remote.splitlines() if remote else [],
            "public_snapshot_note": ("Public repo snapshot used by the independent review is "
                                     "9a20fc0a7e627176f308daf6488a738778e07812; the working "
                                     "repo base commit is 5c5edc3 with uncommitted changes on top."),
        },
        "models": models,
        "hf_cache": hf_revisions(),
        "software": versions,
        "gpu": gpu_state(),
        "immutable_inputs": immutable_inputs,
        "previous_artifacts": prev,
        "generation_defaults": {
            "decoding": "greedy (do_sample=False, temperature=0)",
            "max_new_tokens": 256,
            "batch_size": 8,
            "judge_max_tokens": 512,
            "judge_temperature": 0.0,
            "steering_layers": [23, 24, 25, 26, 27],
            "activation_token_position": "last real token (left padding)",
            "layer_index_definition": ("hook on model.model.layers[i] OUTPUT, so index 0 is the "
                                       "output of the FIRST transformer block, NOT the embedding"),
        },
        "judge": {
            "provider": "DeepSeek (OpenAI-compatible)",
            "model_env": "DEEPSEEK_MODEL",
            "key_present": bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")),
            "note": "credentials are never written to the manifest",
        },
        "output_dir": str(run_dir.relative_to(REPO)),
    }

    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "code_diff.patch").write_text(diff or "", encoding="utf-8")

    print(f"[T0] run_id           : {args.run_id}")
    print(f"[T0] run dir          : {run_dir.relative_to(REPO)}")
    print(f"[T0] commit           : {commit} ({branch})")
    print(f"[T0] dirty files      : {len(manifest['repo']['dirty_files'])}")
    print(f"[T0] GPU idle cands   : {manifest['gpu'].get('idle_candidates')}")
    print(f"[T0] cuda available   : {versions.get('cuda_available')}")
    print(f"[T0] stimuli files    : {len(immutable_inputs['stimuli'])}")
    print(f"[T0] previous artifact present:",
          {k: (v != 'MISSING') for k, v in prev.items()})
    print(f"[T0] saved            : {run_dir/'run_manifest.json'}")


if __name__ == "__main__":
    main()
