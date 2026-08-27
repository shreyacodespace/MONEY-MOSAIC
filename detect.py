"""
detect.py
Graph-based financial crime pattern detector. Reads transactions.csv,
builds a directed multigraph, and flags three pattern types:

  - circular:   short directed cycles (A->B->C->A) within a tight time window
  - smurfing:   many small transfers into a set of "mule" accounts that all
                forward on to a common collector, amounts clustered just
                under a round threshold
  - fan_in_out: many senders into one account, followed by one large payout
                out of it within a short window

No ground truth is used here - detection is purely structural, exactly
as it would be on real (unlabeled) transaction data. Ground truth is only
used afterwards, in evaluate.py, to report accuracy for the pitch.
"""

import json
import pandas as pd
import networkx as nx
from datetime import timedelta
from collections import defaultdict

df = pd.read_csv("transactions.csv", parse_dates=["timestamp"])

G = nx.MultiDiGraph()
for _, row in df.iterrows():
    G.add_edge(row["from"], row["to"], txn_id=row["txn_id"],
               amount=row["amount"], timestamp=row["timestamp"])

clusters = []
cluster_counter = 1
flagged_accounts = set()
flagged_txns = set()

def new_cluster_id():
    global cluster_counter
    cid = f"CLUSTER_{cluster_counter}"
    cluster_counter += 1
    return cid

# ---------------- 1. CIRCULAR ----------------
# simple_cycles is expensive on big graphs; restrict to short cycles (len <= 5)
simple_G = nx.DiGraph()
for u, v in G.edges():
    simple_G.add_edge(u, v)

seen_cycle_sets = set()
for cycle in nx.simple_cycles(simple_G, length_bound=5):
    key = frozenset(cycle)
    if key in seen_cycle_sets or len(cycle) < 3:
        continue
    seen_cycle_sets.add(key)

    # pull the actual edges/timestamps for this cycle
    edge_records = []
    ok = True
    for i in range(len(cycle)):
        a, b = cycle[i], cycle[(i + 1) % len(cycle)]
        candidates = [d for d in G.get_edge_data(a, b, default={}).values()]
        if not candidates:
            ok = False
            break
        edge_records.append(min(candidates, key=lambda d: d["amount"] * 0))  # just take one
    if not ok:
        continue

    timestamps = [e["timestamp"] for e in edge_records]
    span = max(timestamps) - min(timestamps)
    if span > timedelta(hours=48):
        continue  # too spread out to be a deliberate ring

    amounts = [e["amount"] for e in edge_records]
    if max(amounts) / min(amounts) > 1.5:
        continue  # amounts too different to be a layering ring

    cid = new_cluster_id()
    txn_ids = [e["txn_id"] for e in edge_records]
    flagged_accounts.update(cycle)
    flagged_txns.update(txn_ids)
    clusters.append({
        "cluster_id": cid,
        "pattern_type": "circular",
        "accounts_involved": cycle,
        "transaction_ids": txn_ids,
        "total_amount": round(sum(amounts), 2),
        "time_span_hours": round(span.total_seconds() / 3600, 1),
        "num_hops": len(cycle),
    })

# ---------------- 2. SMURFING ----------------
# For each account, look at its outgoing edges: if many small transfers
# (< threshold) go out within a short window, and a large share of those
# recipients then forward on to one common account -> flag as smurfing.
THRESHOLD = 15000
out_edges = defaultdict(list)
for u, v, d in G.edges(data=True):
    out_edges[u].append((v, d))

for source, edges in out_edges.items():
    small = [(v, d) for v, d in edges if d["amount"] < THRESHOLD]
    if len(small) < 5:
        continue
    times = [d["timestamp"] for _, d in small]
    span = max(times) - min(times)
    if span > timedelta(hours=24):
        continue

    # check where the recipients forward their money to
    forward_targets = defaultdict(list)
    for mule, d in small:
        for _, target, fd in G.out_edges(mule, data=True):
            if fd["timestamp"] >= d["timestamp"]:
                forward_targets[target].append((mule, d, fd))

    for target, hits in forward_targets.items():
        distinct_mules = {m for m, _, _ in hits}
        if len(distinct_mules) < 5:
            continue

        cid = new_cluster_id()
        accounts_involved = [source] + list(distinct_mules) + [target]
        in_txns = [d["txn_id"] for m, d, fd in hits]
        out_txns = [fd["txn_id"] for m, d, fd in hits]
        all_txns = list(set(in_txns + out_txns))
        total = sum(d["amount"] for _, d, _ in hits)

        flagged_accounts.update(accounts_involved)
        flagged_txns.update(all_txns)
        clusters.append({
            "cluster_id": cid,
            "pattern_type": "smurfing",
            "accounts_involved": accounts_involved,
            "transaction_ids": all_txns,
            "total_amount": round(total, 2),
            "time_span_hours": round(span.total_seconds() / 3600, 1),
            "num_mules": len(distinct_mules),
        })

# ---------------- 3. FAN-IN / FAN-OUT ----------------
in_edges = defaultdict(list)
for u, v, d in G.edges(data=True):
    in_edges[v].append((u, d))

for collector, incoming in in_edges.items():
    if len(incoming) < 5:
        continue
    times_in = [d["timestamp"] for _, d in incoming]
    span_in = max(times_in) - min(times_in)
    if span_in > timedelta(hours=12):
        continue

    total_in = sum(d["amount"] for _, d in incoming)

    # look for a single large payout shortly after the inflow window
    payouts = [(v, d) for _, v, d in G.out_edges(collector, data=True)
               if d["timestamp"] > max(times_in)]
    big_payouts = [(v, d) for v, d in payouts if d["amount"] > total_in * 0.7]
    if not big_payouts:
        continue

    target, payout_d = max(big_payouts, key=lambda x: x[1]["amount"])
    span_total = payout_d["timestamp"] - min(times_in)
    if span_total > timedelta(hours=24):
        continue

    cid = new_cluster_id()
    senders = [u for u, _ in incoming]
    accounts_involved = senders + [collector, target]
    txn_ids = [d["txn_id"] for _, d in incoming] + [payout_d["txn_id"]]

    flagged_accounts.update(accounts_involved)
    flagged_txns.update(txn_ids)
    clusters.append({
        "cluster_id": cid,
        "pattern_type": "fan_in_out",
        "accounts_involved": accounts_involved,
        "transaction_ids": txn_ids,
        "total_amount": round(total_in, 2),
        "time_span_hours": round(span_total.total_seconds() / 3600, 1),
        "num_senders": len(senders),
    })

# ---------------- WRITE INTERMEDIATE OUTPUT ----------------
with open("detection_raw.json", "w") as f:
    json.dump({
        "clusters": clusters,
        "flagged_accounts": sorted(flagged_accounts),
        "flagged_txns": sorted(flagged_txns),
    }, f, indent=2)

print(f"Detected {len(clusters)} suspicious clusters:")
for c in clusters:
    print(f"  {c['cluster_id']}: {c['pattern_type']} "
          f"({len(c['accounts_involved'])} accounts, "
          f"₹{c['total_amount']:,.0f}, {c['time_span_hours']}h)")
