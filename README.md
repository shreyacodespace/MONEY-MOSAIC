# MONEY-MOSAIC
MoneyMosaic reframes fraud detection as a graph problem instead of a row-by-row problem. Every account is a node, every transaction is an edge — and instead of scoring one transaction at a time, MoneyMosaic looks for the shape of a laundering pattern across the network: circular transfers, smurfing, and fan-in/fan-out schemes. Every flagged cluster comes with a plain-English investigator note explaining why it was caught, not just a risk score.
Built for Build $ Bank 2026 (Track 2 — Fraud Detection & Financial Crime Prevention). Tested on a synthetic 96-account, 333-transaction network with 6 seeded laundering rings — caught 6/6, with zero false positives.

