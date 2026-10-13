# DPCN Research Mapping Project — Group 18
**IISc Bangalore + TIFR Mumbai · publications 2016–2026**
Course: Dynamics & Physics of Complex Networks (DPCN), 2026 · Instructor: Prof. Chittaranjan Hens

---

## 1. Objective

The course maps the research output of 43+ Indian institutions (IITs, IIITs, NITs, central universities, IISc/TIFR/IISERs, CSIR and DAE labs). Each of the 30 groups maps its 2–3 assigned institutions. Group 18 covers **IISc Bangalore** and **TIFR Mumbai**.

The instruction note asks every group for four tasks:

1. **Data collection:** every faculty publication from 2016–2026, exported in a fixed CSV format.
2. **Statistics:** metrics at faculty, department and institution level: publication trend, Q1 fraction, h-index distribution, top journals, most-cited papers and research areas.
3. **Interactive dashboard:** at least the 11 panels listed in the instruction note, including two network visualisations.
4. **Network analysis:**
   - a citation network (papers → papers: in-degree, PageRank, citation flow with other Indian institutes);
   - an authorship network (faculty ↔ faculty: degree, betweenness, Louvain communities, cross-institution links);
   - an "Indian connectivity" map (partner institutes, cross-cluster links, topic similarity).

The analysis stays within our two institutions; links to other Indian institutes appear only in the raw files.

---

## 2. Deliverables and where they are

| Deliverable (instruction note) | File | Status |
|---|---|---|
| Main dataset | `outputs/group18_data.csv` | ✅ |
| Citation network edges | `outputs/citation_network.csv` | ✅ |
| Authorship network edges | `outputs/authorship_network.csv` | ✅ |
| Aggregated Indian connections | `outputs/indian_connections.csv` | ✅ |
| Interactive dashboard (incl. both network visualisations) | **Live: https://sohamjahagirdar.github.io/DPCN_A2/** · or open `dashboard/index.html` offline | ✅ |
| Statistics report (≤10 slides / ≤5 pages) | to be built from the dashboard | ⏸ Week 3 |

Supporting outputs:
- `outputs/faculty_list.csv`: per-faculty department, papers, citations, h-indices, Q1 share and top journal.
- `outputs/faculty_network_metrics.csv`: degree, betweenness, Louvain community and number of partner institutes per faculty.
- `outputs/citation_paper_metrics.csv`: in-degree, out-degree and PageRank of every paper.
- `outputs/stats/*.csv`: ready-made report tables (KPIs, top-5 journals, top-10 cited, departments, PageRank and centrality top-10s, communities).

### Columns of `group18_data.csv`
**Required columns:** `group, institution, author, title, year, type, journal_name, issn, doi, citations, quartile, coauthor_institutes, cites_indian_inst, cited_by_indian_inst`

**Extra columns we added:** `n_coauthors, coauthors_gt_10, is_faculty, department, author_openalex_id, openalex_work_id, sjr_quartile, core_rank, field, subfield, domain, n_authors, mega_collaboration, n_refs_to_indian_inst, n_cites_from_indian_inst, openalex_type`

**`coauthors_gt_10`** (requested by the instructor) is TRUE when the paper has **more than 10 co-authors**, i.e. `n_coauthors = n_authors − 1 > 10` (12 or more authors). The same flag is in `authorship_network.csv` (`paper_coauthors_gt_10`) and `citation_paper_metrics.csv`. `n_authors` is capped at 100 because OpenAlex lists at most 100 authors per paper, so 100 means 100 or more.

---

## 3. What we implemented

### 3.1 Data sources
| Source | Used for |
|---|---|
| **OpenAlex** API | papers, authors and affiliations (including raw affiliation text), references, citations, research topics, author profiles |
| **Official faculty rosters**: IISc Directory & Planner 2025-26 (524 people incl. honorary); TIFR Mumbai department pages (125 people) | who counts as faculty, and their departments |
| **SCImago SJR 1999–2025** (via the `sjrdata` mirror) | journal quartile in the year of publication |
| **CORE 2023** conference ranking | A* / A / B / C rank of conference papers |

### 3.2 Pipeline
The pipeline is written in Python. `python run.py fetch`, then `python run.py build`.

1. **Fetch** (`pipeline/fetch.py`): downloads all 2016–2026 works affiliated with IISc and TIFR. Kept types: journal article, review, letter, book chapter, conference paper. Every API response is cached, so interrupted runs resume for free.
2. **Scope cleaning:** OpenAlex tags many authors at TIFR's *other* centres with the main TIFR ID. These are NCBS (Group 23), NCRA, ICTS, TIFR Hyderabad, TIFR-CAM and HBCSE. We detect them from their affiliation text and drop them, so "TIFR" means the **Mumbai campus**.
3. **Faculty identification** (`pipeline/build.py`):
   - Roster names are matched to OpenAlex author IDs. Matching handles initials and name order, e.g. "Rao M V Srisha" = "M. V. Srisha Rao".
   - Each match is checked against the department named in the paper's affiliation text, so two people with a common name ("Praveen Kumar") are not merged.
   - Former faculty who left or retired before the 2025-26 rosters are added by a rule: at least 8 papers at the institute over at least 4 different years, with at least 30% of them as last or corresponding author.
