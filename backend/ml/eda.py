"""Exploratory data analysis -> docs/eda_report.md + PNG charts in docs/eda/."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from ml.data import load_accounts, load_transactions  # noqa: E402


def _md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(f"{v:,.2f}" if isinstance(v, float) else f"{v:,}" if isinstance(v, int) else str(v) for v in row) + " |")
    return "\n".join(lines)


def run_eda(engine: Engine, docs_dir: Path) -> dict:
    out = docs_dir / "eda"
    out.mkdir(parents=True, exist_ok=True)
    tx = load_transactions(engine)
    acc = load_accounts(engine)
    cust = pd.read_sql(text("SELECT segment, country, kyc_level, pep_flag FROM customers"), engine)
    tx["label"] = tx["sim_is_sar"].map({True: "SAR (simulated)", False: "Normal"})

    plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False})
    daily = tx.set_index("timestamp").resample("D").agg(count=("amount", "size"), sar=("sim_is_sar", "sum"))
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(daily.index, daily["count"], color="#2a78d6", lw=1.5)
    ax.set_title("Daily transaction count"); ax.set_ylabel("transactions")
    fig.tight_layout(); fig.savefig(out / "daily_volume.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.2))
    for lab, color in [("Normal", "#2a78d6"), ("SAR (simulated)", "#eb6834")]:
        s = tx.loc[tx["label"] == lab, "amount"]
        ax.hist(s.clip(upper=50000), bins=80, alpha=0.6, density=True, color=color, label=lab)
    ax.set_yscale("log"); ax.set_title("Amount distribution (density, clipped at 50k)"); ax.legend()
    fig.tight_layout(); fig.savefig(out / "amount_distribution.png"); plt.close(fig)

    hour = pd.crosstab(tx["timestamp"].dt.hour, tx["label"], normalize="columns")
    fig, ax = plt.subplots(figsize=(9, 3.2))
    hour.plot(ax=ax, color=["#2a78d6", "#eb6834"]); ax.set_title("Share of transactions by hour"); ax.set_xlabel("hour")
    fig.tight_layout(); fig.savefig(out / "hour_profile.png"); plt.close(fig)

    by_type = tx.groupby(["tx_type"]).agg(transactions=("amount", "size"), sar_rate=("sim_is_sar", "mean"),
                                          median_amount=("amount", "median")).reset_index()
    by_cat = tx.groupby(["category"]).agg(transactions=("amount", "size"), sar_rate=("sim_is_sar", "mean"),
                                          median_amount=("amount", "median")).reset_index().sort_values("transactions", ascending=False)
    by_xb = tx.groupby("is_cross_border").agg(transactions=("amount", "size"), sar_rate=("sim_is_sar", "mean")).reset_index()
    amount_stats = tx.groupby("label")["amount"].describe(percentiles=[.5, .9, .99]).reset_index()
    seg = cust["segment"].value_counts().rename_axis("segment").reset_index(name="customers")
    alert_types = pd.read_sql(text("SELECT sim_alert_id, COUNT(*) AS n FROM transactions WHERE sim_alert_id IS NOT NULL GROUP BY sim_alert_id"), engine)

    report = f"""# FinGuard AI - Exploratory Data Analysis

Generated from the ingested PostgreSQL tables (synthetic AMLSim-format data).
SAR labels are simulator ground truth, used only to train and evaluate models.

## Dataset size

| Item | Count |
|---|---|
| Customers | {len(cust):,} |
| Accounts | {len(acc):,} |
| Accounts in simulated laundering patterns | {int(acc['sim_is_sar'].sum()):,} |
| Transactions | {len(tx):,} |
| Simulated SAR transactions | {int(tx['sim_is_sar'].sum()):,} ({tx['sim_is_sar'].mean():.2%}) |
| Simulated laundering patterns (alerts) | {len(alert_types):,} |
| Period | {tx['timestamp'].min():%Y-%m-%d} to {tx['timestamp'].max():%Y-%m-%d} |

Class imbalance is severe (~1 in {int(1 / max(tx['sim_is_sar'].mean(), 1e-9)):,}), so PR-AUC and precision/recall at a
review budget (top-k) are the meaningful metrics, not accuracy.

## Customer segments

{_md_table(seg)}

## Amounts: normal vs simulated SAR

{_md_table(amount_stats.round(2))}

![amounts](eda/amount_distribution.png)

## By transaction type

{_md_table(by_type.round(4))}

## By derived category

{_md_table(by_cat.round(4))}

## Cross-border

{_md_table(by_xb.round(4))}

## Time patterns

![daily](eda/daily_volume.png)

![hours](eda/hour_profile.png)

## Observations that drove feature engineering

1. SAR amounts overlap SME/corporate business payments, so amount alone is weak.
2. SAR activity is over-represented at night (00-05h) - `is_night`, `hour`.
3. Laundering typologies show up as bursts: fan-out (many new counterparties), fan-in (many senders
   to one receiver) and pass-through (money leaves soon after it arrives) - velocity windows,
   `sender_new_counterparties_7d`, `receiver_in_count_7d`, `pass_through_ratio`.
4. Structuring shows repeated amounts just below 10,000 - `near_threshold`.
5. Cross-border transfers to elevated-risk jurisdictions have a higher SAR rate - country risk features.
"""
    (docs_dir / "eda_report.md").write_text(report, encoding="utf-8")
    return {"report": str(docs_dir / "eda_report.md"), "charts": sorted(p.name for p in out.glob("*.png"))}
