"""Team PDF report: last-build stats or an explicitly hash-verified frozen dashboard.

The frozen path reads embedded payloads without config, pickle, study DB or acquisition.
Matplotlib figures and the team's HTML design are printed with installed Chrome.
"""
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DASHBOARD_URL = "https://sohamjahagirdar.github.io/DPCN_A2/"
REPO_URL = "https://github.com/SohamJahagirdar/DPCN_A2"
GROUP = 18
PDF_NAME = f"{GROUP}_IISc_TIFR.pdf"
C_IISC, C_TIFR, C_3, INK2, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#52514e", "#e1e0d9"
TEAM = (("Soham Jahagirdar", "2023102046"), ("Manas Inamdar", "2023102052"),
        ("Snehil Sanjog", "2023102051"))


def pct(x, d=1):
    return "–" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=0):
    if x is None:
        return "–"
    return f"{x:,.{d}f}"


def esc(s):
    return html.escape(str(s or ""))


# ------------------------------------------------------------------ figures
def _svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):]


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors=INK2, labelsize=7.5)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def figures(st):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
                         "font.size": 8, "svg.fonttype": "none", "axes.formatter.use_mathtext": False})
    out = {}
    # 1. papers per year by institute + research fields
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.3, 2.25), gridspec_kw={"width_ratios": [1.1, 1]})
    for inst, c in (("IISc", C_IISC), ("TIFR", C_TIFR)):
        tr = st["inst"][inst]["trend"]
        a.plot(tr["years"], tr["total"], color=c, linewidth=1.8, marker="o", markersize=3.5, label=inst)
    a.set_title("Papers per year (2026 partial)", fontsize=8.5, loc="left", color="#0b0b0b")
    a.legend(frameon=False, fontsize=7.5)
    _style(a)
    fl = sorted(st["inst"]["All"]["fields"].items(), key=lambda x: -x[1])[:10][::-1]
    tot = st["inst"]["All"]["kpis"]["papers"]
    b.barh([f[0].replace("Biochemistry, Genetics and Molecular Biology", "Biochem., Genetics & Mol. Bio.") for f in fl],
           [f[1] / tot for f in fl], color=C_IISC, height=0.65)
    b.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    b.set_title("Research fields (share of papers, both institutes)", fontsize=8.5, loc="left")
    _style(b)
    b.grid(axis="x", color=GRID, linewidth=0.6)
    b.grid(axis="y", visible=False)
    fig.tight_layout()
    out["fig1"] = _svg(fig)

    # 2. network: growth of the faculty network + citation in-degree with power-law fit
    T = st.get("network_tests", {})
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.3, 2.25))
    g = T.get("growth", [])
    a.plot([d["year"] for d in g], [d["giant_share"] for d in g], color=C_IISC, linewidth=1.8, marker="o", markersize=3.5)
    a.set_ylim(0, 1)
    a.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    a.set_title("Faculty co-authorship network: share in the\nlargest connected group (joint papers up to each year)", fontsize=8.5, loc="left")
    _style(a)
    dd = {int(k): v for k, v in st["citation"]["indegree_dist"].items() if int(k) > 0}
    xs = sorted(dd)
    n = sum(dd.values())
    ccdf = []
    for x in xs:
        ccdf.append(sum(v for k, v in dd.items() if k >= x) / n)
    b.loglog(xs, ccdf, "o", color=C_IISC, markersize=3, label="papers (cited ≥ 1 time internally)")
    pl = (T.get("citation") or {}).get("powerlaw")
    if pl:
        x0 = pl["xmin"]
        frac = sum(v for k, v in dd.items() if k >= x0) / n
        xx = [x for x in xs if x >= x0]
        b.loglog(xx, [frac * (x / x0) ** (1 - pl["alpha"]) for x in xx], color=C_TIFR, linewidth=1.6,
                 label=f"power law, α = {pl['alpha']:.2f} (x ≥ {x0})")
    b.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    b.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{100 * v:g}%"))
    b.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    b.set_ylabel("share of papers with ≥ x", fontsize=7.5, color=INK2)
    b.set_title("Citation network: in-degree (CCDF, log–log)", fontsize=8.5, loc="left")
    b.set_xlabel("citations from our own papers", fontsize=7.5, color=INK2)
    b.legend(frameon=False, fontsize=7)
    _style(b)
    fig.tight_layout()
    out["fig2"] = _svg(fig)

    # 3. impact pathways by sector
    sec = st["impact"]["All"]["sectors"][::-1]
    fig, a = plt.subplots(figsize=(7.3, 2.35))
    y = range(len(sec))
    a.barh([i + 0.2 for i in y], [s["coauthored"] for s in sec], height=0.38, color=C_IISC, label="papers co-authored with the sector")
    a.barh([i - 0.2 for i in y], [s["cited_papers"] for s in sec], height=0.38, color=C_3, label="papers cited by the sector")
    a.set_yticks(list(y), [s["sector"] for s in sec])
    a.legend(frameon=False, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    a.set_title("Who in India uses the research, beyond academia (both institutes)", fontsize=8.5, loc="left")
    _style(a)
    a.grid(axis="x", color=GRID, linewidth=0.6)
    a.grid(axis="y", visible=False)
    fig.tight_layout()
    out["fig3"] = _svg(fig)
    return out


# ------------------------------------------------------------------ report
def integrated_findings(st, sv, idea):
    """Validate counts from frozen payloads; never sum per-seed unique-citer totals."""
    from pipeline.dashboard_snapshot import canonical_rows
    scope = idea["scopes"]["in"]["All"]
    rows = canonical_rows(idea["seeds"])
    known = sum(r["known_field_citers"] for r in rows)
    unknown = sum(r["unknown_field_citers"] for r in rows)
    denominator = sum(r["known_field_citers"] for r in rows if r["cross_field_share"] is not None)
    numerator = sum(r["cross_field_citers"] for r in rows if r["cross_field_share"] is not None)
    if (scope["direct_edges"] != sum(r["observed_citers"] for r in rows)
            or scope["direct_edges"] != known + unknown
            or (scope["cross_numerator"], scope["cross_denominator"]) != (numerator, denominator)
            or scope["unknown_field_citers"] != unknown
            or scope["direct_edges"] != idea["direct_edges"]
            or scope["distinct_direct_citers"] != idea["distinct_direct_citers"]
            or scope["original_seeds"] != len(idea["seeds"])
            or scope["completed"] + scope["unresolved"] != len(idea["seeds"])):
        raise ValueError("Frozen Follow the Idea counts/denominators disagree")
    res = []
    for label, data in (("All papers", st), ("Without >12-author papers", sv)):
        r = data["resilience"]
        b, summary = r["baseline"], r["summary"]
        top = max(r["researchers"], key=lambda p: p["lost_pair_fraction"])
        degree = max(r["researchers"], key=lambda p: p["degree"])
        if (b["nodes"] != len(r["researchers"])
                or b["edges"] != data["authorship"]["summary"]["faculty_edges"]
                or summary["max_lost_pairs"] != top["lost_connected_pairs"]
                or abs(top["lost_pair_fraction"] - top["lost_connected_pairs"] / top["connected_pairs_before_remaining"]) > 1e-12):
            raise ValueError("Frozen resilience graph/removal measures disagree")
        res.append(dict(label=label, baseline=b, top=top, degree=degree))
    return dict(scope=scope, unknown_citer=unknown, unknown_seed_known_citer=known-denominator,
                independent_human_reviews=sum(bool(r.get("independent_human_review")) for r in idea.get("reviewed_cases", [])),
                cross_share=numerator / denominator if denominator else None, resilience=res)


def analysis_html(st, sv, idea):
    if idea is None:
        return ""
    v = integrated_findings(st, sv, idea)
    s = v["scope"]
    rows = "".join(f"<tr><td>{esc(r['label'])}</td><td class=n>{num(r['baseline']['nodes'])}</td>"
                   f"<td class=n>{num(r['baseline']['edges'])}</td><td class=n>{num(r['baseline']['components'])}</td>"
                   f"<td class=n>{num(r['baseline']['largest_component'])}</td>"
                   f"<td class=n>{num(r['top']['lost_connected_pairs'])} ({pct(r['top']['lost_pair_fraction'],2)})</td></tr>"
                   for r in v['resilience'])
    a, b = v['resilience']
    return f"""<h2 class=pb>4. Network resilience and global citation reach</h2>
<h3>4.1 Who keeps the collaboration network connected?</h3>
<p>Each faculty researcher is removed independently from the recorded co-authorship graph. We count pairs of <b>other, surviving researchers</b> that were connected before removal but no longer have a path afterwards. Pairs involving the removed person are excluded from both the loss and its denominator. Joint papers with more than 50 authors are already absent from both graphs.</p>
<table><tr><th>Graph</th><th class=n>Faculty</th><th class=n>Links</th><th class=n>Components</th><th class=n>Largest</th><th class=n>Maximum pair loss</th></tr>{rows}</table>
<p>The highest proportional removal impacts are <b>{esc(a['top']['name'])}</b> with all papers and <b>{esc(b['top']['name'])}</b> without flagged papers. Their losses are divided by {num(a['top']['connected_pairs_before_remaining'])} and {num(b['top']['connected_pairs_before_remaining'])} previously connected surviving pairs, respectively. The filtered graph has fewer alternative paths and its worst measured loss is larger.</p>
<div class=box><b>Many collaborators and structural importance differ.</b> {esc(a['degree']['name'])} has the highest all-papers degree ({num(a['degree']['degree'])} collaborators), but a different researcher has the largest removal effect. A low-degree bridge can separate groups that a high-degree hub does not. This is a hypothetical topology experiment, not a prediction of departures, lost productivity or researcher quality.</div>
<p>Institution selection filters researcher rows, while graph-wide measures remain for the combined IISc-TIFR graph. Excluding >12-author papers changes the graph itself. The native dashboard provides rankings, role definitions, CSV exports and selected-researcher fragments.</p>
<h3>4.2 Follow the Idea: where are the papers cited next?</h3>
<p>The original {num(s['original_seeds'])} IISc/TIFR seed IDs resolve to {num(s['completed'])} queried IDs; {num(s['unresolved'])} remain provider-unresolved. The separate frozen OpenAlex study (cutoff {esc(idea['cutoff'])}; processed 19 Oct 2026) records <b>{num(s['distinct_direct_citers'])} distinct direct citing works (G1)</b> and <b>{num(s['direct_edges'])} seed-citer links</b>. One work can cite several seeds, so links and works are different totals. Combined unique-citer counts come from citation-pair sets, never sums of seed-level unique counts.</p>
<table><tr><th>Recorded direct links, both institutions / all seeds</th><th class=n>Count</th></tr>
<tr><td>Different primary OpenAlex fields / both fields known</td><td class=n>{num(s['cross_numerator'])} / {num(s['cross_denominator'])} ({pct(v['cross_share'],2)})</td></tr>
<tr><td>Excluded: unknown citing field</td><td class=n>{num(v['unknown_citer'])}</td></tr>
<tr><td>Additional excluded: known citing field, unavailable seed field</td><td class=n>{num(v['unknown_seed_known_citer'])}</td></tr></table>
<p>Thus {num(s['direct_edges'])} - {num(v['unknown_citer'])} - {num(v['unknown_seed_known_citer'])} = {num(s['cross_denominator'])} classifiable links. Cross-field links measure a change of <b>primary field between papers</b>, not unique cross-field people, research quality or proven idea adoption.</p>
<p>The institution control selects seeds (joint papers belong to each institution and count once in Both); excluding flagged papers also selects <b>seeds only</b>, without deleting downstream citers by author count. G2 comprises selected, bounded second-hop paths and is not a full-corpus second-generation census. Evidence paths and edge provenance remain inspectable in the dashboard.</p>
<div class=box><b>Coverage and evidence limits.</b> Exhausted provider queries cover available OpenAlex Core records, not all world scholarship. Unknown fields remain excluded from the cross-field denominator. Recent seeds have less observation time: {num(s['age_censored'])} resolved seeds lack the study's full five-year window; {num(s['age_eligible'])} are eligible. Source pages/excerpts may be unavailable; citation evidence does not establish adoption, practical benefit or causality. Independent human source reviews: <b>{v['independent_human_reviews']}</b>. Full definitions and case-specific limitations: <code>docs/FOLLOW_THE_IDEA.md</code> and <code>docs/NETWORK_RESILIENCE.md</code>.</div>
"""


def build_html(st, sv, cmp_rows, idea=None):
    figs = figures(st)
    K = {i: st["inst"][i]["kpis"] for i in ("IISc", "TIFR", "All")}
    R = {i: st["reputable"][i] for i in ("IISc", "TIFR", "All")}
    J = st["journals"]
    I = st["impact"]
    T = st.get("network_tests", {})
    f = T.get("faculty", {})
    pl = (T.get("citation") or {}).get("powerlaw") or {}
    cs = st["citation"]["summary"]
    au = st["authorship"]["summary"]
    fl = st["flows"]
    con = st["connectivity"]

    def cmp(inst, metric):
        for r in cmp_rows:
            if r["institution"] == inst and r["metric"] == metric:
                return r
        return {}

    cit_drop = {i: cmp(i, "Citations").get("change") for i in ("IISc", "TIFR", "All")}
    hi = sorted([r for r in J["regression"] if r["outcome"] == "High-impact journal" and r["p"] < 0.05],
                key=lambda r: -r["odds_ratio"])
    reg = {(r["outcome"], r["factor"], r["level"]): r for r in J["regression"]}
    tifr_or = reg.get(("High-impact journal", "Institution", "TIFR"), {}).get("odds_ratio")
    ind_or = reg.get(("High-impact journal", "Collaboration", "With other Indian institutes"), {}).get("odds_ratio")
    asst_or = reg.get(("High-impact journal", "Faculty rank", "Assistant professor / Reader"), {}).get("odds_ratio")
    # The frozen dashboard already lists every flagged paper once; no pickle read.
    joint_big = sum({"IISc", "TIFR"}.issubset(r["homes"].split(";")) for r in st["flagged"])
    ni = R["All"]["comparison"][0]
    nif = R["All"]["comparison"][1]
    oth = R["All"]["comparison"][-1]
    partners = sorted([p | {"inst": i} for i in ("IISc", "TIFR") for p in con[i]["top_partners"]], key=lambda p: -p["shared_papers"])
    ratio = (fl["IISc"]["inflow"] + fl["TIFR"]["inflow"]) / (fl["IISc"]["outflow"] + fl["TIFR"]["outflow"])
    cases = [c for c in I["cases"] if c["evidence"] == "Documented outcome"]
    rich = (f.get("rich_club") or [{}])[-1]
    IK = I["All"]["kpis"]

    head_rows = [
        ("Papers 2016–2026", *[num(K[i]["papers"]) for i in ("IISc", "TIFR", "All")]),
        ("Citations", *[num(K[i]["citations"]) for i in ("IISc", "TIFR", "All")]),
        ("Institutional h-index (2016–2026 papers)", *[num(K[i]["h_index"]) for i in ("IISc", "TIFR", "All")]),
        ("Journal papers in Q1 journals (SCImago)", *[pct(K[i]["q1_share_journals"]) for i in ("IISc", "TIFR", "All")]),
        ("Faculty with papers", *[num(K[i]["faculty"]) for i in ("IISc", "TIFR", "All")]),
        ("Papers with another Indian institute", *[pct(K[i]["with_indian_coauthor"]) for i in ("IISc", "TIFR", "All")]),
        ("Papers with > 12 authors (instructor's flag)", *[f"{num(K[i]['many_author_papers'])} ({pct(K[i]['many_author_share'])})" for i in ("IISc", "TIFR", "All")]),
        ("Citations lost without the flagged papers", *[pct(-cit_drop[i]) if cit_drop[i] is not None else "–" for i in ("IISc", "TIFR", "All")]),
        ("Papers in Nature Index journals", *[num(R[i]["kpis"]["ni_papers"]) for i in ("IISc", "TIFR", "All")]),
        ("Papers used outside academia in India", *[pct(I[i]["kpis"]["nonacademic_share"]) for i in ("IISc", "TIFR", "All")]),
        ("Papers cited by patents (published up to 2023)", *[pct(I[i]["kpis"]["patent_cited_share"]) for i in ("IISc", "TIFR", "All")]),
    ]
    head_tbl = "".join(f"<tr><td>{esc(r[0])}</td><td class=n>{r[1]}</td><td class=n>{r[2]}</td><td class=n>{r[3]}</td></tr>" for r in head_rows)

    test_rows = [
        ("Clustering coefficient", f"{f.get('clustering', 0):.3f}", f"{f.get('clustering_null', 0):.3f}", f"{f.get('clustering', 0) / max(f.get('clustering_null', 1e-9), 1e-9):.0f}× random"),
        ("Mean shortest path (largest group)", f"{f.get('path', 0):.2f}", f"{f.get('path_null', 0):.2f}", f"small world, σ = {f.get('sigma', 0):.1f}"),
        ("Louvain modularity (unweighted)", f"{f.get('modularity', 0):.3f}", f"{f.get('modularity_null', 0):.3f} ± {f.get('modularity_null_sd', 0):.3f}", f"z = {f.get('modularity_z', 0):.0f}"),
        ("Links within a department", pct(f.get("within_dept_share")), pct(f.get("within_dept_expected")), f"{f.get('within_dept_share', 0) / max(f.get('within_dept_expected', 1e-9), 1e-9):.0f}× expected"),
        ("Degree assortativity", f"{f.get('degree_assortativity', 0):+.2f}", f"{f.get('degree_assortativity_null', 0):+.2f}", "hubs link to hubs"),
        (f"Rich club (faculty with > {rich.get('k', '–')} co-authors)", f"{rich.get('observed', 0):.3f}", f"{rich.get('null', 0):.3f}", f"{rich.get('ratio') or 0:.2f}× random"),
    ]
    test_tbl = "".join(f"<tr><td>{a}</td><td class=n>{b}</td><td class=n>{c}</td><td>{d}</td></tr>" for a, b, c, d in test_rows)

    case_tbl = "".join(
        f"<li><b>{esc(c['title'])}</b> <span class=muted>({esc(c['institute'])}{', ' + num(c['papers']) + ' papers' if c['papers'] else ''})</span></li>"
        for c in cases)

    rep_tbl = "".join(
        f"<tr><td>{lab}</td><td class=n>{fmt(ni[k])}</td><td class=n>{fmt(nif[k])}</td><td class=n>{fmt(oth[k])}</td></tr>"
        for lab, k, fmt in [("Papers", "papers", num), ("In global top 10% of field", "top10_share", pct),
                            ("Cited at least once in India", "cited_in_india_share", pct),
                            ("Indian citations per paper", "indian_citations_mean", lambda v: num(v, 1)),
                            ("Indian share of all citations", "indian_share", pct),
                            ("Cited by a patent (to 2023)", "patent_share", pct),
                            ("Used outside academia in India", "nonacademic_share", pct)])

    top_team = hi[0] if hi else {}
    team_line = "<div class=team>" + " · ".join(f"{esc(name)} - {roll}" for name, roll in TEAM) + "</div>"
    extra = analysis_html(st, sv, idea)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Group {GROUP} - IISc & TIFR research map</title>
<style>
@page {{ size: A4; margin: 13mm 14mm 13mm 14mm; }}
body {{ font-family: "Segoe UI", system-ui, sans-serif; font-size: 9.3pt; line-height: 1.38; color: #0b0b0b; }}
h1 {{ font-size: 15.5pt; margin: 0 0 2px; }}
h2 {{ font-size: 11pt; margin: 11px 0 3px; border-bottom: 1px solid #e1e0d9; padding-bottom: 2px; break-after: avoid; }}
h3 {{ font-size: 9.6pt; margin: 7px 0 2px; }}
p {{ margin: 3px 0 5px; }}
ul {{ margin: 2px 0 5px 16px; padding: 0; }} li {{ margin: 1.5px 0; }}
.sub {{ color: #52514e; font-size: 9pt; }} .team {{ font-size: 9pt; margin-top: 2px; }}
.links {{ margin: 6px 0 4px; padding: 6px 8px; background: #f3f2ee; border-radius: 6px; font-size: 8.8pt; }}
a {{ color: #2a78d6; text-decoration: none; }}
table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 3px 0 6px; }}
th, td {{ padding: 2.5px 6px; border-bottom: 1px solid #e1e0d9; text-align: left; vertical-align: top; }}
th {{ background: #f3f2ee; font-weight: 600; }} td.n, th.n {{ text-align: right; white-space: nowrap; }}
.muted {{ color: #898781; }} .fig {{ margin: 4px 0 2px; }} .fig svg {{ width: 100%; height: auto; }}
.cap {{ font-size: 8pt; color: #52514e; margin: 0 0 6px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.box {{ border-left: 3px solid #2a78d6; padding: 2px 0 2px 8px; margin: 4px 0; }}
.refs li {{ font-size: 7.8pt; margin: 1px 0; }}
.pb {{ break-before: page; }}
.keep {{ break-inside: avoid; }} tr {{ break-inside: avoid; }}
.cases {{ columns: 2; column-gap: 18px; font-size: 8.5pt; }} .cases li {{ break-inside: avoid; }}
</style></head><body>
<h1>Research map of IISc Bangalore and TIFR Mumbai, 2016–2026</h1>
<div class=sub>DPCN Research Mapping Project · Group {GROUP} · Integrated report · OpenAlex data collected {esc(st['meta']['data_collected'])}</div>
{team_line}
<div class=links><b>Integrated dashboard:</b> <code>dashboard/index.html</code> ({13 if idea else 11} tabs; IISc / TIFR / both; flagged papers included or excluded). Public baseline: <a href="{DASHBOARD_URL}">{DASHBOARD_URL}</a>; this integration is not published.<br>
<b>Code, data files and methods:</b> <a href="{REPO_URL}">{REPO_URL}</a> · deliverables in <code>outputs/</code>: group{GROUP}_data.csv, citation_network.csv, authorship_network.csv, indian_connections.csv</div>

<h2>1. Data and scope</h2>
<p>All journal articles, reviews, letters, book chapters and conference papers from 2016–2026 with an author at IISc Bangalore or TIFR Mumbai, from OpenAlex: {num(st['meta']['n_papers'])} papers ({num(K['All']['shared_with_other'])} joint), {num(st['meta']['n_rows'])} dataset rows. TIFR means Mumbai only (NCBS, NCRA, ICTS, TIFR Hyderabad, TIFR-CAM and HBCSE authors are excluded by affiliation text). Faculty come from the official rosters matched to OpenAlex authors; author lists cut at 100 by the API were fetched in full. Journal quality uses SCImago quartiles in the publication year; impact uses OpenAlex 2-year mean citedness. Full methods: dashboard <i>Method</i> tab and the repository README.</p>
<table><tr><th></th><th class=n>IISc</th><th class=n>TIFR</th><th class=n>Both</th></tr>{head_tbl}</table>

<h2>2. Key statistics</h2>
<div class=fig>{figs['fig1']}</div>
<p class=cap>Figure 1. Output per year and research fields. IISc publishes about five times as many papers as TIFR and is engineering-led; TIFR is concentrated in physics and astronomy.</p>
<ul>
<li><b>Two research models.</b> {pct(K['TIFR']['many_author_share'])} of TIFR papers have more than 12 authors (large physics and astronomy collaborations), against {pct(K['IISc']['many_author_share'])} at IISc. Without these flagged papers TIFR loses {pct(-cit_drop['TIFR']) if cit_drop['TIFR'] is not None else '–'} of its citations and IISc {pct(-cit_drop['IISc']) if cit_drop['IISc'] is not None else '–'}; the dashboard repeats every analysis without them, as the instructor asked.</li>
<li><b>Journal choice.</b> {pct(J['All']['kpis']['q1_share'])} of journal papers are in Q1 journals, but only {pct(J['All']['kpis']['high_impact_share'])} in high-impact journals (impact ≥ 10). In a logistic regression on faculty–paper pairs, team size is the strongest driver: papers with {esc(top_team.get('level', ''))} authors have {num(top_team.get('odds_ratio'), 1)}× the odds of a high-impact journal, other factors held fixed. Assistant professors have {num(asst_or, 2)}× the odds of professors; papers with other Indian institutes {num(ind_or, 2)}×; TIFR {num(tifr_or, 2)}× (its main physics journals have impact below 10, a field effect).</li>
<li><b>Reputable journals.</b> {num(R['All']['kpis']['ni_papers'])} papers ({pct(R['All']['kpis']['ni_share'])} of journal papers) are in the 178 Nature Index journals; they are {pct(ni['top10_share'])} in the global top 10% of their field, against {pct(oth['top10_share'])} for our other papers.</li>
</ul>

<h2 class=pb>3. Network analysis</h2>
<h3>3.1 Citation network (papers citing papers)</h3>
<p>{num(cs['nodes'])} papers and {num(cs['edges'])} citations among them; {pct(cs['largest_wcc_share'])} of papers sit in the largest weakly connected component, and {pct(1 - T.get('citation', {}).get('share_cited_internally', 0))} are never cited by another of our papers. The in-degree distribution is heavy-tailed: a discrete power law fitted by maximum likelihood (Clauset et al. 2009) gives α = {num(pl.get('alpha'), 2)} ± {num(pl.get('alpha_se'), 2)} for papers with ≥ {pl.get('xmin', '–')} internal citations ({num(pl.get('n_tail'))} papers) — a few papers become the internal reference points. PageRank (Brin & Page 1998) ranks them on the dashboard. With the rest of Indian science the flow is balanced: other Indian institutes cite our papers {num(fl['IISc']['inflow'] + fl['TIFR']['inflow'])} times and we cite theirs {num(fl['IISc']['outflow'] + fl['TIFR']['outflow'])} times (ratio {ratio:.2f}).</p>
<div class=fig>{figs['fig2']}</div>
<p class=cap>Figure 2. Left: growth of the faculty co-authorship network. Right: complementary cumulative distribution of internal citations with the fitted power-law tail.</p>
<h3>3.2 Faculty co-authorship network: more than chance?</h3>
<p>{num(au['faculty_nodes'])} faculty, {num(au['faculty_edges'])} links (joint papers with ≤ 50 authors), the kind of collaboration network first studied by Newman (2001). To go beyond description we compare the network with 20 degree-preserving random rewirings (Maslov & Sneppen 2002), in which every faculty member keeps their number of co-authors but not their partners.</p>
<table><tr><th>Measure ({num(f.get('nodes'))} faculty with a faculty co-author)</th><th class=n>Observed</th><th class=n>Random</th><th>Reading</th></tr>{test_tbl}</table>
<ul>
<li><b>A small world organised by departments.</b> Clustering is {f.get('clustering', 0) / max(f.get('clustering_null', 1e-9), 1e-9):.0f}× random while distances stay short (σ = {f.get('sigma', 0):.1f}; Watts & Strogatz 1998; Humphries & Gurney 2008). Louvain finds {au['n_communities']} communities (weighted modularity {au['modularity']:.2f}; Blondel et al. 2008), far stronger than in random networks, and {pct(f.get('within_dept_share'))} of links stay inside a department (expected {pct(f.get('within_dept_expected'))}).</li>
<li><b>The two institutes barely connect.</b> Only {num(f.get('cross_institute_links'))} of {num(f.get('edges'))} faculty links join IISc and TIFR (institute assortativity {f.get('inst_assortativity', 0):.2f}), although {num(K['All']['shared_with_other'])} papers are joint: {num(joint_big)} of these have more than 12 authors, so the institutes meet mainly inside large collaborations.</li>
<li><b>Hubs work with hubs.</b> Positive degree assortativity (Newman 2003) and a rich club (Colizza et al. 2006): the best-connected faculty collaborate with each other more than chance, and a few bridging faculty (highest betweenness, on the dashboard) hold departments together. The largest connected group grew from {pct((T.get('growth') or [{}])[0].get('giant_share'), 0)} of linked faculty in 2016 to {pct((T.get('growth') or [{}])[-1].get('giant_share'), 0)} by 2026.</li>
</ul>
<h3>3.3 Connectivity with Indian institutions</h3>
<p>IISc co-authors with {num(con['IISc']['n_partners'])} Indian institutions and TIFR with {num(con['TIFR']['n_partners'])}; the largest partnership is {esc(partners[0]['inst'])}–{esc(partners[0]['partner_inst'])} ({num(partners[0]['shared_papers'])} shared papers). {pct(K['All']['with_indian_coauthor'])} of papers have another Indian institute (TIFR {pct(K['TIFR']['with_indian_coauthor'])}, IISc {pct(K['IISc']['with_indian_coauthor'])}). Partners are grouped by the course clusters, with topic similarity (Jaccard over research subfields) for the main partners. A journal co-usage network (journals linked by shared faculty, Louvain) shows the publication ecosystems.</p>

{extra}
<h2 class=pb>{5 if idea else 4}. Impact on India: importance and relevance</h2>
<div class=keep><p><b>Reputable papers reach Indian research most, but India is a small part of their audience.</b> Measured with Indian citations (self-citation excluded):</p>
<table><tr><th></th><th class=n>Nature Index</th><th class=n>…India-focused</th><th class=n>Other papers</th></tr>{rep_tbl}</table></div>
<p><b>Beyond research.</b> We traced documented pathways from papers to users outside academia (Bornmann 2013): {pct(IK['nonacademic_share'])} of papers are co-authored or cited by Indian companies, government agencies, hospitals or NGOs; {num(IK['patent_cited'])} papers are cited by {num(IK['patents'])} patents (Reliance on Science; Marx & Fuegi 2020; patent citations are the standard link between science and technology, Ahmadpoor & Jones 2017); {num(IK['industry_papers'])} papers have co-authors at {num(IK['companies'])} companies in India, including {num(IK['iisc_startups'])} start-ups based at IISc. Atomic energy, health, CSIR laboratories and the weather and climate agencies are the heaviest users.</p>
<div class=fig>{figs['fig3']}</div>
<p class=cap>Figure 3. Papers co-authored with, and papers cited by, Indian organisations in each sector (citing papers involving our own institute excluded).</p>
<p><b>Documented outcomes.</b> {len(I['cases'])} case studies with public sources and matching papers where available; the {len(cases)} with a documented outcome are below (all {len(I['cases'])}, with sources, on the dashboard's <i>Impact on India</i> tab). Some outcomes have no matching paper in our corpus; case inclusion is not causal attribution:</p>
<ul class=cases>{case_tbl}</ul>

<h2 class=pb>{6 if idea else 5}. Key observations and insights</h2>
<ul>
<li><b>Separate large collaborations.</b> TIFR's {pct(K['TIFR']['many_author_share'])} flagged papers carry {pct(-cit_drop['TIFR']) if cit_drop['TIFR'] is not None else '–'} of its citations. Author count does not establish individual contribution or invalidate the work.</li>
<li><b>Separate venue indicators from quality.</b> Q1 is common; high-impact-journal publication is associated with team size. These are observational associations, not causal team effects.</li>
<li><b>Collaboration is departmental.</b> Short network paths coexist with strong departmental structure and relatively few direct IISc-TIFR faculty links.</li>
<li><b>Two routes to national reach.</b> Reputable work reaches Indian research; India-focused papers also reach mission agencies and state universities. Documented licences, start-ups and mission roles illustrate practical pathways.</li>
</ul>

<h2>{7 if idea else 6}. Modelling approaches: used and proposed</h2>
<p><b>Used.</b> PageRank on the citation network; Louvain communities; degree and betweenness centrality; degree-preserving null models for small-world, modularity, assortativity and rich-club tests; maximum-likelihood power-law fit; logistic regression with paper-clustered errors for journal choice; with/without-flagged sensitivity analysis. {"Also implemented: independent single-node removal tests; full-seed direct-citation reach, primary-field transitions and bounded G2 evidence paths." if idea else ""}</p>
<p><b>Interpretation limits.</b> 2026 is partial; journal impact is not field-normalised. The power-law fit is a descriptive tail fit, without a bootstrap goodness-of-fit or alternative-distribution test; it does not establish a unique generating mechanism. Twenty null rewirings are a finite comparison. Patent coverage ends in 2023, excludes the Indian Patent Office and lacks assignees. Registry/address matching undercounts companies. Citation/co-authorship and selected documented cases are pathways, not causal estimates of national benefit, revenue, jobs or policy impact.</p>
<p><b>Proposed for the second round (state of the art in the science of science; Fortunato et al. 2018).</b></p>
<p><b>Disruption indices</b> would compare team sizes (Funk & Owen-Smith 2017; Wu et al. 2019); <b>block models/Leiden</b> would test communities (Peixoto 2014; Traag et al. 2019); <b>temporal/multilayer networks</b> would connect collaboration and citation histories (Holme & Saramäki 2012; Kivelä et al. 2014). <b>Link prediction/node2vec</b> would explore future partnerships (Liben-Nowell & Kleinberg 2007; Grover & Leskovec 2016), and <b>citation dynamics</b> future reach (Wang et al. 2013). These remain proposals.</p>

<h2>References</h2>
<ol class=refs>
<li>Ahmadpoor, M. &amp; Jones, B. F. (2017). The dual frontier: patented inventions and prior scientific advance. Science 357, 583–587.</li>
<li>Blondel, V. D. et al. (2008). Fast unfolding of communities in large networks. J. Stat. Mech. P10008.</li>
<li>Bornmann, L. (2013). What is societal impact of research and how can it be assessed? JASIST 64, 217–233.</li>
<li>Brin, S. &amp; Page, L. (1998). The anatomy of a large-scale hypertextual Web search engine. Computer Networks and ISDN Systems 30, 107–117.</li>
<li>Clauset, A., Shalizi, C. R. &amp; Newman, M. E. J. (2009). Power-law distributions in empirical data. SIAM Review 51, 661–703.</li>
<li>Colizza, V. et al. (2006). Detecting rich-club ordering in complex networks. Nature Physics 2, 110–115.</li>
<li>Fortunato, S. et al. (2018). Science of science. Science 359, eaao0185.</li>
<li>Funk, R. J. &amp; Owen-Smith, J. (2017). A dynamic network measure of technological change. Management Science 63, 791–817.</li>
<li>Grover, A. &amp; Leskovec, J. (2016). node2vec: scalable feature learning for networks. KDD 2016.</li>
<li>Holme, P. &amp; Saramäki, J. (2012). Temporal networks. Physics Reports 519, 97–125.</li>
<li>Humphries, M. D. &amp; Gurney, K. (2008). Network 'small-world-ness'. PLoS ONE 3, e0002051.</li>
<li>Kivelä, M. et al. (2014). Multilayer networks. Journal of Complex Networks 2, 203–271.</li>
<li>Liben-Nowell, D. &amp; Kleinberg, J. (2007). The link-prediction problem for social networks. JASIST 58, 1019–1031.</li>
<li>Marx, M. &amp; Fuegi, A. (2020). Reliance on science: worldwide front-page patent citations to scientific articles. Strategic Management Journal 41, 1572–1594.</li>
<li>Maslov, S. &amp; Sneppen, K. (2002). Specificity and stability in topology of protein networks. Science 296, 910–913.</li>
<li>Newman, M. E. J. (2001). The structure of scientific collaboration networks. PNAS 98, 404–409.</li>
<li>Newman, M. E. J. (2003). Mixing patterns in networks. Physical Review E 67, 026126.</li>
<li>Peixoto, T. P. (2014). Hierarchical block structures and high-resolution model selection in large networks. Physical Review X 4, 011047.</li>
<li>Traag, V. A., Waltman, L. &amp; van Eck, N. J. (2019). From Louvain to Leiden: guaranteeing well-connected communities. Scientific Reports 9, 5233.</li>
<li>Wang, D., Song, C. &amp; Barabási, A.-L. (2013). Quantifying long-term scientific impact. Science 342, 127–132.</li>
<li>Watts, D. J. &amp; Strogatz, S. H. (1998). Collective dynamics of 'small-world' networks. Nature 393, 440–442.</li>
<li>Wu, L., Wang, D. &amp; Evans, J. A. (2019). Large teams develop and small teams disrupt science and technology. Nature 566, 378–382.</li>
<li>Data: OpenAlex (openalex.org); SCImago Journal Rank; CORE 2023; Nature Index journal list; Reliance on Science v64 (Zenodo 11461587). Case-study sources are listed on the dashboard.</li>
<li>Frozen Follow the Idea study: cutoff 15 Oct 2026, release 19 Oct 2026; reproducible methods and edge provenance in docs/FOLLOW_THE_IDEA.md. Primary fields: OpenAlex Work object (https://docs.openalex.org/api-entities/works). Network-removal definitions and denominators: docs/NETWORK_RESILIENCE.md. Dashboard/report input hashes: generated provenance manifests; report command: docs/INTEGRATION_REPORT.md.</li>
</ol>
</body></html>"""


def _chrome():
    cands = [os.environ.get("CHROME"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
             r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for c in cands:
        if c and Path(c).exists():
            return c
    raise FileNotFoundError("Chrome not found; set CHROME to its path")


def load_dashboard(path, expected_sha256):
    """Fail on missing/mismatched/partial inputs before creating report outputs."""
    if not expected_sha256 or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Frozen report requires explicit lowercase --dashboard-sha256")
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Frozen dashboard SHA-256 mismatch")
    text = data.decode("utf-8")
    payloads = {}
    for key in ("DATA_ALL", "DATA_NF", "COMPARE", "IDEA_DATA"):
        matches = re.findall(r"^const " + key + r" = (.*);[^\n]*$", text, re.M)
        if len(matches) != 1:
            raise ValueError("Frozen dashboard requires exactly one " + key)
        payloads[key] = json.loads(matches[0])
    for key in ("DATA_ALL", "DATA_NF"):
        st = payloads[key]
        if st["meta"]["group"] != GROUP or st["meta"]["years"] != [2016, 2026] or set(st["meta"]["institutions"]) != {"IISc", "TIFR"}:
            raise ValueError("Frozen dashboard scope differs from Group 18")
        if not st.get("network_tests", {}).get("faculty"):
            raise ValueError("Latest main network tests missing from frozen dashboard")
    integrated_findings(payloads["DATA_ALL"], payloads["DATA_NF"], payloads["IDEA_DATA"])
    return payloads


def write_report(dashboard_html=None, dashboard_sha256=None, output_dir=None):
    idea = None
    default_dest = Path(__file__).resolve().parents[1] / "report"
    if dashboard_html:
        p = load_dashboard(dashboard_html, dashboard_sha256)
        st, sv, cmp_rows, idea = (p[k] for k in ("DATA_ALL", "DATA_NF", "COMPARE", "IDEA_DATA"))
    else:
        if dashboard_sha256:
            raise ValueError("--dashboard-sha256 requires --dashboard-html")
        import config
        default_dest = config.REPORT  # preserve DPCN_SAMPLE report_sample routing
        st = json.loads((config.PROCESSED / "stats.json").read_text(encoding="utf-8"))
        sv = json.loads((config.PROCESSED / "stats_without_flagged.json").read_text(encoding="utf-8"))
        from pipeline import variants
        cmp_rows = variants.compare(st, sv)
    # Prepare all content before creating/replacing output. No live data reads here.
    content = build_html(st, sv, cmp_rows, idea)
    chrome = _chrome()
    dest = Path(output_dir) if output_dir else default_dest
    dest.mkdir(parents=True, exist_ok=True)
    pdf, src = dest / PDF_NAME, dest / Path(PDF_NAME).with_suffix(".html")
    with tempfile.TemporaryDirectory(prefix="report-", dir=dest) as temp:
        tmp = Path(temp)
        html_path, pdf_path = tmp / src.name, tmp / PDF_NAME
        html_path.write_text(content, encoding="utf-8", newline="\n")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf-no-header",
                        "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
                        "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={tmp / 'chrome-profile'}",
                        f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()],
                       check=True, capture_output=True, timeout=180)
        from pypdf import PdfReader
        pages = len(PdfReader(pdf_path).pages)
        if not 1 <= pages <= 5:
            raise ValueError(f"Report has {pages} pages; maximum is 5. Existing output preserved.")
        # Commit the two completed files only after successful print/page-count validation.
        # Chrome inherits the private temporary profile directory's Windows ACL.
        # Publish fresh sibling files so the report inherits its output folder's
        # normal sharing permissions rather than the temporary directory's ACL.
        for source, target in ((pdf_path, pdf), (html_path, src)):
            with tempfile.NamedTemporaryFile(mode="wb", dir=dest, prefix=target.name+".", suffix=".tmp", delete=False) as stage:
                stage.write(source.read_bytes())
            try:
                os.replace(stage.name, target)
            finally:
                Path(stage.name).unlink(missing_ok=True)
    provenance = dict(dashboard_sha256=dashboard_sha256, dashboard_path=str(dashboard_html) if dashboard_html else None,
                      source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), pages=pages,
                      input_mode="frozen dashboard" if idea else "last build stats",
                      findings=integrated_findings(st, sv, idea) if idea else None)
    pdf.with_suffix(".manifest.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"[report] {pdf}")
    return pdf
