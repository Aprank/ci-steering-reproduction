#!/usr/bin/env python3
"""P2 verification: independence of the 270 CONFAIDE evaluation scenarios.

The reviewer notes that `finalise_round1.py`'s `unit` argument is inert: the
bootstrap resamples individual scenario pairs, which is only correct if every
scenario really is an independent unit. This checks that claim against the
source stories instead of assuming it.
"""
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src.data.confaide_loader import ConfaideLoader

RUN = REPO / "outputs/research_next_round/round2_2026-09-29"
rows = [json.loads(l) for l in (RUN / "per_sample.final.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]

methods = sorted({r["method"] for r in rows})
print("methods:", methods)
print("rows:", len(rows), " distinct scenario_id:", len({r["scenario_id"] for r in rows}))

base = "No Steering"
by_scen = {r["scenario_id"]: r for r in rows if r["method"] == base}
print("distinct scenarios in base:", len(by_scen))
for m in methods:
    n = len({r["scenario_id"] for r in rows if r["method"] == m})
    print(f"  {m}: {n} scenarios")

# ---- do any two evaluated scenarios share the same source story? ----
items = ConfaideLoader(str(REPO / "data/confaide")).load_tier3()
print("\ntier3 items:", len(items))

idx_of = {}
for r in by_scen.values():
    idx_of[r["scenario_id"]] = r.get("index_in_order")
idxs = sorted(i for i in idx_of.values() if i is not None)
print("index range:", idxs[0], "-", idxs[-1], " n:", len(idxs))
print("indices contiguous:", idxs == list(range(idxs[0], idxs[0] + len(idxs))))

story_hash = {}
for sid, i in idx_of.items():
    if i is None or i >= len(items):
        continue
    story_hash[sid] = hashlib.sha256(items[i].story.encode()).hexdigest()[:16]

dup = defaultdict(list)
for sid, h in story_hash.items():
    dup[h].append(sid)
dups = {h: v for h, v in dup.items() if len(v) > 1}
print(f"\ndistinct story hashes: {len(set(story_hash.values()))} / {len(story_hash)}")
print(f"story hashes used by >1 scenario: {len(dups)}")
for h, v in list(dups.items())[:5]:
    print("   ", h, v)

# ---- do the scenario metadata fields agree with the stored scenario block? ----
bad = []
for sid, r in by_scen.items():
    i = r.get("index_in_order")
    if i is None or i >= len(items):
        continue
    it = items[i]
    if r["scenario"]["info_type"] != it.topic:
        bad.append((sid, "info_type", r["scenario"]["info_type"], it.topic))
    if r["meta"]["questionee"] != it.questionee:
        bad.append((sid, "questionee", r["meta"]["questionee"], it.questionee))
print(f"\nmetadata mismatches vs loader: {len(bad)}")
for b in bad[:5]:
    print("   ", b)

# ---- how many scenarios does each (about, questionee, questioner, topic, secret) group cover? ----
grp = Counter()
for sid, r in by_scen.items():
    i = r.get("index_in_order")
    if i is None or i >= len(items):
        continue
    it = items[i]
    grp[(it.about, it.questionee, it.questioner, it.topic, it.secret_topic)] += 1
multi = {k: v for k, v in grp.items() if v > 1}
print(f"\n(person-triple, topic, secret) groups: {len(grp)}; with >1 scenario: {len(multi)}")
for k, v in list(multi.items())[:5]:
    print("   ", k, v)

# ---- do answers repeat across scenarios (copy detection)? ----
print("\n=== response duplicates within a method ===")
for m in methods:
    rs = [r for r in rows if r["method"] == m and r.get("response")]
    h = Counter(hashlib.sha256(r["response"].encode()).hexdigest() for r in rs)
    rep = {k: v for k, v in h.items() if v > 1}
    print(f"  {m}: {len(rs)} responses, {len(rep)} exact-duplicate texts "
          f"(max repeat {max(h.values()) if h else 0})")

# ---- diagnostic/random overlap used by the blind package ----
print("\n=== blind package overlap (reviewer: 112 -> 105) ===")
bd = RUN / "blind_review"
diag = [json.loads(l) for l in (bd / "blind_diagnostic.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]
rand = [json.loads(l) for l in (bd / "blind_random.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]
print(f"  blind_random={len(rand)}  blind_diagnostic={len(diag)}")
mapping = json.loads((bd / "mapping.json").read_text(encoding="utf-8"))["items"]
print(f"  mapping items={len(mapping)}")
print(f"  mapping sets: {Counter(x['set'] for x in mapping)}")
key = lambda x: (x["method"], x["scenario_id"])
mk = Counter(key(x) for x in mapping)
overlap = {k: v for k, v in mk.items() if v > 1}
print(f"  (method,scenario) appearing in BOTH sets: {len(overlap)}")
