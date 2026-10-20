# Integrated dashboard and team report

This is a local review integration on `manas/integrate-network-analyses-report`.
It starts at `fa79f72d0d3cbab4baae4b08a4cffbc152f88f30` (main's Report PDF)
and merges `c1b654a9aed99b7f9692ff6b6dccaaea3d516da0` (the pushed development
branch). Both histories are retained. No push, public deployment, submission or
instructor approval is implied.

## Main changes retained

The three new main commits are `0696ef7` (Report), `bfc154c` (Minor Fix) and
`fa79f72` (Report PDF). The integration keeps `pipeline/netstats.py`, the in-memory
graphs in `networks.py`, both-variant `network_tests` preparation, the co-authorship
null-model table/growth plot, citation-tail hint and Method references. All main
Impact on India, reputable-journal, journal-choice and story-first navigation
renderers remain intact. Main's deliberate `.gitignore` convention keeps private
handover/agent notes out of public Git and tracks only the final report PDF.

The template conflict retains both the new main network panels and the existing
degree tie explanation. The stats conflict retains network tests and the
precision-preserving resilience payload. Two small responsive fixes bound the
Overview finding-card minimum and row selects/inputs to their available width;
the previous fixed widths overflowed a 390px viewport. No study metric or chart
series was changed for those layout fixes.

## Dashboard and input provenance

All thirteen tabs remain native to the Research Map, in its horizontal-tab,
light/dark/system design. There is one Plotly and one vis-network copy, no iframe,
and no sidebar transplant. Frozen dashboard commands, required historical/study
inputs, host pin and six-scope semantics are in [UNIFIED_DASHBOARD.md](UNIFIED_DASHBOARD.md).
The host is main `fa79f72`; the older research study retains its original release
and historical inputs. This is a dashboard-only generation, not a raw-data rebuild.

Resilience's institution control filters researcher rows; graph-wide scores
describe the combined graph. Excluding >12-author papers changes that graph.
Follow the Idea's controls select original seeds; downstream citing works remain
worldwide and are not removed by their author counts. Joint seeds belong to each
institution and count once in Both. Distinct-citer totals come from pair sets,
never per-seed sums. Unknown fields, recent/censored windows, bounded G2 excerpts
and zero independent human source reviews remain explicit.

## Editable report source and command

The actual source is `pipeline/report.py`, exposed through `python run.py report`;
the final tracked artifact is `report/18_IISc_TIFR.pdf`. The existing HTML/matplotlib
design, publication/field charts, journal findings, network tests, India-impact
comparisons, sector chart, documented case studies and references are retained.
The new dedicated page adds single-removal and direct-citation findings and their
limitations. Future-work proposals remain labelled as proposals.

The cover uses exactly:

- Soham Jahagirdar - 2023102046
- Manas Inamdar - 2023102052
- Snehil Sanjog - 2023102051

No submission date, additional institution, approval or unverified course detail
was added. The report keeps the verified Group 18 project title and collection
period. It has five A4 pages; body text is 9.3pt, table text 8.5pt and references
7.8pt, matching the team's established report design.

Install the declared requirements, including the previously undeclared report
dependencies `matplotlib` and `pypdf`; installed Chrome must be available (`CHROME`
can select its executable). No research acquisition or credentials are needed.

```powershell
# First build and verify the staged dashboard as documented separately.
$stagedDashboard = '<verified external staging>\a\index.html'
$expectedDigest = '<expected SHA-256 recorded by the verified dashboard build>'
python -B run.py report `
  --dashboard-html $stagedDashboard `
  --dashboard-sha256 $expectedDigest `
  --report-output '<new external report staging>'
```

`--dashboard-sha256` is mandatory with frozen input; do not substitute an
unreviewed file's calculated hash. The loader checks the exact bytes, required
payloads, Group 18 scope, latest main network tests and count/denominator
consistency before writing. It reads neither a study database nor `papers.pkl`,
and imports no project config. The runner imports config only for fetch/build or
the legacy no-argument report mode. The legacy `python run.py report` still reads
the last build's processed stats; use the explicit frozen mode for this integrated
release so Follow the Idea is included.

The report prints in an isolated Chrome profile, with background networking and
external host resolution disabled. It enforces 1-5 pages before replacing the
PDF/HTML. Intermediate HTML and the adjacent `.manifest.json` remain ignored;
the manifest records dashboard/source/PDF hashes, page count and derived findings.
After rendering and inspecting all pages, copy the exact accepted PDF to the
tracked report path. Do not commit profiles, rendering PNGs, local dependency
folders or manifests.

## Verified findings

Both graph variants reproduce 879/1,814 and 877/1,642 faculty/links, with 185/198
components and largest components of 679/660. Sitharam T G loses 6,713 pairs out
of 229,522 previously connected surviving pairs (2.92%) in the all-paper graph;
Raghavan Varadarajan loses 21,840/216,835 (10.07%) in the filtered graph. Ambarish
Ghosh has the highest all-paper degree, 40. These are independent hypothetical
removals, not predicted departures or measures of quality.

The direct study has 42,725 original seed IDs, 42,719 resolved and six unresolved,
555,786 distinct citing works and 807,678 direct links. An independent read-only
SQL aggregation confirms 184,420 cross-field links / 806,331 classifiable links
= 22.87%: subtract 1,339 unknown-citer-field links and eight additional
known-citer/unknown-seed-field links. These are primary-field link counts, not
unique people or adoption. G2 remains a selected, bounded second hop. Completed
provider queries do not establish worldwide coverage or causality.

Null-model network statistics and India-impact values are read unchanged from
the pinned latest main host. Their underlying raw acquisition/null ensembles are
not rerun by the dashboard-only/report commands. The null-model table uses linked
faculty, while resilience includes isolated faculty; weighted community
modularity and unweighted null-comparison modularity are separate quantities.
Patent coverage ends in 2023, excludes the Indian Patent Office and lacks
assignees. Case studies are selected documented pathways, not causal effects.

## Verification evidence

Accepted dashboard: **87,158,902 bytes**, SHA-256
`405611a04604eb98ee4908ccac78cca80bcc3518f5f13c218c45453239db9214`.
Two full frozen-input builds at `2026-10-20T13:21:18+00:00` produce identical bytes.
Accepted five-page PDF: **235,022 bytes**, SHA-256
`d7f9bcc05953f1ea478e62dae32ad21c53594a12771db87c2507f8949a071855`.
The repository artifacts are exact copies of the accepted external files.

Fresh checks: **85 Python**, **28 Node controller**, **20 generated-HTML Node**
checks (the latter rerun the resilience cases against the actual artifact),
**23 unified Chrome**, **14 resilience Chrome**, and **14 standalone Chrome**.
PDF generation, all-five-page visual inspection, PDF text/bounds and numerical
assertions, independent read-only SQL reconciliation, full main-payload/renderer
preservation, no-network build audit and unchanged study DB hash were checked.
Earlier CRLF-input, pagination and mobile-overflow failures are retained in the
external evidence and superseded by these final passing runs.

External evidence is kept at
`C:\Users\HP\Desktop\dpcn\assignment\integration_verification_2026-10-20`.
It includes the original refs/main PDF/template/HTML, deterministic build
manifests, read-only/network audit, complete logs, CSVs, browser screenshots,
independent SQL reconciliation and PDF page renders. Final verified counts,
hashes, commands and any superseded failures are recorded in `COMPLETION.md`
there. This file documents methods; the completion record documents operations.

The automated Python suite, Node controller suites and installed-Chrome suites
exercise the integrated sources/artifact. The Chrome harness additionally checks
the latest main network table/growth/citation-tail panels across all six scopes
and all thirteen tabs at phone/tablet widths in both themes. Checks that pass
locally do not replace team/instructor review. No new API acquisition, full
raw-data pipeline build or independent human source review is claimed.
