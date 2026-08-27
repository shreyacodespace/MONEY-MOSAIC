"""
explain_and_export.py
Turns each detected cluster into a plain-English "case note", the way a
junior investigator would summarize it, and exports the final data.json
that the React UI reads directly (no live backend needed for the demo).

Note: this is a template-based generator so the prototype runs standalone
with zero external dependencies or API keys. It's written so a single
function (explain_cluster) can be swapped for a real Claude API call
later without touching anything else - see the commented block at the
bottom for how that swap would look.
"""

import json
import pandas as pd

df = pd.read_csv("transactions.csv", parse_dates=["timestamp"])
with open("detection_raw.json") as f:
    detected = json.load(f)

def fmt_amount(a):
    return f"₹{a:,.0f}"

def explain_cluster(c):
    p = c["pattern_type"]
    n_acc = len(c["accounts_involved"])
    amt = fmt_amount(c["total_amount"])
    hrs = c["time_span_hours"]

    if p == "circular":
        hops = c.get("num_hops", n_acc)
        return (
            f"{amt} moved through a closed loop of {hops} accounts and returned "
            f"close to its starting point within {hrs} hours. Each hop kept the "
            f"amount nearly unchanged, which is consistent with layering — moving "
            f"money through intermediaries to obscure its origin rather than any "
            f"real economic transaction."
        )
    if p == "smurfing":
        mules = c.get("num_mules", n_acc - 2)
        return (
            f"{amt} was split into {mules} transfers, each kept just under the "
            f"₹15,000 threshold, sent to {mules} separate accounts, then "
            f"reconsolidated into a single account within {hrs} hours. This "
            f"structuring pattern is a classic way to stay under reporting limits "
            f"while still moving a large sum as one block."
        )
    if p == "fan_in_out":
        senders = c.get("num_senders", n_acc - 2)
        return (
            f"{senders} separate accounts sent smaller amounts into one collector "
            f"account, which then paid out {amt} in a single large transfer within "
            f"{hrs} hours of the first inflow. The account shows no other activity "
            f"outside this window, suggesting it exists only to pool and forward "
            f"funds."
        )
    return f"{amt} across {n_acc} accounts flagged as a suspicious pattern."

def confidence(c):
    hrs = c["time_span_hours"]
    if hrs < 6:
        return "high"
    if hrs < 24:
        return "medium"
    return "low"

for c in detected["clusters"]:
    c["explanation"] = explain_cluster(c)
    c["confidence"] = confidence(c)

# ---------- Build final accounts + transactions + clusters payload ----------
flagged_accounts = set(detected["flagged_accounts"])
flagged_txns = set(detected["flagged_txns"])

acc_to_cluster = {}
for c in detected["clusters"]:
    for a in c["accounts_involved"]:
        acc_to_cluster[a] = c["cluster_id"]

txn_to_cluster = {}
for c in detected["clusters"]:
    for t in c["transaction_ids"]:
        txn_to_cluster[t] = c["cluster_id"]

all_accounts = sorted(set(df["from"]) | set(df["to"]))
accounts_payload = [
    {
        "id": a,
        "label": a,
        "flagged": a in flagged_accounts,
        "cluster_id": acc_to_cluster.get(a),
    }
    for a in all_accounts
]

transactions_payload = [
    {
        "id": row["txn_id"],
        "from": row["from"],
        "to": row["to"],
        "amount": round(row["amount"], 2),
        "timestamp": row["timestamp"].isoformat(),
        "flagged": row["txn_id"] in flagged_txns,
        "cluster_id": txn_to_cluster.get(row["txn_id"]),
    }
    for _, row in df.iterrows()
]

clusters_payload = [
    {k: v for k, v in c.items()} for c in detected["clusters"]
]

output = {
    "meta": {
        "total_accounts": len(all_accounts),
        "total_transactions": len(df),
        "flagged_clusters": len(clusters_payload),
        "flagged_accounts": len(flagged_accounts),
        "flagged_transactions": len(flagged_txns),
    },
    "accounts": accounts_payload,
    "transactions": transactions_payload,
    "clusters": clusters_payload,
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Exported data.json: {len(all_accounts)} accounts, "
      f"{len(df)} transactions, {len(clusters_payload)} clusters.")

# ---------------------------------------------------------------------------
# To swap in a real Claude API call later, replace explain_cluster() with:
#
#   import anthropic
#   client = anthropic.Anthropic(api_key="YOUR_KEY")
#
#   def explain_cluster(c):
#       prompt = f"Summarize this suspected money-laundering pattern for an " \
#                f"investigator in 2-3 sentences: {json.dumps(c)}"
#       msg = client.messages.create(
#           model="claude-sonnet-4-6",
#           max_tokens=200,
#           messages=[{"role": "user", "content": prompt}],
#       )
#       return msg.content[0].text
#
# Everything downstream (export, UI) stays identical.
# ---------------------------------------------------------------------------
