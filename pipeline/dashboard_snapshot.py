"""Deterministic offline dashboard-only generation from a pinned study release.

No config/Study construction, acquisition, metric export or historical output writes.
The historical baseline is an explicit input independent of the output destination.
"""
import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from pipeline.dashboard import render_dashboard
from pipeline.idea_flow_dashboard import build_payload, render_standalone
from pipeline.rankings import ranked_top
from pipeline.resilience import analyze_resilience

BASELINE_SHA256 = "38d05a4062a151ff68b098bd72908eda4007038a6fd3c873ca40c7a5f8e34ddc"
RELEASE_SHA256 = "eb5a560ea85a6607fb51f973c7e114c34fbda11cfe7c180a59cf48ceeaeca844"
EXTRA_HASHES = {
    "manifests/pilot_selection.json": "80fae0399174c0525896771c77ecd1ff8ca259cc1fa403b26d2516f4152ab160",
    "manifests/g2_selection.json": "df8e2325cbfbe10f48aee5539cfebe51b581d481ea215d2ca192156d8f3b6e63",
}
VENDOR_URLS = (
    "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js",
    "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js",
)
RESULT_INPUTS = ("study_manifest.json", "study.sqlite3", "results/seed_metrics.json",
                 "results/summary.json", "results/g2_summary.json")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_file(path, expected):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Required frozen input missing: " + str(path))
    actual = sha256(path)
    if actual != expected:
        raise ValueError("SHA-256 mismatch for frozen input: " + str(path))
    return actual


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def under(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Manifest path escapes its input root")
    return path


def validate_inputs(repo, study, release_manifest, baseline_html):
    """Check actual consumed inputs before opening the DB or touching output."""
    checked_file(release_manifest, RELEASE_SHA256)
    release = read_json(release_manifest)
    checked_file(baseline_html, BASELINE_SHA256)
    hashes = {str(Path(release_manifest)): RELEASE_SHA256, str(Path(baseline_html)): BASELINE_SHA256}
    for rel in RESULT_INPUTS:
        path = under(study, rel)
        hashes[str(path)] = checked_file(path, release["data_sha256"][rel])
    for rel, digest in EXTRA_HASHES.items():
        path = under(study, rel)
        hashes[str(path)] = checked_file(path, digest)
    rel = "evidence/case_verifications.json"
    path = under(study, rel)
    hashes[str(path)] = checked_file(path, release["evidence_sha256"][path.name])
    manifest = read_json(Path(study) / "study_manifest.json")
    # The new dashboard is the one authorized historical-output exception.
    for rel, digest in manifest["protected_sha256"].items():
        if rel != "dashboard/index.html":
            path = under(repo, rel)
            hashes[str(path)] = checked_file(path, digest)
    if manifest["protected_sha256"]["dashboard/index.html"] != BASELINE_SHA256:
        raise ValueError("Study does not refer to the pinned historical dashboard")
    db_path = Path(study) / "study.sqlite3"
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Study has an uncheckpointed WAL; supply a frozen release copy")
    return manifest, hashes


def baseline_payloads(path, expected=BASELINE_SHA256):
    checked_file(path, expected)
    text = Path(path).read_text(encoding="utf-8")
    payloads = {}
    for name in ("DATA_ALL", "DATA_NF", "COMPARE"):
        match = re.search(r"^const " + name + r" = (.*);[^\r\n]*$", text, re.M)
        if not match:
            raise ValueError("Historical baseline missing " + name)
        payloads[name] = json.loads(match.group(1))
    libraries = re.findall(r"<script>/\* (https://[^ ]+) \*/\n(.*?)\n</script>", text, re.S)
    if len(libraries) != 2 or {u for u, _ in libraries} != set(VENDOR_URLS):
        raise ValueError("Expected exactly the two pinned historical vendor libraries")
    return payloads, dict(libraries)


def enrich_resilience(payload, metrics_path):
    with Path(metrics_path).open(encoding="utf-8-sig", newline="") as f:
        metrics = {r["person"]: dict(r, community=int(r["community"]), betweenness=float(r["betweenness"]))
                   for r in csv.DictReader(f)}
    nodes = {p: dict(name=r["name"], inst=r["inst"], dept=r["department"]) for p, r in metrics.items()}
    edges = [(a, b, dict(weight=w)) for a, b, w in payload["authorship"]["vis"]["edges"]]
    result = analyze_resilience(nodes, edges, metrics)
    summary = payload["authorship"]["summary"]
    if (result["baseline"]["nodes"], result["baseline"]["edges"]) != (summary["faculty_nodes"], summary["faculty_edges"]):
        raise ValueError("Historical graph and faculty metrics disagree")
    payload["resilience"] = result
    rows = [dict(r, n_faculty_coauthors=int(r["n_faculty_coauthors"]), degree_centrality=float(r["degree_centrality"]))
            for r in metrics.values()]
    payload["authorship"]["top_degree"] = ranked_top(rows, "n_faculty_coauthors")


def attach_seed_flags(rows, repo):
    counts = {}
    with (Path(repo) / "outputs/group18_data.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            wid = r["openalex_work_id"].rsplit("/", 1)[-1]
            n = int(r["n_authors"])
            if wid in counts and counts[wid] != n:
                raise ValueError("Conflicting seed author counts: " + wid)
            if (r["authors_gt_12"] == "True") != (n > 12):
                raise ValueError("Seed flag and author count disagree: " + wid)
            counts[wid] = n
    with (Path(repo) / "outputs/citation_paper_metrics.csv").open(encoding="utf-8-sig", newline="") as f:
        homes = {r["work_id"].rsplit("/", 1)[-1]: sorted(r["homes"].split(";")) for r in csv.DictReader(f)}
    ids = {r["original_id"] for r in rows}
    if ids != set(counts) or ids != set(homes) or len(ids) != len(rows):
        raise ValueError("Frozen study and original seed populations disagree")
    for r in rows:
        if sorted(r["homes"]) != homes[r["original_id"]]:
            raise ValueError("Frozen seed institution membership changed")
        r["authors_gt_12"] = counts[r["original_id"]] > 12


def canonical_rows(rows):
    unique = {}
    for r in rows:
        key = r["canonical_id"] or r["original_id"]
        if key not in unique:
            unique[key] = dict(r, homes=list(r["homes"]))
        else:
            prior = unique[key]
            for k in ("authors_gt_12", "observed_citers", "known_field_citers", "unknown_field_citers", "cross_field_citers", "field_id"):
                if prior[k] != r[k]:
                    raise ValueError("Conflicting aliased seed metrics/flag: " + key)
            prior["homes"] = sorted(set(prior["homes"]) | set(r["homes"]))
    return list(unique.values())


def scope_summaries(db, rows):
    """Distinct combined citer counts come from pair sets, never per-seed sums."""
    unique = canonical_rows(rows)
    scopes = {}
    for flag in ("in", "out"):
        scopes[flag] = {}
        for inst in ("All", "IISc", "TIFR"):
            def eligible(r):
                return (inst == "All" or inst in r["homes"]) and (flag == "in" or not r["authors_gt_12"])
            originals = [r for r in rows if eligible(r)]
            rs = [r for r in unique if eligible(r)]
            targets = sorted(r["canonical_id"] for r in rs if r["canonical_id"])
            direct, distinct = db.execute("SELECT count(*),count(DISTINCT citing) FROM citations WHERE cited IN (SELECT value FROM json_each(?))",
                                          (json.dumps(targets),)).fetchone()
            if direct != sum(r["observed_citers"] for r in rs):
                raise ValueError("Stored seed metrics disagree with normalized direct pairs")
            defined = [r for r in rs if r["cross_field_share"] is not None]
            numerator = sum(r["cross_field_citers"] for r in defined)
            denominator = sum(r["known_field_citers"] for r in defined)
            scopes[flag][inst] = dict(original_seeds=len(originals), canonical_seeds=len(rs), completed=sum(r["query_complete"] for r in originals),
                                      unresolved=sum(not r["canonical_id"] for r in originals), direct_edges=direct,
                                      distinct_direct_citers=distinct, cross_numerator=numerator, cross_denominator=denominator,
                                      cross_field_share=numerator / denominator if denominator else None,
                                      known_field_citers=sum(r["known_field_citers"] for r in rs),
                                      unknown_field_citers=sum(r["unknown_field_citers"] for r in rs),
                                      age_eligible=sum(r["age_window"]["status"] == "eligible" for r in originals),
                                      age_censored=sum(r["age_window"]["status"] == "right_censored" for r in originals))
    return scopes


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            f.write(text)
        tmp.replace(path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def validate_host(repo, host_baseline_html):
    """Verify the newer main host independently of the historical study release."""
    pins = read_json(Path(__file__).with_name('dashboard_host_snapshot.json'))
    if pins['commit'] != 'edf3ae4a13ffaa34da42d2c56abaf3043de49944':
        raise ValueError('Unreviewed main host snapshot')
    checked_file(host_baseline_html, pins['baseline_sha256'])
    hashes = {str(host_baseline_html): pins['baseline_sha256']}
    for relative, expected in pins['protected_sha256'].items():
        path = under(repo, relative)
        # Git blobs are LF; Windows checkouts may use CRLF. CSV values stay exact.
        actual = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if actual != expected:
            raise ValueError('Main host input SHA-256 mismatch: ' + str(path))
        hashes[str(path)] = actual
    return pins, hashes


def generate(repo, study, release_manifest, baseline_html, output, build_utc, standalone_output=None,
             historical_repo=None, host_baseline_html=None):
    repo, study, release_manifest, baseline_html, output = map(lambda p: Path(p).resolve(), (repo, study, release_manifest, baseline_html, output))
    historical_repo = Path(historical_repo).resolve() if historical_repo else repo
    host_baseline_html = Path(host_baseline_html).resolve() if host_baseline_html else None
    stamp = datetime.fromisoformat(build_utc.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Explicit UTC --build-utc required")
    destinations = [output, output.with_suffix(".manifest.json")]
    if standalone_output:
        standalone_output = Path(standalone_output).resolve()
        destinations.append(standalone_output)
    if len(set(destinations)) != len(destinations):
        raise ValueError("Output destinations must be distinct")
    for target in destinations:
        if target.is_relative_to(repo) or target.is_relative_to(study) or target.is_relative_to(historical_repo) or target in (baseline_html, release_manifest, host_baseline_html):
            raise ValueError("Generate to external staging, separate from repository/study/baseline inputs")
        if target.exists():
            raise ValueError("Preserving existing output; choose a new staging path: " + str(target))
    def source_digests():
        return {p.name: sha256(p) for p in Path(__file__).parent.iterdir()
                if p.name in {"dashboard.py", "dashboard_template.html", "dashboard_snapshot.py", "dashboard_host_snapshot.json", "idea_flow_dashboard.py", "idea_flow_template.html", "idea_flow_view.js", "rankings.py", "resilience.py"}}
    source_hashes = source_digests()
    if host_baseline_html and historical_repo == repo:
        raise ValueError('New main host requires a separate verified --historical-repo')
    if historical_repo != repo and not host_baseline_html:
        raise ValueError('--historical-repo requires --host-baseline-html')
    print("[snapshot] verifying pinned baseline, release, database and historical inputs", flush=True)
    manifest, hashes = validate_inputs(historical_repo, study, release_manifest, baseline_html)
    baseline, vendors = baseline_payloads(baseline_html)
    host_pins = None
    if host_baseline_html:
        host_baseline_html = Path(host_baseline_html).resolve()
        host_pins, host_hashes = validate_host(repo, host_baseline_html)
        hashes.update(host_hashes)
        baseline, vendors = baseline_payloads(host_baseline_html, host_pins['baseline_sha256'])
    for name, folder in (("DATA_ALL", "outputs"), ("DATA_NF", "outputs/without_flagged")):
        enrich_resilience(baseline[name], (repo if host_pins else historical_repo) / folder / "faculty_network_metrics.csv")
    db_path = study / "study.sqlite3"
    before = (db_path.stat().st_size, db_path.stat().st_mtime_ns)
    print("[snapshot] preparing read-only explorer payload and six exact citation scopes", flush=True)
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if db.execute("SELECT count(*) FROM frontiers WHERE stage='full' AND status NOT IN ('complete','complete_empty')").fetchone()[0]:
            raise ValueError("Full direct-citer frontiers are incomplete")
        idea = build_payload(db, manifest, study, build_utc)
        if not idea["summary"]["full_quality_gate"]["passed"] or len(idea["seeds"]) != manifest["seed_count"]:
            raise ValueError("Frozen study acceptance/population mismatch")
        attach_seed_flags(idea["seeds"], historical_repo)
        if host_pins:
            attach_seed_flags(idea["seeds"], repo)  # fail if main no longer has the frozen seed population
        idea["scopes"] = scope_summaries(db, idea["seeds"])
    if before != (db_path.stat().st_size, db_path.stat().st_mtime_ns):
        raise ValueError("Frozen study database changed during rendering")
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Study became live during rendering; output not written")
    # Data timestamp describes its original release; the host build time is separate.
    idea["generated_utc"] = "2026-10-19T18:14:33+00:00"
    html = render_dashboard(baseline["DATA_ALL"], baseline["DATA_NF"], baseline["COMPARE"],
                            idea_flow=idea, build_utc=build_utc, vendor_sources=vendors)
    standalone_html = render_standalone(idea) if standalone_output else None
    if source_hashes != source_digests():
        raise ValueError("Rendering source changed during generation; output not written")
    report = dict(build_utc=build_utc, method="Offline frozen-study dashboard-only rendering; historical statistics retained; resilience recomputed independently for both variants",
                  input_sha256=hashes, source_sha256=dict(sorted(source_hashes.items())),
                  vendor_sha256={u: hashlib.sha256(v.encode("utf-8")).hexdigest() for u, v in vendors.items()},
                  database_immutable=True, database_stat_unchanged=True, scopes=idea["scopes"],
                  host_commit=host_pins['commit'] if host_pins else None, historical_repo=str(historical_repo),
                  output_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(), output_bytes=len(html.encode("utf-8")))
    # All validation/rendering finishes before any output is created.
    atomic_write(output, html)
    if standalone_html is not None:
        atomic_write(standalone_output, standalone_html)
    atomic_write(output.with_suffix(".manifest.json"), json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(output=str(output), sha256=report["output_sha256"], bytes=report["output_bytes"])), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "study", "release-manifest", "baseline-html", "output"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--build-utc", required=True)
    p.add_argument("--standalone-output", type=Path, help="Optional NEW external compatibility preview; never the released artifact")
    p.add_argument('--historical-repo', type=Path, help='External frozen historical protected outputs, separately hash-verified')
    p.add_argument('--host-baseline-html', type=Path, help='Pinned newer main dashboard; preserves all newer main payloads')
    a = p.parse_args()
    try:
        generate(a.repo, a.study, a.release_manifest, a.baseline_html, a.output, a.build_utc, a.standalone_output,
                 a.historical_repo, a.host_baseline_html)
    except (ValueError, KeyError, OSError, sqlite3.Error) as e:
        p.exit(2, "[snapshot] " + str(e) + "\n")


if __name__ == "__main__":
    main()