4. **Departments:** taken from the roster. For former faculty, the most frequent department in their affiliation text is used.
5. **Quality metrics:** SJR best quartile for journals and CORE rank for conferences. For each faculty member we compute h-index on their 2016–2026 papers at the institute, h-index without mega-collaboration papers, and OpenAlex's career h-index.
6. **Citation network** (`pipeline/networks.py`): a directed graph of our 42,622 papers, with edges taken from OpenAlex reference lists. We compute in-degree and PageRank (α = 0.85).
7. **Citation flow with other Indian institutes:**
   - *Out-flow:* papers by other Indian institutes that our papers cite. Collected as exact edges; this fills `cites_indian_inst`.
   - *In-flow:* papers by other Indian institutes that cite ours. Collected in aggregate form (counts per citing institute and per year).
   - Works that include our own institute are excluded from both, which removes self-citation.
8. **Authorship network:**
   - Raw file: every co-author pair on a paper with at most 50 authors, where at least one author is from our institutes and the other is from our institutes or any Indian institute.
   - Analysis graph: faculty-to-faculty, edge weight = joint papers. Degree and betweenness centrality, Louvain communities (seed 42) and modularity.
9. **Indian connectivity map:**
   - Partner institutes are ranked by shared papers.
   - Each is assigned a cluster following the course PPT: IIT, NIT, IIIT, IISc/TIFR/IISER, Premier Science, CSIR, DAE, Central University, plus Other DAE, Govt R&D, Medical, Industry and other universities. Partners outside our own cluster are flagged as cross-cluster.
   - Topic similarity is Jaccard on OpenAlex subfield profiles. We report two versions: binary (presence of a subfield) and weighted by share of output.
10. **Co-author flag:** papers with more than 10 co-authors are flagged (`coauthors_gt_10`), as requested by the instructor. The dashboard's **Flagged papers** tab lists all of them (searchable, filterable, with a CSV download).
11. **Statistics and dashboard** (`pipeline/stats.py`, `pipeline/dashboard.py`): all metrics go into one self-contained HTML file. The data and the chart libraries (Plotly, vis-network) are embedded, so the file works fully offline and can be sent as a single attachment. It has 9 tabs, an IISc / TIFR / Both switch, and light and dark mode.

### 3.3 Headline numbers
*(Data collected from OpenAlex on 13 Oct 2026.)*

| | IISc | TIFR Mumbai | Both |
|---|---|---|---|
| Papers 2016–2026 | 35,819 | 7,648 | 42,622 (825 joint) |
| of which conference papers | 7,173 | 1,034 | 8,187 |
| Citations received | 610,269 | 158,344 | 737,911 |
| Institutional h-index (2016–2026 papers) | 217 | 145 | 237 |
| Q1 share of journal papers (SJR) | 69.0% | 71.2% | 69.5% |
| Faculty with papers (roster-matched + former) | 692 | 146 | 838 |
| Papers with more than 10 co-authors (flag `coauthors_gt_10`) | 1,935 (5.4%) | 2,122 (27.7%) | 3,363 (7.9%) |
| Mega-collaboration papers (> 50 authors) | 763 | 1,335 | 1,423 |
| Papers with a co-author from another Indian institute | 40.3% | 44.2% | 40.9% |
| Indian citing works (in-flow, per-batch distinct) | 104,016 | 17,051 | — |
| Citation impact ratio (in / out, same unit) | 0.94 | 1.19 | — |

**Faculty matching.** 624 of the 649 rostered faculty (96%) are matched to their OpenAlex author IDs. Another 216 former faculty are identified by the publication rule in §3.2.

**Citation network.**
- 42,622 papers and 73,319 citations between our own papers; the largest weakly connected component holds 46% of papers.
- Separately, 127,095 citation edges point to papers by other Indian institutes.
- Excluding mega-collaborations, the highest-PageRank papers are early IISc materials, biology and communications papers.

**Co-authorship network.**
- 838 faculty with 1,622 faculty–faculty links.
- 39 Louvain communities (modularity 0.74), closely aligned with departments.
- The raw edge file has 194,190 co-author pairs, of which 76,857 cross institutions.

**Indian connectivity.**
- IISc co-authors with 1,371 Indian institutes and TIFR with 442.
- IISc's top partners are IIT Madras, TIFR, JNCASR, IIT Kharagpur and IIT Bombay.
- The institutes citing IISc most are IIT Madras, IIT Bombay, IIT Kharagpur and AcSIR (CSIR).
- The institutes citing TIFR most are HBNI, IIT Bombay, IISc and NISER.
- By subfield profile, IISc is most similar to the IITs (weighted Jaccard ≈ 0.6).

---

## 4. How to run

```bash
python -m pip install -r requirements.txt
# put your free OpenAlex API key in openalex_key.txt (https://openalex.org/settings/api)
python run.py fetch      # cached + resumable; a free key allows ~10,000 calls/day
python run.py build      # dataset, networks, stats, dashboard (~3 min)
```
Settings such as institution IDs, years, publication types, the mega-collaboration threshold and the faculty-rule thresholds live in `config.py`.

