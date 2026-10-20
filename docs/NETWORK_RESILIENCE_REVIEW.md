# Network Resilience independent review and implementation record

## 1. Recovered context

Started with a clean checkout on `manas/research-network-resilience` at
`d1eee50277546dc2e3c10d571f9ceb6bee4ff1cb`, tracking the same origin commit.
Local main and origin/main were `32640db4a6e657ddb0dc2ac4174bec1608bdb64b`.
Inspected status/branches/log/remotes/diff, AGENTS.md, README, resilience methods,
analyzer, networks/stats integration, configuration, run.py, dashboard generator
and template, all resilience tests, and the existing separate preview/README.
No existing modifications needed preservation. AGENTS requires the permanent
development branch and protects main, data, outputs and generated dashboard.
The review and browser-verification stages deferred commits and pushes. The
subsequent final source-control task authorizes committing and pushing only
the reviewed source, tests and documentation after all required checks pass.

## 2. Decisions and evidence

| Finding | Evidence | Decision | Regression coverage |
|---|---|---|---|
| A: top-ten overlap | Same faculty graph/variant/universe. Resilience uses degree then person ID; legacy stats used score-only sort/head. Included cutoff degree 25 has 3 tied people, producing 12 inclusive entries. Satyam Suwas is impact rank 9, degree 25, score 0.011759221338259513; legacy table includes him, strict ID ordering does not. Filtered cutoff 24 has 3 tied people, 11 inclusive entries. | Fix inconsistent selection using shared deterministic helper. Retain strict 0/0; additionally report tie-inclusive 1/0 and set sizes. | Degree and impact ties, secondary tie-breakers, shuffled input, empty/zero-loss cases, independent snapshot sets. |
| B: articulation terminology | Vertex removals; positive pair loss is equivalent to increasing full-graph component count. Existing counts verified independently. | High-impact / lower-impact articulation point, threshold unchanged; articulation flag explicitly checks component count. Integer comparison at 1% avoids rounding decisions. | All small graph shapes, isolates/disconnected graphs, independent union-find, exact boundary and adjacent floating-point values. |
| C: percentage headers | cross_community_fraction and lost_pair_fraction were pct-formatted under ambiguous count-like headers. Sort fields themselves were correct. | Explicit percentage headers and tooltips, separate integer pairs disconnected, raw CSV fractions retained. | Header/format/sort/CSV tests, nullable local denominators sorted last. |
| D: fragment truncation | Source already labels up to 12 and uses slice(0,12); real graphs have at most 4/6 fragments. | Retain bound; add dynamic fragments/survivors shown and omitted. Original claim of entirely unlabeled truncation is not supported. | Sixteen-node star produces 15 fragments; verify 12 shown, 3 omitted, survivor totals and clearing. |
| E: hub thresholds | Nearest-rank 90th percentile of positive degrees, minimum 3, gives 12/10. | Retain relative definition. Explicitly state independent variant recalculation; no fixed-threshold view added. | Percentile/minimum/tie tests and active-variant method text. |
| F: betweenness | Existing nx.betweenness_centrality(F, normalized=True); weight=None, endpoints=False, k=None defaults. | Retain baseline values; document exact unweighted full-graph normalization, unreachable pairs and score direction. | Snapshot values preserved; tooltip/method assertions. |
| G: dates | meta.generated comes from compute_stats datetime.now, not a measured corpus snapshot. Existing dates are 15 October 23:54/23:55. | Label statistics build/timezone unrecorded; record actual HTML-generation UTC separately. Corpus snapshot date stays unrecorded. | Actual generator timestamp bounded by clock readings; both variants, no input mutation, absent filtered payload. |
| Component-local loss | Small original components have their losses diluted by connected pairs elsewhere. Three-node path centers in the real snapshot lose 1 pair: global about 0.000434%/0.000460%, component-local 100%. | Add secondary local fraction with component size and denominator; null for no surviving pair. Preserve global ranking. | Isolates, size two, complete/path/star graphs, distinct local/global ordering, all real removals and exports. |
| Related: precision | _clean rounded analyzer fractions to six decimals while CSV retained full precision. It can manufacture score ties; no such positive-score merge occurs in this particular snapshot. | Preserve JSON-safe resilience results at analyzer precision; other statistics keep their prior rounding. | Distinct close scores survive serialization and round-trip JSON. |
| Related: empty CSV schema | Empty searches previously exported only four headers, dropping other metric definitions. Null/null table comparisons also returned a nonzero result. | Preserve complete active schema for empty exports; equal unavailable values compare equal. | Empty download schema and numeric nullable sorting. |
| Related: URL/reload state | Actual Chrome clicks selected excluded data while the URL retained flag=in; reload restored included because startup hash parsing overrides saved state. | Synchronize tab/inst/flag with history.replaceState and preserve other hash parameters. | New regression failed before the source fix and passed afterward; real browser switching and reload passed. |

