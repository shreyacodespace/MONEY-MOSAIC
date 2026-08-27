"""
generate_data.py
Builds a synthetic UPI-style transaction log: mostly normal peer-to-peer
transfers, with 3 deliberately planted money-laundering patterns buried
inside the noise:

  1. CIRCULAR   - A -> B -> C -> A, similar amounts, short time window
  2. SMURFING   - one big amount split into many small transfers (all
                  under a reporting-style threshold), then reconsolidated
                  into a single account
  3. FAN_IN_OUT - many small senders -> one collector account -> one
                  large payout to a different account, all within hours

Output: transactions.csv, accounts.csv (ground truth included for
scoring the detector later, but the detector itself never sees it).
"""

import random
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)

NUM_NORMAL_ACCOUNTS = 40
START = datetime(2026, 8, 1, 0, 0, 0)
DAYS = 21

accounts = [f"ACC_{i:03d}" for i in range(1, NUM_NORMAL_ACCOUNTS + 1)]

def rand_time(day_offset_max=DAYS):
    return START + timedelta(
        days=random.uniform(0, day_offset_max),
        hours=random.uniform(0, 24),
    )

rows = []
txn_counter = 1

def add_txn(frm, to, amount, ts, ring_id=None, pattern=None):
    global txn_counter
    rows.append({
        "txn_id": f"TXN_{txn_counter:04d}",
        "from": frm,
        "to": to,
        "amount": round(amount, 2),
        "timestamp": ts.isoformat(),
        "ring_id": ring_id,      # ground truth, not used by detector
        "pattern": pattern,      # ground truth, not used by detector
    })
    txn_counter += 1

# ---------- 1. NORMAL NOISE ----------
for _ in range(260):
    a, b = random.sample(accounts, 2)
    amt = random.choice([
        random.uniform(200, 3000),      # everyday spends
        random.uniform(3000, 20000),    # bigger transfers
    ])
    add_txn(a, b, amt, rand_time())

# ---------- 2. CIRCULAR RINGS ----------
def plant_circular(ring_id, base_amount, n_accounts=3):
    ring_accounts = [f"RING{ring_id}_{i}" for i in range(n_accounts)]
    start = rand_time(DAYS - 2)
    amt = base_amount
    for i in range(n_accounts):
        frm = ring_accounts[i]
        to = ring_accounts[(i + 1) % n_accounts]
        # amount shrinks slightly each hop (a cut taken at each layer)
        add_txn(frm, to, amt, start + timedelta(hours=i * 3),
                 ring_id=f"circular_{ring_id}", pattern="circular")
        amt *= 0.97
    return ring_accounts

plant_circular(1, 180000, n_accounts=3)
plant_circular(2, 95000, n_accounts=4)

# ---------- 3. SMURFING ----------
def plant_smurfing(ring_id, total_amount, n_splits, threshold=15000):
    source = f"SMURF{ring_id}_SRC"
    mules = [f"SMURF{ring_id}_M{i}" for i in range(n_splits)]
    collector = f"SMURF{ring_id}_COL"
    start = rand_time(DAYS - 2)
    per_split = total_amount / n_splits
    for i, mule in enumerate(mules):
        amt = min(per_split * random.uniform(0.85, 1.0), threshold - random.uniform(200, 1500))
        t1 = start + timedelta(minutes=i * 20)
        add_txn(source, mule, amt, t1, ring_id=f"smurf_{ring_id}", pattern="smurfing")
        t2 = t1 + timedelta(hours=random.uniform(1, 20))
        add_txn(mule, collector, amt * 0.995, t2, ring_id=f"smurf_{ring_id}", pattern="smurfing")

plant_smurfing(1, 210000, 14)
plant_smurfing(2, 130000, 9)

# ---------- 4. FAN-IN / FAN-OUT ----------
def plant_fan(ring_id, n_senders, per_amount, payout_target):
    collector = f"FAN{ring_id}_COL"
    senders = [f"FAN{ring_id}_S{i}" for i in range(n_senders)]
    start = rand_time(DAYS - 1)
    total = 0
    for i, s in enumerate(senders):
        amt = per_amount * random.uniform(0.8, 1.2)
        total += amt
        add_txn(s, collector, amt, start + timedelta(minutes=i * 8),
                 ring_id=f"fan_{ring_id}", pattern="fan_in_out")
    payout_time = start + timedelta(hours=random.uniform(2, 6))
    add_txn(collector, payout_target, total * 0.98, payout_time,
             ring_id=f"fan_{ring_id}", pattern="fan_in_out")

plant_fan(1, 11, 9000, f"FAN1_OUT")
plant_fan(2, 7, 14000, f"FAN2_OUT")

df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
df.to_csv("transactions.csv", index=False)

all_accounts = sorted(set(df["from"]) | set(df["to"]))
acc_df = pd.DataFrame({"account_id": all_accounts})
acc_df.to_csv("accounts.csv", index=False)

print(f"Generated {len(df)} transactions across {len(all_accounts)} accounts.")
print(f"Planted rings: {df['ring_id'].dropna().unique().tolist()}")
