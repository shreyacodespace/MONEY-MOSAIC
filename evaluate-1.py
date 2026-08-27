"""
evaluate.py
Scores the detector against the ground-truth ring_id labels planted by
generate_data.py. This is only for reporting a concrete accuracy number
in the pitch - the detector itself never sees ring_id.
"""

import json
import pandas as pd

df = pd.read_csv("transactions.csv")
with open("detection_raw.json") as f:
    detected = json.load(f)

planted_rings = df["ring_id"].dropna().unique().tolist()
detected_txn_sets = [set(c["transaction_ids"]) for c in detected["clusters"]]

hits = 0
for ring_id in planted_rings:
    ring_txns = set(df[df["ring_id"] == ring_id]["txn_id"])
    # a ring counts as caught if any detected cluster overlaps it substantially
    if any(len(ring_txns & dset) / len(ring_txns) > 0.5 for dset in detected_txn_sets):
        hits += 1

normal_txns = set(df[df["ring_id"].isna()]["txn_id"])
flagged_normal = normal_txns & set(detected["flagged_txns"])

print(f"Planted rings: {len(planted_rings)}")
print(f"Caught: {hits}/{len(planted_rings)}")
print(f"Normal transactions incorrectly flagged: {len(flagged_normal)} / {len(normal_txns)}")
print(f"Total clusters raised: {len(detected['clusters'])}")
