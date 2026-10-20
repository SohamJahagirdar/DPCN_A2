"""Budgeted OpenAlex acquisition using only the Python standard library.

No credential, network or filesystem access occurs on import. HTTP errors are
reported by status only; keys and response authorization headers are never saved.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.error
import urllib.parse
import urllib.request

from pipeline.idea_flow import COMPLETE, SELECT, chronology, status, utcnow, work_id, write_json

BASE = "https://api.openalex.org"


def decode_response(payload, encoding):
    if encoding.lower() == "gzip":
        payload=gzip.decompress(payload)
    elif encoding and encoding.lower() != "identity":
        raise ValueError("Unexpected HTTP content encoding")
    return json.loads(payload)


class StopAcquisition(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("OpenAlex HTTP " + str(code))


def free_allowance(data):
    """Fail closed unless the provider reports used/remaining USD and list cost.

    Even paid/prepaid accounts can use at most the unused part of the documented
    $1 daily free allowance. Paid balances are never added to this ceiling.
    """
    r = data.get("rate_limit") or {}
    keys = ("daily_budget_usd", "daily_used_usd", "daily_remaining_usd")
    if any(not isinstance(r.get(k), (int, float)) or isinstance(r.get(k), bool) for k in keys):
        raise StopAcquisition("Unrecognized budget response; free allowance cannot be established")
    if any(not math.isfinite(r[k]) or r[k] < 0 for k in keys):
        raise StopAcquisition("Invalid provider budget")
    costs = r.get("endpoint_costs_usd") or {}
    if costs.get("list") != 0.0001 or costs.get("singleton") != 0:
        raise StopAcquisition("Provider tariff changed; review required before retrieval")
    remaining = max(0, min(1.0, r["daily_budget_usd"]) - r["daily_used_usd"])
    remaining = min(remaining, r["daily_remaining_usd"])
    return dict(free_remaining_usd=remaining, free_remaining_credits=int(round(remaining * 10000)),
                daily_budget_usd=r["daily_budget_usd"], daily_used_usd=r["daily_used_usd"],
                daily_remaining_usd=r["daily_remaining_usd"], resets_at=r.get("resets_at"),
                list_cost_usd=costs["list"], singleton_cost_usd=0,
                checked_utc=utcnow(), paid_spend_authorized=False)


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        if u.scheme != "https" or u.hostname != "api.openalex.org":
            raise ProviderError("unsafe_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, study, credential_file=None, max_calls=9800, max_seconds=3600,
                 interval=0.25, transport=None, sleep=time.sleep, clock=time.monotonic):
        self.study, self.max_calls, self.max_seconds = study, max_calls, max_seconds
        self.interval, self.sleep, self.clock = max(0.1, interval), sleep, clock
        self.started, self.last = clock(), None
        self.calls = self.reserved = self.inflight = self.total_reserved = 0
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.allowance = None
        self.reserve_credits = 20
        self.transport = transport
        self.key = None
        if transport is None:
            raw = os.environ.get("OPENALEX_API_KEY", "")
            if not raw.strip():
                path = Path(credential_file) if credential_file else Path(study.manifest["repository"]) / "openalex_key.txt"
                if path.is_file():
                    raw = path.read_text(encoding="utf-8")
            values = [v.strip() for v in raw.replace(",", "\n").splitlines() if v.strip() and not v.strip().startswith("#")]
            if not values:
                raise StopAcquisition("No configured credential; use a local credential file, never chat or command-line key values")
            self.key = values[0]  # Never rotate through team members' allowances.
        self.opener = urllib.request.build_opener(SameHostRedirect()) if transport is None else None

    def _http(self, path, params):
        if self.transport:
            return self.transport(path, params)
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.key,
                                                   "Accept-Encoding": "gzip",
                                                   "User-Agent": "DPCN18-FollowIdea/1 metadata-research"})
        try:
            with self.opener.open(req, timeout=40) as response:
                data = decode_response(response.read(),response.headers.get("Content-Encoding", ""))
                headers = {k.lower(): v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit")}
                return response.status, data, headers
        except urllib.error.HTTPError as e:
            # Never log an HTTP body, URL or the headers sent with a request.
            return e.code, {}, {}
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, {}, {}

    def establish_budget(self):
        code, data, _ = self._http("/rate-limit", {})
        if code != 200:
            raise StopAcquisition("Authentication/free-budget probe failed (HTTP " + str(code) + "); no data acquisition authorized by the client")
        self.allowance = free_allowance(data)
        self.reserved = self.inflight
        self.study.check("budget_latest", self.allowance)
        return self.allowance

    def _sanitize(self, value):
        if isinstance(value, dict):
            return {k: self._sanitize(v) for k, v in value.items() if k.lower() not in
                    ("api_key", "authorization", "access_token", "token", "email")}
        if isinstance(value, list):
            return [self._sanitize(v) for v in value]
        if isinstance(value, str) and self.key:
            return value.replace(self.key, "[redacted]")
        return value

    def request(self, path, params, billable=True):
        if not (path == "/works" or (path.startswith("/works/") and work_id(path.split("/")[-1]))):
            raise ValueError("Only work metadata endpoints are permitted")
        if any(k.lower() in ("api_key", "authorization", "token") for k in params):
            raise ValueError("Credentials are forbidden in query parameters")
        params_text = json.dumps(params, sort_keys=True)
        with self.lock:
            cached = self.study.db.execute("SELECT snapshot FROM requests WHERE path=? AND params=? AND status=200 AND snapshot IS NOT NULL ORDER BY id LIMIT 1", (path, params_text)).fetchone()
        if cached:
            snapshot = cached[0]
            with gzip.open(self.study.path / "snapshots" / (snapshot + ".json.gz"), "rt", encoding="utf-8") as f:
                envelope = json.load(f)
            return envelope["response"], snapshot, envelope["retrieved_utc"]
        for attempt in range(5):
            # Only HTTP is concurrent. Reservations, SQLite transactions, budget
            # refreshes and page application share this process-wide lock.
            with self.lock:
                if self.stopping.is_set():
                    raise StopAcquisition("Another frontier checkpointed; resume the study")
                if self.clock() - self.started >= self.max_seconds:
                    raise StopAcquisition("Acquisition wall-time checkpoint")
                if self.calls >= self.max_calls:
                    raise StopAcquisition("Per-run request ceiling reached")
                if self.allowance is None:
                    raise StopAcquisition("Free allowance has not been established")
                if self.calls and self.calls % 100 == 0:
                    self.establish_budget()
                cost = 1 if billable else 0
                if self.allowance["free_remaining_credits"] - self.reserved - cost < self.reserve_credits:
                    raise StopAcquisition("Free allowance safety reserve reached; checkpointed without paid spend")
                if self.last is not None:
                    self.sleep(max(0, self.interval - (self.clock() - self.last)))
                self.last = self.clock()
                now = utcnow()
                rid = self.study.db.execute("INSERT INTO requests(path,params,credits_reserved,at_utc) VALUES(?,?,?,?)", (path, params_text, cost, now)).lastrowid
                self.study.db.commit()
                self.calls += 1; self.reserved += cost; self.inflight += cost; self.total_reserved += cost
            code, data, headers = self._http(path, params)
            with self.lock:
                self.inflight -= cost
                self.study.db.execute("UPDATE requests SET status=?,error=? WHERE id=?", (code, None if code == 200 else "http_" + str(code), rid))
                self.study.db.commit()
                if code == 200:
                    charged = headers.get("x-ratelimit-credits-used")
                    if charged is not None and float(charged) > cost:
                        raise StopAcquisition("Unexpected operation charge; stopped for tariff review")
                    envelope = dict(retrieved_utc=now, path=path, params=params, response=self._sanitize(data))
                    encoded = gzip.compress(json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8"), mtime=0)
                    snapshot = hashlib.sha256(encoded).hexdigest()
                    dest = self.study.path / "snapshots" / (snapshot + ".json.gz")
                    dest.parent.mkdir(exist_ok=True)
                    if not dest.exists():
                        with dest.open("xb") as f:
                            f.write(encoded)
                    self.study.db.execute("UPDATE requests SET snapshot=?,cost_usd=? WHERE id=?", (snapshot, cost / 10000, rid))
                    self.study.db.commit()
                    return envelope["response"], snapshot, now
                if code in (401, 403):
                    raise StopAcquisition("Credential rejected/expired (HTTP " + str(code) + ")")
                if code == 429:
                    self.establish_budget()
                    if self.allowance["free_remaining_credits"] <= self.reserve_credits:
                        raise StopAcquisition("Daily free allowance exhausted")
                elif code and code < 500:
                    raise ProviderError(code)
            self.sleep(min(16, 2 ** attempt))
        raise StopAcquisition("Transient request failures; durable page cursor retained")


def process_page(study, fid, cursor, body, snapshot, at):
    """Commit nodes, edges, evidence and next cursor in ONE transaction."""
    f = study.db.execute("SELECT * FROM frontiers WHERE id=?", (fid,)).fetchone()
    if study.db.execute("SELECT 1 FROM pages WHERE frontier_id=? AND cursor=?", (fid, cursor)).fetchone():
        return  # A replay after a crash is idempotent.
    results, meta = body.get("results"), body.get("meta")
    if not isinstance(results, list) or not isinstance(meta, dict) or not isinstance(meta.get("count"), int):
        raise ValueError("Invalid provider page schema")
    targets = {study.canonical(w) for w in json.loads(f["targets"])}
    aliases = {r["original_id"]: r["canonical_id"] for r in study.db.execute("SELECT * FROM aliases")}
    next_cursor = meta.get("next_cursor")
    seen = json.loads(f["seen_cursors"])
    if next_cursor and (next_cursor == cursor or next_cursor in seen):
        raise ValueError("Repeated provider cursor; frontier is not complete")
    if not results and next_cursor:
        raise ValueError("Empty page with a continuation cursor; frontier is not complete")
    unmatched = 0
    with study.db:
        for raw in results:
            wid = study.put_work(raw, snapshot)
            study.db.execute("INSERT OR IGNORE INTO members VALUES(?,?)", (fid, wid))
            if f["kind"] == "metadata":
                if wid in targets:
                    study.db.execute("UPDATE seeds SET canonical_id=?,identity_status='resolved' WHERE original_id=?", (wid, wid))
                continue
            refs = raw.get("referenced_works")
            if not isinstance(refs, list):
                unmatched += 1; continue
            matched = set()
            for ref in refs:
                ref = work_id(ref)
                matched.add(aliases.get(ref, ref))
            matched &= targets
            if not matched:
                unmatched += 1
            for cited in matched:
                if wid == cited:
                    # A provider same-ID reference reaches G0 again, not a
                    # distinct G1 paper. Raw references remain in snapshots and
                    # works.data; exports explicitly flag these identity loops.
                    continue
                target = study.db.execute("SELECT year FROM works WHERE id=?", (cited,)).fetchone()
                if not target:
                    raise ValueError("Citation target metadata is unresolved")
                source = study.db.execute("SELECT year FROM works WHERE id=?",(wid,)).fetchone()
                flag = chronology(dict(source), dict(target))
                study.db.execute("INSERT OR IGNORE INTO citations VALUES(?,?,?)", (wid, cited, flag))
                study.db.execute("INSERT OR IGNORE INTO edge_evidence VALUES(?,?,?,?,?)", (wid, cited, fid, snapshot, at))
        study.db.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (fid, cursor, snapshot, len(results), at))
        returned = study.db.execute("SELECT count(*) FROM members WHERE frontier_id=?", (fid,)).fetchone()[0]
        expected = f["expected"] if f["expected"] is not None else meta["count"]
        reason = f["reason"]
        if unmatched:
            reason = "unmatched_returned_references"
        if expected != meta["count"]:
            reason = "provider_count_drift"
        state = "running" if next_cursor else "complete_empty" if returned == 0 else "complete"
        if reason or (not next_cursor and returned != expected):
            reason = reason or "unique_result_count_mismatch"
            state = "inconsistent"
        seen.append(cursor)
        study.db.execute("UPDATE frontiers SET cursor=?,status=?,pages=pages+1,returned=?,expected=?,reason=?,seen_cursors=?,updated_utc=? WHERE id=?",
                         (next_cursor, state, returned, expected, reason, json.dumps(seen), at, fid))


def repair_missing_seed_metadata(study, client, pilot):
    clause = " AND pilot=1" if pilot else ""
    rows = study.db.execute("SELECT original_id FROM seeds WHERE canonical_id IS NULL AND identity_status!='not_found'" + clause + " ORDER BY original_id").fetchall()
    for row in rows:
        wid = row[0]
        try:
            body, snapshot, _ = client.request("/works/" + wid, {"select": SELECT}, billable=False)
            with study.db:
                study.put_work(body, snapshot, requested=wid)
        except ProviderError as e:
            if e.code != 404:
                raise
            with study.db:
                study.db.execute("UPDATE seeds SET identity_status='not_found' WHERE original_id=?", (wid,))


def plan_checks(study, full=False):
    condition = "" if full else " WHERE pilot=1"
    candidates = [json.loads(r["data"]) | {"canonical_id": r["canonical_id"]} for r in study.db.execute("SELECT * FROM seeds" + condition) if r["canonical_id"]]
    from pipeline.idea_flow import stable_rank
    eligible = sorted((s for s in candidates if s["stored_citations"] >= 10), key=lambda s: stable_rank(s["work_id"], "individual-check-v1|"))
    for s in eligible[:6 if full else 3]:
        wid = s["canonical_id"]
        params = dict(filter="cites:" + wid + ",to_publication_date:" + study.manifest["cutoff"], corpus="core", select=SELECT, per_page=100)
        study.frontier("full-check" if full else "pilot-check", "citers", [wid], params)


def acquire(study, client, stage, batch_size=100, workers=1):
    if not 1 <= workers <= 8:
        raise ValueError("Workers must be 1-8")
    if stage.startswith("full"):
        gate = study.db.execute("SELECT data FROM checks WHERE name='pilot_acceptance'").fetchone()
        if not gate or not json.loads(gate[0]).get("passed"):
            raise StopAcquisition("Pilot acceptance gate has not passed")
    if stage in ("pilot", "full"):
        metadata_stage = stage + "-metadata"
        meta_count = study.db.execute("SELECT count(*) FROM frontiers WHERE stage=?", (metadata_stage,)).fetchone()[0]
        pending_identities = study.db.execute("SELECT count(*) FROM seeds WHERE canonical_id IS NULL AND identity_status!='not_found'" + (" AND pilot=1" if stage == "pilot" else "")).fetchone()[0]
        if not meta_count or pending_identities or study.db.execute("SELECT count(*) FROM frontiers WHERE stage=? AND status NOT IN ('complete','complete_empty','complete_metadata_limited')", (metadata_stage,)).fetchone()[0]:
            raise StopAcquisition("Finish seed metadata acquisition first")
    if stage in ("pilot-metadata", "full-metadata", "pilot", "full"):
        study.plan(stage, batch_size)
    elif stage in ("pilot-check", "full-check"):
        plan_checks(study, full=stage == "full-check")
    elif stage == "g2":
        gate = study.db.execute("SELECT data FROM checks WHERE name='g2_selection'").fetchone()
        if not gate or not json.loads(gate[0]).get("eligible_to_acquire"):
            raise StopAcquisition("Full direct-citer and G2 selection gates have not passed")
        client.max_calls = min(client.max_calls, 500)
    reason = None
    with study.db:
        # Operational stop reasons are not page-consistency failures. Clear them
        # on an authorized resume; inconsistent frontiers remain blocked.
        study.db.execute("UPDATE frontiers SET status='pending',reason=NULL WHERE stage=? AND status IN ('partial','failed')", (stage,))
    frontiers = study.db.execute("SELECT * FROM frontiers WHERE stage=? ORDER BY id", (stage,)).fetchall()
    def run_frontier(fid):
        try:
            while True:
                with client.lock:
                    f = study.db.execute("SELECT * FROM frontiers WHERE id=?", (fid,)).fetchone()
                    if f["status"] in COMPLETE:
                        return
                    if f["status"] == "inconsistent":
                        raise StopAcquisition("Existing inconsistent frontier requires review")
                    params = json.loads(f["params"])
                    params["cursor"] = f["cursor"] or "*"
                body, snapshot, at = client.request("/works", params)
                with client.lock:
                    if stage == "g2":
                        edges = study.db.execute("SELECT count(*) FROM (SELECT DISTINCT e.citing,e.cited FROM edge_evidence e JOIN frontiers f ON f.id=e.frontier_id WHERE f.stage='g2')").fetchone()[0]
                        if edges + len(body.get("results", [])) > 25000:
                            raise StopAcquisition("Study-wide sampled G2 edge cap reached; cached unapplied page retained")
                    process_page(study, fid, params["cursor"], body, snapshot, at)
                    state = study.db.execute("SELECT status FROM frontiers WHERE id=?", (fid,)).fetchone()[0]
                    if state == "inconsistent":
                        raise StopAcquisition("Page relationship/count consistency gate failed")
        except (StopAcquisition, ProviderError, ValueError) as e:
            client.stopping.set()
            with client.lock, study.db:
                study.db.execute("UPDATE frontiers SET status=CASE WHEN status='inconsistent' THEN status WHEN status IN ('complete','complete_empty') THEN status ELSE 'partial' END,reason=?,updated_utc=? WHERE id=?", (str(e), utcnow(), fid))
            raise
    pending = [f["id"] for f in frontiers if f["status"] not in COMPLETE]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(run_frontier, fid):fid for fid in pending}
        done = 0
        for job in as_completed(jobs):
            try:
                job.result(); done += 1
                if done % 10 == 0:
                    with client.lock:
                        print(json.dumps(dict(progress_stage=stage, completed_frontiers=done, frontiers_this_run=len(pending), requests_this_run=client.calls),ensure_ascii=True),flush=True)
            except (StopAcquisition, ProviderError, ValueError) as e:
                reason = reason or str(e)
    if reason is None and stage.endswith("metadata"):
        try:
            repair_missing_seed_metadata(study, client, stage == "pilot-metadata")
        except (StopAcquisition, ProviderError, ValueError) as e:
            reason = str(e)
    result = dict(stage=stage, stopped_reason=reason, requests_this_run=client.calls, conservative_reserved_credits_this_run=client.total_reserved,
                  reserved_credits_since_budget_check=client.reserved, status=status(study))
    study.check("acquisition_" + stage, result)
    return result
