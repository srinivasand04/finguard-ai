"""AMLSim-compatible synthetic banking data generator.

Produces files in the same layout as IBM AMLSim's output so the ingestion
pipeline works unchanged with real AMLSim runs:

    accounts.csv      ACCOUNT_ID, CUSTOMER_ID, INIT_BALANCE, COUNTRY, ACCOUNT_TYPE,
                      IS_SAR, TX_BEHAVIOR_ID, BANK_ID, OPEN_DATE
    transactions.csv  TX_ID, SENDER_ACCOUNT_ID, RECEIVER_ACCOUNT_ID, TX_TYPE,
                      TX_AMOUNT, TIMESTAMP, IS_SAR, ALERT_ID
    alerts.csv        ALERT_ID, ALERT_TYPE, IS_SAR, TX_ID, SENDER_ACCOUNT_ID,
                      RECEIVER_ACCOUNT_ID, TX_TYPE, TX_AMOUNT, TIMESTAMP

plus a FinGuard extension file:

    customers.csv     CUSTOMER_ID, FULL_NAME, SEGMENT, COUNTRY, OCCUPATION,
                      DATE_OF_BIRTH, ONBOARDING_DATE, KYC_LEVEL, PEP_FLAG

Laundering typologies follow AMLSim's names (fan_out, fan_in, cycle,
scatter_gather, gather_scatter, bipartite, stack) plus "structuring".
All data is synthetic. A small number of deliberately dirty rows are
injected so the validation layer has something to catch.

Usage:  python -m data_gen.amlsim_synth --out ../data/raw/amlsim --customers 1500 --days 180
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

FIRST = ["Anna", "Ben", "Clara", "David", "Elena", "Felix", "Greta", "Hugo", "Ines", "Jonas", "Klara", "Lukas",
         "Mila", "Noah", "Olivia", "Paul", "Rosa", "Samir", "Tara", "Umar", "Vera", "Wim", "Yara", "Zoe",
         "Aiko", "Bilal", "Chen", "Dana", "Emre", "Farah", "Goran", "Hana", "Ivan", "Jana", "Kofi", "Lena"]
LAST = ["Weber", "Jansen", "Moreau", "Rossi", "Novak", "Silva", "Kowalski", "Berg", "Dubois", "Fischer",
        "Visser", "Garcia", "Horvat", "Lindqvist", "Meyer", "Nagy", "Okafor", "Petrov", "Quinn", "Richter",
        "Schmidt", "Tanaka", "Ueda", "Varga", "Wagner", "Yilmaz", "Zimmer", "Haddad", "Costa", "Ivanova"]
OCCUPATIONS = {
    "RETAIL": ["Teacher", "Engineer", "Nurse", "Student", "Retired", "Sales associate", "Designer", "Driver", "Chef"],
    "SME": ["Restaurant owner", "Import/export trader", "Construction firm", "IT consultancy", "Retail shop", "Car dealer"],
    "CORPORATE": ["Manufacturing group", "Logistics company", "Wholesale distributor", "Software company"],
}
# The simulated bank operates in one home market; foreign customers/counterparties sit elsewhere
HOME_COUNTRIES = ["DE"]
HOME_WEIGHTS = [1.0]
# Illustrative "elevated-risk" jurisdictions for the synthetic demo; configurable in backend/config/risk_config.json
FOREIGN_COUNTRIES = ["NL", "FR", "AT", "GB", "CH", "US", "AE", "HK", "CY", "PA", "KY", "TR"]
FOREIGN_WEIGHTS = [0.14, 0.12, 0.10, 0.10, 0.08, 0.08, 0.09, 0.07, 0.06, 0.06, 0.05, 0.05]

TYPOLOGIES = ["fan_out", "fan_in", "cycle", "scatter_gather", "gather_scatter", "bipartite", "stack", "structuring"]


@dataclass
class GenConfig:
    customers: int = 1500
    days: int = 180
    start: str = "2026-01-01"
    seed: int = 42
    alerts: int = 120
    dirty_fraction: float = 0.002


class Generator:
    def __init__(self, cfg: GenConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.start = datetime.fromisoformat(cfg.start)
        self.end = self.start + timedelta(days=cfg.days)
        self.tx_rows: list[tuple] = []
        self.alert_rows: list[dict] = []

    # ------------------------------------------------------------------ customers / accounts
    def make_customers(self) -> pd.DataFrame:
        r, n = self.rng, self.cfg.customers
        n_foreign = int(n * 0.12)
        segment = r.choice(["RETAIL", "SME", "CORPORATE"], size=n, p=[0.80, 0.15, 0.05])
        country = np.where(
            np.arange(n) < n - n_foreign,
            r.choice(HOME_COUNTRIES, size=n, p=HOME_WEIGHTS),
            r.choice(FOREIGN_COUNTRIES, size=n, p=FOREIGN_WEIGHTS),
        )
        r.shuffle(country)
        onboard_days = r.integers(30, 365 * 10, size=n)
        # ~6% of customers onboarded recently (within the simulation window) - "new customer" behaviour
        recent = r.random(n) < 0.06
        onboard = [
            (self.start + timedelta(days=int(r.integers(0, self.cfg.days // 2)))) if rec
            else (self.start - timedelta(days=int(d)))
            for d, rec in zip(onboard_days, recent)
        ]
        ages = r.integers(19, 85, size=n)
        rows = []
        for i in range(n):
            seg = segment[i]
            name = f"{r.choice(FIRST)} {r.choice(LAST)}"
            if seg != "RETAIL":
                name = f"{r.choice(LAST)} {r.choice(['GmbH', 'BV', 'SARL', 'Holding', 'Trading', 'Group'])}"
            rows.append({
                "CUSTOMER_ID": f"CUST{10000 + i}",
                "FULL_NAME": name,
                "SEGMENT": seg,
                "COUNTRY": country[i],
                "OCCUPATION": r.choice(OCCUPATIONS[seg]),
                "DATE_OF_BIRTH": (self.start - timedelta(days=int(ages[i] * 365.25))).date().isoformat() if seg == "RETAIL" else "",
                "ONBOARDING_DATE": onboard[i].date().isoformat(),
                "KYC_LEVEL": r.choice(["SIMPLIFIED", "STANDARD", "ENHANCED"], p=[0.15, 0.75, 0.10]),
                "PEP_FLAG": bool(r.random() < 0.01),
            })
        return pd.DataFrame(rows)

    def make_accounts(self, customers: pd.DataFrame) -> pd.DataFrame:
        r = self.rng
        rows, k = [], 0
        for c in customers.itertuples():
            n_acc = {"RETAIL": r.choice([1, 2, 3], p=[0.6, 0.3, 0.1]),
                     "SME": r.choice([1, 2], p=[0.5, 0.5]),
                     "CORPORATE": r.choice([2, 3, 4])}[c.SEGMENT]
            onboard = datetime.fromisoformat(c.ONBOARDING_DATE)
            for j in range(n_acc):
                acc_type = "BUSINESS" if c.SEGMENT != "RETAIL" else ("CHECKING" if j == 0 else r.choice(["SAVINGS", "CHECKING"]))
                opened = onboard + timedelta(days=int(r.integers(0, 60)) * j)
                bal_mu = {"RETAIL": 8.0, "SME": 10.0, "CORPORATE": 12.0}[c.SEGMENT]
                rows.append({
                    "ACCOUNT_ID": f"ACC{100000 + k}",
                    "CUSTOMER_ID": c.CUSTOMER_ID,
                    "INIT_BALANCE": round(float(r.lognormal(bal_mu, 0.8)), 2),
                    "COUNTRY": c.COUNTRY,
                    "ACCOUNT_TYPE": acc_type,
                    "IS_SAR": False,
                    "TX_BEHAVIOR_ID": 1,
                    "BANK_ID": "BANK_FG" if c.COUNTRY in HOME_COUNTRIES else f"BANK_{c.COUNTRY}",
                    "OPEN_DATE": opened.date().isoformat(),
                    "SEGMENT": c.SEGMENT,  # helper column, dropped before writing
                })
                k += 1
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ normal behaviour
    def _rand_times(self, n: int, start: datetime | None = None, end: datetime | None = None, night_bias: float = 0.0):
        r = self.rng
        start = start or self.start
        end = end or self.end
        span_days = max((end - start).days, 1)
        day = r.integers(0, span_days, size=n)
        # mostly business hours; night_bias pushes some activity to 00-05h
        hours = r.choice(np.arange(24), size=n, p=self._hour_p())
        if night_bias > 0:
            night = r.random(n) < night_bias
            hours = np.where(night, r.integers(0, 5, size=n), hours)
        secs = r.integers(0, 3600, size=n)
        return [start + timedelta(days=int(d), hours=int(h), seconds=int(s)) for d, h, s in zip(day, hours, secs)]

    @staticmethod
    def _hour_p():
        w = np.array([1, 0.5, 0.4, 0.3, 0.3, 0.6, 1.5, 3, 5, 6, 6, 6, 7, 6, 6, 6, 6, 6, 5, 4, 3.5, 3, 2, 1.5])
        return w / w.sum()

    def _add(self, sender, receiver, ttype, amount, ts, is_sar=False, alert_id=-1):
        self.tx_rows.append((sender, receiver, ttype, round(float(amount), 2), ts, is_sar, alert_id))

    def make_normal_transactions(self, accounts: pd.DataFrame):
        r = self.rng
        acc_ids = accounts["ACCOUNT_ID"].to_numpy()
        seg = accounts["SEGMENT"].to_numpy()
        country = accounts["COUNTRY"].to_numpy()
        opened = pd.to_datetime(accounts["OPEN_DATE"]).to_numpy()
        n = len(acc_ids)
        business_idx = np.where(seg != "RETAIL")[0]
        retail_idx = np.where(seg == "RETAIL")[0]
        corp_idx = np.where(seg == "CORPORATE")[0]

        rate = {"RETAIL": 0.30, "SME": 0.75, "CORPORATE": 1.8}
        amt = {"RETAIL": (4.3, 1.0), "SME": (6.3, 1.1), "CORPORATE": (7.6, 1.2)}
        for i in range(n):
            s = seg[i]
            # favoured counterparties: retail mostly pays businesses (merchants), businesses pay both
            pool = business_idx if s == "RETAIL" else np.concatenate([business_idx, retail_idx[:200]])
            fav = r.choice(pool, size=min(len(pool), int(r.integers(3, 12))), replace=False)
            acc_start = max(self.start, pd.Timestamp(opened[i]).to_pydatetime())
            if acc_start >= self.end:
                continue
            days_active = (self.end - acc_start).days
            count = r.poisson(rate[s] * days_active)
            if count == 0:
                continue
            times = self._rand_times(count, start=acc_start)
            use_fav = r.random(count) < 0.75
            cps = np.where(use_fav, r.choice(fav, size=count), r.integers(0, n, size=count))
            amounts = r.lognormal(*amt[s], size=count)
            for t, cp, a in zip(times, cps, amounts):
                if cp == i:
                    continue
                foreign = country[cp] != country[i]
                ttype = "WIRE" if foreign and r.random() < 0.7 else ("PAYMENT" if seg[cp] != "RETAIL" else "TRANSFER")
                self._add(acc_ids[i], acc_ids[cp], ttype, max(a, 1.0), t)

        # monthly salaries: corporate accounts -> retail accounts on the 25th
        employees = r.choice(retail_idx, size=min(len(retail_idx), len(corp_idx) * 12), replace=False)
        employers = r.choice(corp_idx, size=len(employees))
        salary = r.uniform(2200, 5500, size=len(employees))
        m = self.start
        while m < self.end:
            pay = m.replace(day=25, hour=6)
            if self.start <= pay < self.end:
                for e, b, s_amt in zip(employees, employers, salary):
                    self._add(acc_ids[b], acc_ids[e], "TRANSFER", s_amt * r.uniform(0.98, 1.02), pay + timedelta(minutes=int(r.integers(0, 120))))
            m = (m.replace(day=1) + timedelta(days=32)).replace(day=1)

        # legitimate one-off large purchases (noise that looks like risk)
        for i in r.choice(retail_idx, size=int(len(retail_idx) * 0.04), replace=False):
            cp = r.choice(business_idx)
            self._add(acc_ids[i], acc_ids[cp], "PAYMENT", r.uniform(9000, 45000), self._rand_times(1)[0])

    # ------------------------------------------------------------------ laundering typologies
    def make_sar_patterns(self, accounts: pd.DataFrame):
        r = self.rng
        acc_ids = accounts["ACCOUNT_ID"].to_numpy()
        is_sar = np.zeros(len(acc_ids), dtype=bool)
        foreign_mask = ~accounts["COUNTRY"].isin(HOME_COUNTRIES).to_numpy()
        foreign_idx = np.where(foreign_mask)[0]
        opened = pd.to_datetime(accounts["OPEN_DATE"])
        eligible = np.where(opened < pd.Timestamp(self.end - timedelta(days=40)))[0]

        # Laundering networks reuse a limited pool of mule accounts (~10% of accounts)
        dom_pool = r.choice(np.setdiff1d(eligible, foreign_idx), size=int(len(acc_ids) * 0.085), replace=False)
        for_pool = r.choice(np.intersect1d(eligible, foreign_idx), size=min(40, len(np.intersect1d(eligible, foreign_idx))), replace=False)

        def pick(k):
            # 25% chance each pattern member is a foreign account (cross-border layering); members are distinct
            out: list[int] = []
            while len(out) < k:
                pool = for_pool if (len(for_pool) and r.random() < 0.25) else dom_pool
                c = int(r.choice(pool))
                if c not in out:
                    out.append(c)
            return out

        for alert_id in range(self.cfg.alerts):
            typ = TYPOLOGIES[alert_id % len(TYPOLOGIES)]
            base = float(r.lognormal(8.1, 0.5))  # ~3.3k median, overlaps SME business payments
            w_start = self.start + timedelta(days=int(r.integers(0, self.cfg.days - 30)))
            w_end = w_start + timedelta(days=int(r.integers(4, 25)))
            nb = 0.3

            def t():
                return self._rand_times(1, w_start, w_end, night_bias=nb)[0]

            def amt(scale=1.0):
                return base * scale * r.uniform(0.85, 1.1)

            def tx(a, b, amount, ttype=None):
                if a == b:
                    return
                if ttype is None:
                    # same typing rule as normal activity, so tx type is not a give-away
                    if accounts.at[b, "COUNTRY"] != accounts.at[a, "COUNTRY"] and r.random() < 0.7:
                        ttype = "WIRE"
                    else:
                        ttype = "PAYMENT" if accounts.at[b, "SEGMENT"] != "RETAIL" else "TRANSFER"
                self._add(acc_ids[a], acc_ids[b], ttype, amount, t(), True, alert_id)
                is_sar[a] = is_sar[b] = True

            if typ == "fan_out":
                src, *dst = pick(int(r.integers(6, 13)))
                for d in dst:
                    tx(src, d, amt(0.6))
            elif typ == "fan_in":
                dst, *src = pick(int(r.integers(6, 13)))
                for s in src:
                    tx(s, dst, amt(0.6))
            elif typ == "cycle":
                ring = pick(int(r.integers(3, 7)))
                a = amt(2.0)
                for _ in range(int(r.integers(1, 4))):
                    for k in range(len(ring)):
                        tx(ring[k], ring[(k + 1) % len(ring)], a)
                        a *= r.uniform(0.95, 0.99)
            elif typ == "scatter_gather":
                src, dst, *mid = pick(int(r.integers(5, 10)))
                for m_ in mid:
                    a = amt(0.8)
                    tx(src, m_, a)
                    tx(m_, dst, a * r.uniform(0.93, 0.98))
            elif typ == "gather_scatter":
                hub, *rest = pick(int(r.integers(7, 13)))
                half = len(rest) // 2
                for s in rest[:half]:
                    tx(s, hub, amt(0.7))
                for d in rest[half:]:
                    tx(hub, d, amt(0.65))
            elif typ == "bipartite":
                grp = pick(int(r.integers(6, 10)))
                left, right = grp[: len(grp) // 2], grp[len(grp) // 2:]
                for a_ in left:
                    for b_ in right:
                        if r.random() < 0.7:
                            tx(a_, b_, amt(0.5))
            elif typ == "stack":
                layers = [pick(int(r.integers(2, 4))) for _ in range(3)]
                for l1, l2 in zip(layers[:-1], layers[1:]):
                    for a_ in l1:
                        for b_ in l2:
                            tx(a_, b_, amt(0.5))
            elif typ == "structuring":
                src, *dst = pick(int(r.integers(2, 4)))
                for _ in range(int(r.integers(6, 14))):
                    tx(src, int(r.choice(dst)), r.uniform(9000, 9950), "TRANSFER")
            self.alert_rows.append({"ALERT_ID": alert_id, "ALERT_TYPE": typ})

        accounts["IS_SAR"] = is_sar
        return accounts

    # ------------------------------------------------------------------ assemble
    def run(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        customers = self.make_customers()
        accounts = self.make_accounts(customers)
        self.make_normal_transactions(accounts)
        accounts = self.make_sar_patterns(accounts)

        tx = pd.DataFrame(self.tx_rows, columns=["SENDER_ACCOUNT_ID", "RECEIVER_ACCOUNT_ID", "TX_TYPE", "TX_AMOUNT", "TIMESTAMP", "IS_SAR", "ALERT_ID"])
        tx = tx.sort_values("TIMESTAMP").reset_index(drop=True)
        tx.insert(0, "TX_ID", np.arange(1, len(tx) + 1))
        tx["TIMESTAMP"] = pd.to_datetime(tx["TIMESTAMP"]).dt.strftime("%Y-%m-%dT%H:%M:%S")

        alerts_meta = pd.DataFrame(self.alert_rows)
        alert_tx = tx[tx["ALERT_ID"] >= 0].merge(alerts_meta, on="ALERT_ID")
        alerts = alert_tx[["ALERT_ID", "ALERT_TYPE", "IS_SAR", "TX_ID", "SENDER_ACCOUNT_ID", "RECEIVER_ACCOUNT_ID", "TX_TYPE", "TX_AMOUNT", "TIMESTAMP"]]

        tx, dirty = self._inject_dirty(tx)

        customers.to_csv(out / "customers.csv", index=False)
        accounts.drop(columns=["SEGMENT"]).to_csv(out / "accounts.csv", index=False)
        tx.to_csv(out / "transactions.csv", index=False)
        alerts.to_csv(out / "alerts.csv", index=False)
        summary = {
            "generator": "finguard amlsim_synth",
            "config": self.cfg.__dict__,
            "customers": len(customers),
            "accounts": len(accounts),
            "sar_accounts": int(accounts["IS_SAR"].sum()),
            "transactions": len(tx),
            "sar_transactions": int((tx["IS_SAR"].astype(str).str.lower() == "true").sum()),
            "alerts": len(alerts_meta),
            "typology_counts": alerts_meta["ALERT_TYPE"].value_counts().to_dict(),
            "dirty_rows_injected": dirty,
        }
        (out / "generation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
        return summary

    def _inject_dirty(self, tx: pd.DataFrame):
        """Add a few malformed rows so validation is exercised (as real feeds would have)."""
        r = self.rng
        k = max(5, int(len(tx) * self.cfg.dirty_fraction))
        sample = tx.sample(k * 6, random_state=self.cfg.seed).reset_index(drop=True)
        chunks = [sample.iloc[i * k:(i + 1) * k] for i in range(6)]
        dup = chunks[0].copy()                                              # exact duplicates
        neg = chunks[1].copy(); neg["TX_ID"] += 10_000_000; neg["TX_AMOUNT"] = -neg["TX_AMOUNT"]
        miss = chunks[2].copy(); miss["TX_ID"] += 20_000_000; miss["RECEIVER_ACCOUNT_ID"] = ""
        unknown = chunks[3].copy(); unknown["TX_ID"] += 30_000_000; unknown["SENDER_ACCOUNT_ID"] = "ACC999999"
        badts = chunks[4].copy(); badts["TX_ID"] += 40_000_000; badts["TIMESTAMP"] = "not-a-date"
        selft = chunks[5].copy(); selft["TX_ID"] += 50_000_000; selft["RECEIVER_ACCOUNT_ID"] = selft["SENDER_ACCOUNT_ID"]
        # lower-case / padded transaction types - fixable by cleaning, not rejected
        idx = r.choice(len(tx), size=k, replace=False)
        tx.loc[idx, "TX_TYPE"] = " " + tx.loc[idx, "TX_TYPE"].str.lower() + " "
        out = pd.concat([tx, dup, neg, miss, unknown, badts, selft], ignore_index=True)
        return out, {"duplicates": len(dup), "negative_amount": len(neg), "missing_receiver": len(miss),
                     "unknown_account": len(unknown), "bad_timestamp": len(badts), "self_transfer": len(selft),
                     "messy_tx_type_fixable": int(k)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="../data/raw/amlsim")
    p.add_argument("--customers", type=int, default=1500)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--alerts", type=int, default=120)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    summary = Generator(GenConfig(customers=a.customers, days=a.days, alerts=a.alerts, seed=a.seed)).run(Path(a.out))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
