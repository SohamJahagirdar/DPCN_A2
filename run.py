"""DPCN Research Mapping - Group 18 (IISc + TIFR) pipeline runner.

Usage
  python run.py fetch [--steps corpus,authors,partners,outflow,inflow] [--max-calls N]
  python run.py build            # dataset + networks + stats + dashboard from fetched data
  python run.py all              # fetch then build

OpenAlex API key(s): env var OPENALEX_API_KEY (comma-separated) or openalex_key.txt (one key per line).
"""
import argparse
import time

import config


def do_fetch(steps, max_calls):
    from pipeline import fetch
    from pipeline.openalex import BudgetExhausted, OpenAlex
    oa = OpenAlex(max_calls=max_calls)
    if not oa.key:
        print("WARNING: no OpenAlex API key found (OPENALEX_API_KEY / openalex_key.txt); "
              "using the small shared keyless budget.")
    try:
        if "corpus" in steps:
            fetch.fetch_corpus(oa)
        if "fullauthors" in steps:
            fetch.fetch_full_authorships(oa)
        if "sources" in steps:
            fetch.fetch_sources(oa)
        if "authors" in steps:
            fetch.fetch_authors(oa)
        if "partners" in steps:
            from pipeline.build import top_partner_ids
            fetch.fetch_partner_topics(oa, top_partner_ids(config.N_PARTNERS_FOR_TOPICS, config.MIN_SHARED_FOR_TOPICS))
        if "profiles" in steps:
            fetch.fetch_missing_profiles(oa)
        if "inflow_agg" in steps:
            fetch.fetch_inflow_aggregate(oa)
            fetch.fetch_institution_meta(oa)
        flows = tuple(s for s in ("outflow", "inflow") if s in steps)
        if flows:
            fetch.fetch_flows(oa, flows)
    except BudgetExhausted as e:
        print(f"\nSTOPPED: {e}\nEverything fetched so far is cached; just re-run the same command later.")
        print(oa.status())
        return False
    print("fetch done:", oa.status())
    return True


def do_build():
    from pipeline import build, dashboard, networks, stats, variants
    t = time.time()
    tables = build.build_all()
    print(f"  dataset built: {time.time() - t:.0f}s", flush=True)
    nets = networks.build_networks(tables)
    print(f"  networks built: {time.time() - t:.0f}s", flush=True)
    st = stats.compute_stats(tables, nets)
    print(f"  statistics: {time.time() - t:.0f}s", flush=True)
    # the same analysis without the flagged (> 12 authors) papers, as the instructor asked
    v = variants.without_flagged(tables)
    nets_v = networks.build_networks(v, variants.OUT)
    st_v = stats.compute_stats(v, nets_v, variants.OUT, config.PROCESSED / "stats_without_flagged.json")
    comparison = variants.compare(st, st_v)
    print(f"  without-flagged variant: {time.time() - t:.0f}s", flush=True)
    dashboard.write_dashboard(st, st_v, comparison)
    print(f"build done in {time.time() - t:.0f}s -> {config.OUTPUTS} and {config.DASHBOARD_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build", "all"])
    ap.add_argument("--steps", default="corpus,fullauthors,sources,authors,partners,outflow,inflow,profiles",
                    help="'inflow' = exact in-flow citation edges (~1,400 calls; fills cited_by_indian_inst); "
                         "'inflow_agg' = cheaper aggregate in-flow (~700 calls)")
    ap.add_argument("--max-calls", type=int, default=None)
    a = ap.parse_args()
    if a.cmd in ("fetch", "all"):
        ok = do_fetch(a.steps.split(","), a.max_calls)
        if not ok and a.cmd == "all":
            print("Building with what is available so far ...")
    if a.cmd in ("build", "all"):
        do_build()


if __name__ == "__main__":
    main()