## 3. Confirmed corrections

The original strict overlap value was not a calculation error. The defect was
that the independently generated degree display could choose a different tied
person, making comparisons appear contradictory. The shared ranking helper now
governs both the summary and stats degree-list selection. Inclusive comparison
describes the substantive tie; IDs merely stabilize strict display selection.
The already-correct impact order was preserved exactly.

Percentage labels, vertex terminology, serialization precision and empty-export
schema were corrected in source with regressions. Fragment coverage and date
provenance improve interpretation without claiming their former calculations
were mathematically wrong. No thresholds, faculty identities, graph construction,
author limits, baseline communities or centralities were changed.

## 4. Methods

Global loss retains `lost_pair_fraction = L/B`: L is disconnected surviving pairs,
B previously connected surviving pairs across the full graph, excluding the
removed researcher and previously disconnected pairs. Zero B gives zero under
the existing convention. Local loss is `L / choose(s-1,2)` for original component
size s; zero denominator gives unavailable, not zero. Equivalently subtract
retained fragment pairs from that local denominator to obtain the same L.
Small-component percentages require the accompanying count and size.

An articulation point increases the number of connected components. High impact
additionally requires positive L and `100*L >= B`; lower impact means positive
loss below that threshold. Hub definitions stay relative to each variant.
Degree strict rankings use score then person ID; impact uses global fraction,
lost pairs, degree, person ID. Inclusive sets use primary cutoff-score equality
alone; comparison excludes zero-impact rows. The complete impact ranking remains
unchanged, including zero-loss researchers at its end.

