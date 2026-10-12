"""Minimal OpenAlex client with on-disk caching, cursor paging and budget awareness.

Every response is cached under data/cache/, keyed by URL + params, so an interrupted
run (e.g. the daily budget ran out) resumes where it stopped without paying twice.
"""
import gzip
import hashlib
import json
import time

import requests

import config

BASE = "https://api.openalex.org"


class BudgetExhausted(RuntimeError):
    pass


class OpenAlex:
    def __init__(self, max_calls=None, verbose=True):
        self.key = config.openalex_api_key()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"DPCN-group{config.GROUP}-research-mapping"
        if self.key:
            self.session.headers["Authorization"] = f"Bearer {self.key}"
        self.calls = 0          # network calls made in this process
        self.cache_hits = 0
        self.max_calls = max_calls
        self.remaining_usd = None
        self.verbose = verbose

    # ------------------------------------------------------------------ caching
    @staticmethod
    def _cache_path(path, params):
        blob = json.dumps([path, sorted(params.items())], sort_keys=True)
        h = hashlib.sha1(blob.encode()).hexdigest()
        return config.CACHE / h[:2] / f"{h}.json.gz"

    def get(self, path, params=None, use_cache=True):
        params = dict(params or {})
        if config.MAILTO:
            params.setdefault("mailto", config.MAILTO)
        cp = self._cache_path(path, params)
        if use_cache and cp.exists():
            self.cache_hits += 1
            with gzip.open(cp, "rt", encoding="utf-8") as f:
                return json.load(f)
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExhausted(f"max_calls={self.max_calls} reached for this run")

        for attempt in range(8):
            try:
                r = self.session.get(BASE + path, params=params, timeout=90)
            except requests.RequestException as e:
                wait = 2 ** attempt
                print(f"  network error {e!r}; retry in {wait}s")
                time.sleep(wait)
                continue
            self.calls += 1
            rem = r.headers.get("X-RateLimit-Remaining-USD")
            if rem is not None:
                try:
                    self.remaining_usd = float(rem)
                except ValueError:
                    pass
            if r.status_code == 200:
                data = r.json()
                cp.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(cp, "wt", encoding="utf-8") as f:
                    json.dump(data, f)
                if self.verbose and self.calls % 50 == 0:
                    print(f"  [openalex] calls={self.calls} cache_hits={self.cache_hits} "
                          f"remaining_usd={self.remaining_usd}")
                return data
            if r.status_code == 429:
                body = r.text
                if "budget" in body.lower():
                    raise BudgetExhausted(
                        "OpenAlex daily budget exhausted. Re-run after midnight UTC (05:30 IST); "
                        "cached pages will be reused. " + body[:300])
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"OpenAlex {r.status_code} for {r.url}: {r.text[:500]}")
        raise RuntimeError(f"OpenAlex request kept failing: {path} {params}")

    # ------------------------------------------------------------------ paging
    def paginate(self, path, filter_, select=None, per_page=100, extra=None):
        """Yield results for a list endpoint using cursor paging (deterministic, cache-replayable)."""
        cursor = "*"
        while cursor:
            params = {"filter": filter_, "per_page": per_page, "cursor": cursor}
            if select:
                params["select"] = select
            if extra:
                params.update(extra)
            data = self.get(path, params)
            for item in data.get("results", []):
                yield item
            cursor = data.get("meta", {}).get("next_cursor")
            if not data.get("results"):
                break

    def count(self, path, filter_):
        data = self.get(path, {"filter": filter_, "per_page": 1})
        return data["meta"]["count"]

    def group_by(self, path, filter_, key):
        data = self.get(path, {"filter": filter_, "group_by": key})
        return data.get("group_by", [])

    def entity(self, path):
        """Single-entity lookup (free in OpenAlex pricing)."""
        return self.get(path, {})

    def status(self):
        return f"network calls={self.calls}, cache hits={self.cache_hits}, remaining_usd={self.remaining_usd}"


def short_id(x):
    """'https://openalex.org/W123' -> 'W123'"""
    if not x:
        return x
    return x.rsplit("/", 1)[-1]


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