---

## 5. Known limitations

- **OpenAlex coverage:** affiliations and references are not complete. Some papers have no venue (about 0.4%), and roughly 4% of journal papers have no SJR quartile.
- **Long author lists:** OpenAlex shows at most 100 authors per paper. On some mega-collaboration papers (CMS, ALICE, Belle, …) our authors are not visible. Those papers are kept, with author shown as "[not listed]".
- **Faculty lists are current (2025-26):** former faculty come from the publication rule above, which can include a few long-term postdocs or research scientists. They are marked `faculty_source = heuristic`.
- **In-flow is aggregate:** the per-paper column `cited_by_indian_inst` stays empty until full in-flow edges are fetched (about 23,000 API calls).
- **Name matching:** a few roster faculty with very few papers at the institute (mostly new hires) are not matched; they are listed as "roster (no OpenAlex match)".

---

## 6. Design decisions and assumptions

These are the definitions we chose where the instruction note leaves room for interpretation. Each can be changed in `config.py` or one function, followed by a rebuild.

| Topic | Our choice | Why |
|---|---|---|
| TIFR scope | **Mumbai campus only.** Authors at NCBS, NCRA, ICTS, TIFR Hyderabad, TIFR-CAM and HBCSE are recognised from their affiliation text and excluded, even when OpenAlex gives them the main TIFR ID. | The course assigns "TIFR Mumbai", and NCBS belongs to Group 23. |
| Publication types | Journal article, review, letter, book chapter, conference paper. arXiv-only preprints are excluded. | Counts peer-reviewed output only and avoids double counting with published versions. |
| Faculty | Official 2025-26 rosters, plus former faculty identified by a publication rule (§3.2). | The rosters are current lists, but the study covers 2016–2026. |
| Dataset rows | One row per paper × institution × faculty author. Papers without a matched faculty author get one row (`is_faculty = FALSE`). | Matches the "author" column of the template; every paper is still present. |
| Co-author flag | `coauthors_gt_10` = TRUE if the paper has more than 10 co-authors (12 or more authors). Flagged papers stay in all counts; the dashboard shows them per year and compares their citations. | Instructor's request (13 Oct 2026). Threshold is `COAUTHOR_FLAG_THRESHOLD` in `config.py`. |
| Mega-collaborations (> 50 authors) | Kept in the dataset and publication counts (flag `mega_collaboration`). Excluded from the co-authorship network. h-index reported with and without them. | CMS/ALICE-style author lists would otherwise dominate the networks. |
| h-index | Shown in three versions: 2016–2026 papers at the institute, the same without mega-collaborations, and OpenAlex lifetime h-index. | The template does not specify which one. |
| Quartile | SCImago best quartile of the journal in the publication year; 2026 papers use SJR 2025. For conference papers, the CORE 2023 rank. | Matches the Q1–Q4 / A*–C scheme in the template. |
| `cites_indian_inst` / `cited_by_indian_inst` | TRUE if the paper cites, or is cited by, a paper with an author at another Indian institution. Works that include the row's own institution are not counted (removes self-citation). | Captures cross-institute links only. |
| In-flow | Collected in aggregate (citing papers per institute and per year). The per-paper `cited_by_indian_inst` needs about 23k extra API calls and is optional (`--steps inflow`). | OpenAlex's per-call pricing. |
| `total_citations` (indian_connections) | Total citations of the papers co-authored with the partner. Citations to and from the partner are separate columns. | The template does not define it. |
| Partner clusters | PPT clusters (IIT, NIT, IIIT, IISc/TIFR/IISER, Premier Science, CSIR, DAE, Central University), plus Other DAE, Govt R&D/Autonomous, Medical, Industry and other universities. Anything outside IISc/TIFR/IISER counts as cross-cluster. | Follows the course's grouping. |

---

## 7. Next steps
1. Confirm the design decisions above with the instructor and adjust them if needed.
2. Optionally fetch the exact per-paper in-flow (`python run.py fetch --steps inflow`).
3. Write the statistics report (≤10 slides) from the dashboard panels.
4. Final checklist and submission.

## Project structure
```
config.py                 settings (institutions, years, types, thresholds)
run.py                    entry point: fetch / build
pipeline/
  openalex.py             API client with caching and budget handling
  fetch.py                data collection (corpus, authors, flows, partner topics)
  lookups.py              SJR quartiles and CORE ranks
  build.py                dataset, faculty matching, departments, institution clusters
  networks.py             citation network, authorship network, Indian connections
  stats.py                all statistics -> data/processed/stats.json + outputs/stats/
  dashboard.py + dashboard_template.html   interactive dashboard
data/external/            CORE ranks, faculty rosters (SJR data is downloaded automatically)
data/raw/, data/cache/    fetched OpenAlex records - created by `run.py fetch`, not stored in the repo
outputs/                  deliverables
dashboard/index.html      dashboard
```