Betweenness sums shortest-path shares over unordered pairs of other nodes and
normalizes by (n-1)(n-2)/2 for n>2, using all graph nodes. Unreachable pairs add
zero. Endpoints and edge weights are excluded, values are reused after removals.
This matches the actual call and [NetworkX's documented convention](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html).

## 5. Recomputed results

| Measure | Included | Excluding >12-author papers |
|---|---:|---:|
| Nodes / edges | 879 / 1,814 | 877 / 1,642 |
| Articulation removals | 136 | 148 |
| High-impact articulation points | 11 | 23 |
| Maximum lost surviving pairs | 6,713 | 21,840 |
| Maximum global fraction | 2.924774% | 10.072175% |
| Highest global-impact researcher | Sitharam T G | Raghavan Varadarajan |
| Strict / tie-inclusive top-ten overlap | 0 / 1 | 0 / 0 |
| Tie-inclusive degree / positive-impact set sizes | 12 / 10 | 11 / 10 |
| Hub cutoff | 12 | 10 |
| Researchers with available local denominator | 688 | 672 |

These were recomputed from committed real weighted edges and complete faculty
metrics, with independent data-attribution and connectivity oracles. They are
not assertions inserted into the analysis. Every global per-researcher metric,
baseline, edge and impact ordering matches the saved pre-review calculation.
All generated CSV fields agree with the actual HTML payloads.

## 6. Commands and tests

From the checkout, using existing bundled runtimes in PowerShell:

```powershell
$py = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $py -B -m unittest discover -s tests -p 'test_resilience*.py' -v
$env:DPCN_TEST_PYTHON = $py
& $node --test tests/test_resilience_dashboard.cjs
```

Results: **26 Python passed, 0 failed; 18 template/controller passed, 0 failed**.
Python covers synthetic/exhaustive graphs, score denominators, deterministic
ties, roles, CSV exports, real graph reconciliation, every real removal via
independent union-find, generator provenance and statistics serialization.
JavaScript covers actual controller code with DOM/Plotly/vis adapters, both
variants, missing-data guards, selected identity, filters/search/sort, metric
headers/tooltips, fragment coverage, CSV Blob contents, normal renderers and
URL/reload state with preservation of other hash parameters.

From the workspace parent directory:

```powershell
& $py -B resilience_verification\prepare_preview.py
& $node resilience_verification\verify_rendered.cjs
& $py -B resilience_verification\verify_payloads.py
```

The same **18 adapter checks passed, 0 failed** against actual generated HTML.
All three embedded scripts parse, both library scripts are inline, served bytes
match the preview file (HTTP 200), payload/CSV fields match, and global metrics
and ordering match the pre-review baseline. The generated wrapper reuses the
repository test suite rather than maintaining another adapter implementation.

## 7. Dashboard extent

Actual current analyzer and dashboard generator/template were executed offline
against both real historical graphs. Other statistics remain historical, except
the degree ranking reselected from complete metrics with the shared helper.
Generation writes only to the sibling resilience_verification folder, with
isolated config and a network-blocking requests stub. Existing inline chart
libraries provide the vendor cache. Pre-review preview files are preserved as
*.before-review.*. Actual preview build UTC is embedded by the generator.

The computer-use inventory initially returned no browser, but a broader check
found installed Chrome 155 and bundled Playwright 1.62.1. Actual headless Chrome
then passed **14/14 acceptance checks** at a 1600x1100 desktop viewport, using
fresh profiles and locally served pages. This is separate from adapter testing.
Real SVG charts and canvas networks drew, mouse clicks selected researchers,
both variants and URL/reload behavior worked, and search, role/institution
filters, numeric sorting and empty states were exercised. All normal tabs
opened without page errors. All 31,608 rendered resilience table cells matched
their own variant fields and formatting. Six real button-triggered CSV downloads
were independently checked field by field. The final run had no page errors,
console errors, failed page requests or external page requests.

Evidence outside the checkout includes 24 actual screenshots, browser and test
logs, machine-readable reports, original downloaded CSVs and the standalone
HTML in RESILIENCE_REVIEW_BUNDLE.zip. The ZIP-extracted HTML opened via a file
URL with Chrome offline and preserved excluded data and charts after reload.
A portable standard-library checker, run from the extracted ZIP without the
repository, rechecked all 1,756 removals and all six download files. Synthetic
15-fragment and negative missing-payload pages are explicitly labelled fixtures;
they are separate from the real-snapshot results. No manual user acceptance
testing is required for the completed desktop checks.

## 8. Changed source files

- README.md: points readers to secondary loss and tie-aware definitions.
- docs/NETWORK_RESILIENCE.md: methods, schema, interpretation and validation.
- docs/NETWORK_RESILIENCE_REVIEW.md: this decision/evidence record (new).
- pipeline/rankings.py: shared deterministic/tie-inclusive selection (new).
- pipeline/resilience.py: local metric, role names, exact threshold and comparisons.
- pipeline/stats.py: shared degree selection and retained resilience precision.
- pipeline/dashboard.py: actual UTC HTML-build metadata without input mutation.
- pipeline/dashboard_template.html: labels/tooltips, methods, local values,
  fragment coverage, date labels, equal-null sorting, stable empty CSV schema
  and synchronized URL state.
- tests/test_resilience.py: synthetic/local/tie/boundary/export regressions.
- tests/test_resilience_snapshot.py: independent local, role and overlap checks.
- tests/test_resilience_generation.py: generator dates/serialization (new).
- tests/test_resilience_dashboard.cjs: shared template/generated adapter suite.

Sibling preview artifacts, helpers, exports, provenance and saved baseline files
are outside the repository and are not candidates for a source commit.

## 9. Limits and deliberate nonchanges

Raw/cache/processed snapshots are absent; a complete raw-input pipeline rebuild
was not run. No research API calls, keys, package installs, speculative styling,
fixed hub-threshold view or new primary visualization were used. Baseline
betweenness and relative hubs were retained because evidence supports them.
The corpus snapshot date cannot be recovered from meta.generated. The public
site and committed generated HTML remain stale; no publishing claim is made.
Full raw-input integration, other browsers, mobile layouts and native tooltip
popup appearance remain outside the completed desktop acceptance scope.

## 10. Final Git safety

The final source-control step includes only these 12 reviewed source, test and
documentation files on the permanent development branch. Generated previews,
evidence, downloads and ZIP bundles remain outside the checkout and are excluded.
Main remains 32640db4a6e657ddb0dc2ac4174bec1608bdb64b; no merge or deployment is authorized.
No changes to outputs/, dashboard/index.html, raw data or protected caches.
Original dashboard SHA-256 remains
38d05a4062a151ff68b098bd72908eda4007038a6fd3c873ca40c7a5f8e34ddc.
