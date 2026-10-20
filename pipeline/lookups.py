"""Journal quartiles (SCImago SJR, per year) and conference ranks (CORE 2023).

SJR data: SCImago Journal Rank 1999-2025 via the `sjrdata` R package
(github.com/ikashnitsky/sjrdata, data/sjr_journals.rda). scimagojr.com itself blocks
scripted downloads, so the mirror is used; values are identical to the SJR export.
CORE: portal.core.edu.au conference ranks, CORE2023 export.
"""
import pickle
import re

import pandas as pd

import config

SJR_RDA = config.EXTERNAL / "sjr_journals.rda"
SJR_PKL = config.EXTERNAL / "sjr_lookup.pkl"
# pinned to sjrdata v1.0.25 (7 Jun 2026; SJR years up to 2025) so every teammate's build gets the same quartiles
SJR_URL = ("https://raw.githubusercontent.com/ikashnitsky/sjrdata/"
           "f7ed8273edd350cfd36db0a4832a5ce1542cf77f/data/sjr_journals.rda")
CORE_CSV = config.EXTERNAL / "core_2023.csv"


def _norm_issn(s):
    s = re.sub(r"[^0-9Xx]", "", str(s or "")).upper()
    return s if len(s) == 8 else None


class SJR:
    def __init__(self):
        if SJR_PKL.exists():
            self.table, self.years = pickle.loads(SJR_PKL.read_bytes())
            return
        import pyreadr
        if not SJR_RDA.exists():
            import requests
            print("[sjr] downloading SCImago data (sjrdata, ~30 MB) ...")
            r = requests.get(SJR_URL, timeout=600)
            r.raise_for_status()
            SJR_RDA.write_bytes(r.content)
        df = pyreadr.read_r(str(SJR_RDA))["sjr_journals"]
        df = df[df["year"] >= config.YEAR_FROM - 1]
        self.table = {}
        for year, issns, q, sjr, areas, cats in zip(df["year"], df["issn"], df["sjr_best_quartile"], df["sjr"],
                                                    df["areas"], df["categories"]):
            if q not in ("Q1", "Q2", "Q3", "Q4"):
                continue
            for i in str(issns).split(","):
                i = _norm_issn(i)
                if i:
                    self.table.setdefault(i, {})[int(year)] = (q, float(sjr) if sjr == sjr else None, areas)
        self.years = sorted({y for d in self.table.values() for y in d})
        SJR_PKL.write_bytes(pickle.dumps((self.table, self.years)))

    def lookup(self, issns, year):
        """Best quartile of the journal in the publication year (nearest available SJR year otherwise)."""
        for i in issns:
            d = self.table.get(_norm_issn(i))
            if not d:
                continue
            y = min(max(year, self.years[0]), self.years[-1])
            if y in d:
                return d[y]
            nearest = min(d, key=lambda k: abs(k - y))
            return d[nearest]
        return None


_STOP = {"international", "conference", "on", "the", "of", "and", "in", "for", "proceedings", "annual",
         "acm", "ieee", "symposium", "workshop", "joint", "a", "an", "to", "with", "its", "ieee/cvf", "sigplan",
         "usenix", "siam", "acm/ieee", "european", "asian"}


def _words(s):
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"\b(19|20)\d\d\b|\b\d+(st|nd|rd|th)\b", " ", s)
    return [w for w in re.findall(r"[a-z][a-z\-]+", s) if w not in _STOP]


class CORE:
    RANKS = ("A*", "A", "B", "C")

    def __init__(self):
        df = pd.read_csv(CORE_CSV, header=None, dtype=str).fillna("")
        df = df[df[4].isin(self.RANKS)]
        self.by_acr = {}
        self.by_title = {}
        for title, acr, rank in zip(df[1], df[2], df[4]):
            acr = acr.strip()
            if len(acr) >= 3:
                self.by_acr.setdefault(acr.upper(), rank)
            key = " ".join(_words(title))
            if len(key) >= 12:
                self.by_title[key] = rank
        self._cache = {}

    def lookup(self, venue_name):
        if not venue_name:
            return None
        if venue_name in self._cache:
            return self._cache[venue_name]
        rank = None
        # 1) acronym in parentheses or as an upper-case token, e.g. "... (ICRA)" / "AAAI"
        for tok in re.findall(r"\(([A-Za-z\-\*]{3,12})\)", venue_name) + re.findall(r"\b[A-Z]{3,10}\b", venue_name):
            r = self.by_acr.get(tok.upper())
            if r:
                rank = r
                break
        # 2) normalised full-title containment
        if rank is None:
            key = " ".join(_words(venue_name))
            if key in self.by_title:
                rank = self.by_title[key]
            elif len(key) >= 20:
                # venue name is a shortened CORE title ("Neural Information Processing Systems")
                sup = [t for t in self.by_title if key in t]
                # or venue name contains a full CORE title ("Proceedings - 2020 ... <title>")
                sub = [t for t in self.by_title if len(t) >= 25 and t in key]
                if sup:
                    rank = self.by_title[min(sup, key=len)]
                elif sub:
                    rank = self.by_title[max(sub, key=len)]
        self._cache[venue_name] = rank
        return rank
