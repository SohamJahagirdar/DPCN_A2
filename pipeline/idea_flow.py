"""Independent Follow the Idea study. Importing this module performs no I/O.

Run ``python -B -m pipeline.idea_flow --help``. Study files must be outside
the checkout. Only acquisition commands contact OpenAlex, with an explicit key.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

VERSION = "follow-idea-v1"
PREFIX = "follow-idea-pilot-v1|42|"
FIELDS = ("Physics and Astronomy", "Mathematics", "Biochemistry, Genetics and Molecular Biology")
COMPLETE = ("complete", "complete_empty", "complete_metadata_limited")
SELECT = "id,ids,doi,title,publication_year,publication_date,type,primary_topic,primary_location,cited_by_count,referenced_works,updated_date,created_date,language,is_retracted,is_xpac"


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def work_id(value):
    """Accept only a short ID or an HTTPS OpenAlex work URL; never fuzzy-match."""
    if not isinstance(value, str):
        raise ValueError("Missing/invalid OpenAlex work ID")
    value = value.strip()
    value = re.sub(r"^https://openalex\.org/", "", value, flags=re.I)
    if not re.fullmatch(r"W[1-9][0-9]*", value, re.I):
        raise ValueError("Invalid OpenAlex work ID")
    return value.upper()


def doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip(), flags=re.I).lower()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_rank(wid, prefix=PREFIX):
    return hashlib.sha256((prefix + wid).encode()).hexdigest()


def write_json(path, data, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("Refusing to overwrite immutable artifact")
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    os.replace(tmp, path)


def outside(path, repo):
    path, repo = Path(path).resolve(), Path(repo).resolve()
    if path == repo or repo in path.parents or path in repo.parents:
        raise ValueError("Study/review directory must be a separate directory outside the checkout")
    return path


def original_seeds(repo):
    """Reconcile actual input IDs. Attribution rows never become extra papers."""
    repo = Path(repo)
    with (repo / "outputs/citation_paper_metrics.csv").open(encoding="utf-8-sig", newline="") as f:
        paper_rows = list(csv.DictReader(f))
    if len({work_id(r["work_id"]) for r in paper_rows}) != len(paper_rows):
        raise ValueError("Duplicate original work IDs in paper metrics")
    papers = {work_id(r["work_id"]): r for r in paper_rows}
    attributed = {}
    with (repo / "outputs/group18_data.csv").open(encoding="utf-8-sig", newline="") as f:
        count = 0
        for r in csv.DictReader(f):
            count += 1
            wid = work_id(r["openalex_work_id"])
            if wid in attributed:
                for col in ("year", "field", "title", "doi", "citations", "openalex_type"):
                    if attributed[wid][col] != r[col]:
                        raise ValueError("Conflicting original metadata for " + wid)
            attributed[wid] = r
    if set(attributed) != set(papers):
        raise ValueError("Original CSV work-ID populations differ")
    aliases = defaultdict(set)
    for wid, p in papers.items():
        if doi(p["doi"]):
            aliases[doi(p["doi"])].add(wid)
    conflicts = {wid for ids in aliases.values() if len(ids) > 1 for wid in ids}
    rows = []
    for wid, p in sorted(papers.items()):
        a = attributed[wid]
        n = int(p["citations"])
        rows.append(dict(work_id=wid, homes=sorted(p["homes"].split(";")), title=p["title"], year=int(p["year"]),
                         stored_citations=n, citation_band="0-9" if n < 10 else "10-99" if n < 100 else "100+",
                         sampling_field=a["field"], stored_type=a["openalex_type"], doi=doi(p["doi"]),
                         identity_conflict=wid in conflicts, selection_rank=stable_rank(wid)))
    return rows, dict(attribution_rows=count, original_work_ids=len(rows), original_doi_collision_groups=sum(len(v) > 1 for v in aliases.values()))


def select_pilot(seeds):
    frame, chosen, decisions, used = [], [], [], set()
    for s in sorted(seeds, key=lambda x: x["work_id"]):
        reasons = []
        if not s["title"] or not s["sampling_field"]:
            reasons.append("missing_sampling_metadata")
        if s["identity_conflict"]:
            reasons.append("ambiguous_original_doi")
        if not 2016 <= s["year"] <= 2022 or s["sampling_field"] not in FIELDS or s["citation_band"] == "100+":
            reasons.append("outside_pilot_strata")
        frame.append(dict(s, exclusion_reasons=reasons))
    for inst, field, cohort, band in itertools.product(("IISc", "TIFR"), FIELDS, ("2016-2018", "2019-2022"), ("0-9", "10-99")):
        lo, hi = map(int, cohort.split("-"))
        candidates = sorted((s for s in frame if not s["exclusion_reasons"] and inst in s["homes"] and
                             s["sampling_field"] == field and lo <= s["year"] <= hi and s["citation_band"] == band),
                            key=lambda s: (s["selection_rank"], s["work_id"]))
        cell = [inst, field, cohort, band]
        selected = next((s for s in candidates if s["work_id"] not in used), None)
        decisions.append(dict(cell=cell, eligible_candidates=len(candidates), selected=selected["work_id"] if selected else None,
                              joint_collision_skips=[s["work_id"] for s in candidates if s["work_id"] in used]))
        if selected:
            used.add(selected["work_id"])
            chosen.append(dict(selected, sampling_cell=cell, sampling_allocation=inst))
    return frame, chosen, decisions


SCHEMA = """
CREATE TABLE IF NOT EXISTS seeds(original_id TEXT PRIMARY KEY, canonical_id TEXT, data TEXT NOT NULL, pilot INTEGER NOT NULL, identity_status TEXT NOT NULL DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS seeds_canonical ON seeds(canonical_id);
CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, date TEXT, type TEXT, field_id TEXT, field TEXT, data TEXT NOT NULL, snapshot TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS works_doi ON works(doi);
CREATE INDEX IF NOT EXISTS works_doi_ids ON works(doi,id);
CREATE INDEX IF NOT EXISTS works_analysis ON works(id,field_id,field,year,date,type);
CREATE TABLE IF NOT EXISTS aliases(original_id TEXT PRIMARY KEY, canonical_id TEXT NOT NULL, evidence TEXT NOT NULL, retrieved_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS frontiers(id TEXT PRIMARY KEY, stage TEXT NOT NULL, kind TEXT NOT NULL, targets TEXT NOT NULL, params TEXT NOT NULL, cursor TEXT, status TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0, returned INTEGER NOT NULL DEFAULT 0, expected INTEGER, reason TEXT, seen_cursors TEXT NOT NULL DEFAULT '[]', sampling TEXT, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS frontiers_stage ON frontiers(stage,status);
CREATE TABLE IF NOT EXISTS members(frontier_id TEXT NOT NULL,work_id TEXT NOT NULL,PRIMARY KEY(frontier_id,work_id));
CREATE TABLE IF NOT EXISTS citations(citing TEXT NOT NULL,cited TEXT NOT NULL,chronology TEXT NOT NULL,PRIMARY KEY(citing,cited));
CREATE INDEX IF NOT EXISTS citations_cited ON citations(cited);
CREATE TABLE IF NOT EXISTS edge_evidence(citing TEXT NOT NULL,cited TEXT NOT NULL,frontier_id TEXT NOT NULL,page TEXT NOT NULL,retrieved_utc TEXT NOT NULL,PRIMARY KEY(citing,cited,frontier_id,page));
CREATE INDEX IF NOT EXISTS edge_evidence_cited ON edge_evidence(cited,frontier_id,citing);
CREATE INDEX IF NOT EXISTS edge_evidence_frontier ON edge_evidence(frontier_id,cited,citing);
CREATE TABLE IF NOT EXISTS pages(frontier_id TEXT NOT NULL,cursor TEXT NOT NULL,snapshot TEXT NOT NULL,results INTEGER NOT NULL,retrieved_utc TEXT NOT NULL,PRIMARY KEY(frontier_id,cursor));
CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,path TEXT NOT NULL,params TEXT NOT NULL,status INTEGER,credits_reserved INTEGER NOT NULL,cost_usd REAL,snapshot TEXT,at_utc TEXT NOT NULL,error TEXT);
CREATE TABLE IF NOT EXISTS checks(name TEXT PRIMARY KEY,data TEXT NOT NULL,at_utc TEXT NOT NULL);
"""


class Study:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.manifest = json.loads((self.path / "study_manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("version") != VERSION:
            raise ValueError("Unrecognized study format")
        outside(self.path, self.manifest["repository"])
        self.db = sqlite3.connect(self.path / "study.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def check(self, name, data):
        self.db.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?)", (name, json.dumps(data, allow_nan=False), utcnow()))
        self.db.commit()
        write_json(self.path / "verification" / (name + ".json"), {"at_utc": utcnow(), **data})

    def canonical(self, wid):
        seen = set()
        while wid not in seen:
            seen.add(wid)
            row = self.db.execute("SELECT canonical_id FROM aliases WHERE original_id=?", (wid,)).fetchone()
            if not row or row[0] == wid:
                return wid
            wid = row[0]
        raise ValueError("Provider alias cycle")

    def put_work(self, data, snapshot, requested=None):
        wid = work_id(data.get("id"))
        pt = data.get("primary_topic") or {}
        field = pt.get("field") or {}
        year = data.get("publication_year")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
            raise ValueError("Provider publication year is not an integer")
        # Preserve first-seen metadata; later responses remain immutable evidence.
        self.db.execute("INSERT OR IGNORE INTO works VALUES(?,?,?,?,?,?,?,?,?,?)", (
            wid, doi(data.get("doi")), data.get("title"), year, data.get("publication_date"), data.get("type"),
            field.get("id"), field.get("display_name"), json.dumps(data, ensure_ascii=False), snapshot))
        if requested and requested != wid:
            self.db.execute("INSERT OR REPLACE INTO aliases VALUES(?,?,?,?)", (requested, wid, snapshot, utcnow()))
        if requested:
            self.db.execute("UPDATE seeds SET canonical_id=?,identity_status=? WHERE original_id=?",
                            (wid, "provider_alias" if requested != wid else "resolved", requested))
        else:
            self.db.execute("UPDATE seeds SET canonical_id=?,identity_status='resolved' WHERE original_id=? AND canonical_id IS NULL", (wid, wid))
        return wid

    def frontier(self, stage, kind, targets, params, sampling=None):
        targets = sorted(set(targets))
        payload = [VERSION, stage, kind, targets, params]
        fid = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        now = utcnow()
        self.db.execute("INSERT OR IGNORE INTO frontiers(id,stage,kind,targets,params,cursor,status,sampling,created_utc,updated_utc) VALUES(?,?,?,?,?,?,'pending',?,?,?)",
                        (fid, stage, kind, json.dumps(targets), json.dumps(params, sort_keys=True), "*", json.dumps(sampling), now, now))
        self.db.commit()
        return fid

    def plan(self, stage, batch_size=100):
        if not 1 <= batch_size <= 100:
            raise ValueError("Batch size must be 1-100")
        if stage not in ("pilot-metadata", "full-metadata", "pilot", "full"):
            raise ValueError("Invalid direct acquisition stage")
        is_pilot = stage.startswith("pilot")
        metadata = stage.endswith("metadata")
        rows = self.db.execute("SELECT * FROM seeds" + (" WHERE pilot=1" if is_pilot else "") + " ORDER BY original_id").fetchall()
        targets = sorted({r["original_id"] if metadata else r["canonical_id"] for r in rows if metadata or r["canonical_id"]})
        ids = []
        for start in range(0, len(targets), batch_size):
            batch = targets[start:start + batch_size]
            if metadata:
                params = dict(filter="openalex_id:" + "|".join(batch), corpus="all", select=SELECT, per_page=100)
            else:
                params = dict(filter="cites:" + "|".join(batch) + ",to_publication_date:" + self.manifest["cutoff"], corpus="core", select=SELECT, per_page=100)
            ids.append(self.frontier(stage, "metadata" if metadata else "citers", batch, params))
        return ids

    @contextmanager
    def acquisition_lock(self):
        f = (self.path / ".acquisition.lock").open("a+b")
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                if not f.read(1):
                    f.write(b"0"); f.flush()
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            f.close()  # OS releases the lock even after an interrupted process.


def initialize(repo, directory, cutoff="2026-10-15"):
    repo = Path(repo).resolve()
    datetime.strptime(cutoff, "%Y-%m-%d")
    path = outside(directory, repo)
    if path.exists() and any(path.iterdir()):
        if not (path / "study_manifest.json").exists():
            raise ValueError("Nonempty unrecognized study directory; refusing to mix contents")
        study = Study(path)
        if study.manifest["cutoff"] != cutoff or study.manifest["repository"] != str(repo):
            raise ValueError("Existing study scope differs")
        for rel, digest in study.manifest["protected_sha256"].items():
            if sha256(repo / rel) != digest:
                raise ValueError("Protected source snapshot has changed")
        return study
    seeds, diagnostics = original_seeds(repo)
    frame, pilot, cells = select_pilot(seeds)
    protected = sorted([*repo.glob("outputs/**/*.csv"), *repo.glob("data/external/*.csv"), repo / "dashboard/index.html"])
    hashes = {p.relative_to(repo).as_posix(): sha256(p) for p in protected}
    # Recheck central reconnaissance facts from current inputs, never repair them.
    own = {s["work_id"]: s for s in seeds}
    counts, pairs, orphan_targets = Counter(), set(), set()
    inversions = orphan = 0
    with (repo / "outputs/citation_network.csv").open(encoding="utf-8-sig", newline="") as f:
        for e in csv.DictReader(f):
            s, t = work_id(e["source_id"]), work_id(e["target_id"])
            pairs.add((s, t)); counts[e["edge_type"]] += 1
            if e["edge_type"] == "inflow" and t not in own:
                orphan += 1; orphan_targets.add(t)
            if e["edge_type"] == "internal" and own[s]["year"] < own[t]["year"]:
                inversions += 1
    diagnostics.update(edge_counts=dict(counts), unique_pairs=len(pairs), orphan_inflow_edges=orphan,
                       orphan_inflow_targets=len(orphan_targets), internal_year_inversions=inversions)
    def git(*args):
        return subprocess.check_output(["git", "-c", "safe.directory=" + repo.as_posix(), "-C", str(repo), *args], text=True).strip()
    manifest = dict(version=VERSION, run_id=VERSION + "-" + utcnow().replace(":", ""), created_utc=utcnow(), repository=str(repo),
                    git_head=git("rev-parse", "HEAD"), branch=git("branch", "--show-current"), cutoff=cutoff,
                    retrieval_window="Recorded per immutable response; later than publication cutoff; not a historical index snapshot",
                    provider="OpenAlex", corpus="core", selected_fields=SELECT.split(","), primary_taxonomy="OpenAlex primary_topic.field.id; first-seen frozen record",
                    sampling_prefix=PREFIX, pilot_cells=cells, seed_count=len(seeds), pilot_count=len(pilot), protected_sha256=hashes,
                    budget_policy="No paid spend; live free allowance check, conservative credit reservations and reserve; no key rotation",
                    query_completeness="Exhausted cursor AND all returned relationships recoverable; metadata completeness reported separately",
                    known_legacy_limits=diagnostics)
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / "study_manifest.json", manifest, immutable=True)
    write_json(path / "manifests/pilot_selection.json", dict(prefix=PREFIX, cells=cells, seeds=pilot), immutable=True)
    write_csv(path / "manifests/candidate_frame.csv", list(frame[0]), frame)
    study = Study(path)
    pids = {s["work_id"] for s in pilot}
    for s in seeds:
        if s["work_id"] in pids:
            s = next(p for p in pilot if p["work_id"] == s["work_id"])
        study.db.execute("INSERT INTO seeds(original_id,data,pilot) VALUES(?,?,?)", (s["work_id"], json.dumps(s), int(s["work_id"] in pids)))
    study.db.commit()
    study.plan("pilot-metadata")
    study.check("initialization", dict(pilot_count=len(pilot), original_seed_count=len(seeds), legacy=diagnostics))
    return study


def chronology(citer, cited):
    cy, ty = citer.get("year"), cited.get("year")
    if cy is None or ty is None:
        return "unknown_year"
    if cy < ty:
        return "year_inversion"
    if cy == ty:
        return "same_year_indeterminate"
    return "later_year"


def reverse_reach(seed, edges, max_depth=2):
    incoming = defaultdict(set)
    for citing, cited in edges:
        if citing != cited:
            incoming[cited].add(citing)
    distances, queue = {seed: 0}, deque([seed])
    while queue:
        node = queue.popleft()
        if distances[node] >= max_depth:
            continue
        for nxt in sorted(incoming[node]):
            if nxt not in distances:
                distances[nxt] = distances[node] + 1
                queue.append(nxt)
    return distances


def status(study):
    db = study.db
    return dict(original_seeds=db.execute("SELECT count(*) FROM seeds").fetchone()[0],
                resolved_original_seeds=db.execute("SELECT count(*) FROM seeds WHERE canonical_id IS NOT NULL").fetchone()[0],
                unique_canonical_seeds=db.execute("SELECT count(DISTINCT canonical_id) FROM seeds").fetchone()[0],
                unique_acquired_works=db.execute("SELECT count(*) FROM works").fetchone()[0],
                unique_citation_edges=db.execute("SELECT count(*) FROM citations").fetchone()[0],
                frontiers=[dict(r) for r in db.execute("SELECT stage,status,count(*) AS count,sum(pages) AS pages,sum(returned) AS returned FROM frontiers GROUP BY stage,status ORDER BY stage,status")],
                requests=db.execute("SELECT count(*) FROM requests").fetchone()[0],
                conservative_reserved_credits=db.execute("SELECT coalesce(sum(credits_reserved),0) FROM requests").fetchone()[0],
                checks={r["name"]: {k:v for k,v in json.loads(r["data"]).items() if k in
                        ("passed","gates","reason","eligible_to_acquire","stage","stopped_reason","pilot_count","original_seed_count","checked_utc","free_remaining_usd")}
                        for r in db.execute("SELECT * FROM checks")})


def verify_study(study):
    """Check immutable response bytes and normalized relational invariants offline."""
    failures=[]
    snapshots=[r[0] for r in study.db.execute("SELECT DISTINCT snapshot FROM requests WHERE snapshot IS NOT NULL")]
    for digest in snapshots:
        path=study.path/"snapshots"/(digest+".json.gz")
        if not path.is_file() or sha256(path)!=digest:
            failures.append(dict(snapshot=digest,reason="missing_or_changed_snapshot"))
    dangling=study.db.execute("SELECT count(*) FROM citations e LEFT JOIN works s ON s.id=e.citing LEFT JOIN works t ON t.id=e.cited WHERE s.id IS NULL OR t.id IS NULL").fetchone()[0]
    without_evidence=study.db.execute("SELECT count(*) FROM citations e WHERE NOT EXISTS (SELECT 1 FROM edge_evidence p WHERE p.citing=e.citing AND p.cited=e.cited)").fetchone()[0]
    known=set(snapshots)
    referenced={r[0] for r in study.db.execute("SELECT snapshot FROM works UNION SELECT snapshot FROM pages UNION SELECT page FROM edge_evidence UNION SELECT evidence FROM aliases")}
    unbacked=sorted(referenced-known)
    for f in study.db.execute("SELECT * FROM frontiers WHERE status IN ('complete','complete_empty','complete_metadata_limited')"):
        actual=study.db.execute("SELECT count(*) FROM members WHERE frontier_id=?",(f["id"],)).fetchone()[0]
        if f["cursor"] or actual!=f["returned"] or actual!=f["expected"]:
            failures.append(dict(frontier=f["id"],reason="invalid_completion_accounting"))
    result=dict(passed=not failures and not dangling and not without_evidence and not unbacked,snapshots_checked=len(snapshots),
                dangling_edges=dangling,edges_without_evidence=without_evidence,failures=failures,
                provenance_without_request_snapshot=unbacked,
                output_sha256={p.relative_to(study.path).as_posix():sha256(p) for p in (study.path/"results").glob("*") if p.is_file()})
    study.check("study_integrity",result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "status", "budget", "acquire", "validate-pilot", "analyze", "sample-g2", "preview", "verify-inputs", "verify-study"))
    p.add_argument("--study", required=True, type=Path)
    p.add_argument("--repo", type=Path)
    p.add_argument("--review", type=Path)
    p.add_argument("--credential-file", type=Path)
    p.add_argument("--stage", choices=("pilot-metadata", "pilot", "pilot-check", "full-metadata", "full", "full-check", "g2"), default="pilot-metadata")
    p.add_argument("--cutoff", default="2026-10-15")
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--max-calls", type=int, default=9800)
    p.add_argument("--max-seconds", type=float, default=3600)
    p.add_argument("--interval", type=float, default=0.25)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args(argv)
    study = None
    try:
        if args.command == "prepare":
            if not args.repo:
                p.error("prepare requires --repo")
            study = initialize(args.repo, args.study, args.cutoff)
            result = status(study)
        else:
            study = Study(args.study)
            if args.command == "status":
                result = status(study)
            elif args.command in ("budget", "acquire"):
                from pipeline.idea_flow_fetch import Client, acquire
                with study.acquisition_lock():
                    client = Client(study, credential_file=args.credential_file, max_calls=args.max_calls,
                                    max_seconds=args.max_seconds, interval=args.interval)
                    result = client.establish_budget()
                    if args.command == "acquire":
                        result = acquire(study, client, args.stage, args.batch_size, args.workers)
            elif args.command in ("validate-pilot", "analyze", "sample-g2"):
                from pipeline.idea_flow_metrics import validate_pilot, analyze, sample_g2
                with study.acquisition_lock():
                    result = {"validate-pilot": validate_pilot, "analyze": analyze, "sample-g2": sample_g2}[args.command](study)
            elif args.command == "preview":
                if not args.review:
                    p.error("preview requires --review")
                from pipeline.idea_flow_dashboard import preview
                with study.acquisition_lock():
                    result = preview(study, args.review)
            elif args.command == "verify-study":
                with study.acquisition_lock():
                    result = verify_study(study)
                if not result["passed"]:
                    raise ValueError("Study integrity checks failed; inspect verification/study_integrity.json")
            else:
                root = Path(study.manifest["repository"])
                changed = [r for r, h in study.manifest["protected_sha256"].items() if sha256(root / r) != h]
                result = dict(protected_files=len(study.manifest["protected_sha256"]), changed=changed)
                study.check("protected_inputs", result)
                if changed:
                    raise ValueError("Protected inputs changed")
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError) as e:
        # All explicit errors use safe constants/IDs, never HTTP bodies or keys.
        print(json.dumps(dict(status="stopped", reason=str(e)), ensure_ascii=True))
        return 2
    finally:
        if study:
            study.close()


if __name__ == "__main__":
    raise SystemExit(main())
