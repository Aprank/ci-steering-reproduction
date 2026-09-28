#!/usr/bin/env python3
"""P2 verification: how do the three CI-parameter stimulus sets overlap?

The reviewer asks for a JOINT group_id so that a test scenario and all of its
parameter variants are held out together. This script establishes what the base
scenario actually is, and whether the three sets really share it.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.extraction.activation_extractor import ActivationExtractor

P = ["info_type", "recipient", "transmission_principle"]
D = Path("outputs/activations/Qwen2.5-7B-Instruct")

RX = re.compile(
    r"^(?P<sender>.+?) knows that (?P<subject>.+?) has (?P<fact>.+?)\. "
    r"(?P<recip>.+?) asks (?P<sender2>.+?) about (?P<subject2>.+?)'s (?P<topic>.+?)\. "
    r"(?P<tp>.+?)\.$"
)

meta = {}
for p in P:
    a = ActivationExtractor.load_activations(str(D / f"ci_{p}"))
    meta[p] = a["metadata"]

print("=== parse rate ===")
parsed = {}
for p in P:
    parsed[p] = []
    for m in meta[p]:
        g = RX.match(m["text"])
        parsed[p].append(g)
    ok = sum(1 for g in parsed[p] if g)
    print(f"  {p}: {ok}/{len(meta[p])} parsed; classes={len(set(m['varied_value'] for m in meta[p]))}")
    if ok < len(meta[p]):
        for m, g in zip(meta[p], parsed[p]):
            if not g:
                print("    FAIL:", m["text"][:160])
                break

print()
print("=== varied clause is exactly the varied_param? ===")
for p in P:
    field = {"info_type": "fact", "recipient": "recip",
             "transmission_principle": "tp"}[p]
    print(f"  {p}: varied_value appears in its own slot for "
          f"{sum(1 for m, g in zip(meta[p], parsed[p]) if g and m['varied_value'].lower() in g.group(field).lower())}"
          f"/{len(meta[p])}")

print()
print("=== base scenario signature = (subject, sender, fact) ===")
sig = {}
for p in P:
    sig[p] = [ (g.group("subject"), g.group("sender"), g.group("fact")) if g else ("FAIL", m["text"][:80], "")
               for m, g in zip(meta[p], parsed[p]) ]
for p in P:
    print(f"  {p}: {len(sig[p])} rows -> {len(set(sig[p]))} distinct base sigs")

print()
print("=== pairwise overlap ===")
for i, a in enumerate(P):
    for b in P[i + 1:]:
        ov = set(sig[a]) & set(sig[b])
        inter = len(ov)
        print(f"  {a} vs {b}: shared={inter} "
              f"of min={min(len(set(sig[a])), len(set(sig[b])))} "
              f"({inter / min(len(set(sig[a])), len(set(sig[b]))):.1%})")
        for s in list(ov)[:2]:
            print(f"      e.g. {s}")

print()
print("=== is (subject,sender) the same as (subject,sender,fact)? ===")
for p in P:
    ss = [(s, se) for s, se, _ in sig[p]]
    print(f"  {p}: distinct (subject,sender)={len(set(ss))} vs (subject,sender,fact)={len(set(sig[p]))}")

print()
print("=== does one base sig carry multiple classes within a parameter? ===")
for p in P:
    d = {}
    for m, s in zip(meta[p], sig[p]):
        d.setdefault(s, set()).add(m["varied_value"])
    multi = {k: sorted(v) for k, v in d.items() if len(v) > 1}
    print(f"  {p}: base sigs with >1 class = {len(multi)} / {len(d)}")

print()
print("=== exact duplicate activation rows across parameters ===")
acts = {}
for p in P:
    d = ActivationExtractor.load_activations(str(D / f"ci_{p}"))
    layers = sorted(d["activations"].keys())
    layer = layers[len(layers) * 3 // 4]
    acts[p] = d["activations"][layer].float().numpy()
    print(f"  {p}: layer {layer} shape {acts[p].shape}")

for i, a in enumerate(P):
    for b in P[i + 1:]:
        ha = {r.tobytes() for r in acts[a]}
        hb = {r.tobytes() for r in acts[b]}
        print(f"  {a} vs {b}: identical rows = {len(ha & hb)}")
