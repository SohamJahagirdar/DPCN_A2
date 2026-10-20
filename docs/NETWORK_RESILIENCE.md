# Who holds the research ecosystem together? Network resilience

## Research question and scope

Are collaborations across IISc Bangalore and TIFR Mumbai broadly distributed,
or do a few researchers connect otherwise separated groups?

This is a leave-one-researcher-out connectivity experiment on the **existing
faculty co-authorship graph**, not a new definition of faculty collaboration.
`networks.build_networks()` passes its original `F` graph's nodes and edges,
plus its faculty metric rows, directly to `resilience.analyze_resilience()`.
Existing person identifiers (`R:...`, `H:...`), names, institutions, departments,
betweenness, and Louvain communities are retained. No name-based joins are added.

Nodes are faculty with papers in the selected paper variant, including isolates.
An undirected edge means at least one joint paper with **at most 50 authors**;
weight is its joint-paper count. All eligible papers and the variant with
**at most 12 authors** are analyzed separately through the existing build paths.
The filtered variant can have fewer faculty nodes. The analysis does not change
either threshold, identify faculty again, or alter existing centralities.

The graph combines both institutions. The dashboard institution selector filters
researcher rows, charts and the selection list; it does **not** induce a separate
institutional graph. Baseline tiles and every removal effect are explicitly
labeled as combined-graph results. The selected-person drawing can therefore
show collaborators from the other institution.

## Independent removal procedure

For each existing person key v, traverse the same original adjacency while
ignoring v and all incident edges. Never remove nodes cumulatively. Surviving
co-author links remain even if they came from a paper also involving v.
No input graph, node attributes, edge weights, or metric mappings are mutated.

Connectivity is unweighted: repeated collaborations are retained as display
weights, but one observed collaboration is enough to permit a path. Betweenness
and community assignments are the existing baseline values for that variant;
they are not recomputed after each removal. This distinguishes actual simulated
fragmentation from a centrality ranking.

`networks.py` calls `nx.betweenness_centrality(F, normalized=True)`: exact
shortest-path betweenness with `weight=None`, `endpoints=False`, no source
sampling, on the undirected full faculty graph. For n > 2, sum the fraction
of shortest paths through the node for each unordered pair of other nodes,
then divide by (n-1)(n-2)/2. Unreachable pairs contribute zero; normalization
uses all graph nodes, not only the node's connected component. Larger values
mean greater baseline betweenness, not necessarily greater removal loss.
The existing pipeline uses zero for n <= 2. Joint-paper weights are ignored for
these shortest paths, but retained for the drawing and baseline Louvain inference.
See [NetworkX's definition](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html).

### Denominators and metrics

Let C(n,2) = n(n−1)/2. For component sizes s_i, define:

    possible pairs P(G) = C(n,2)
    connected pairs C(G) = Σ_i C(s_i,2)
    connected-pair fraction CPF(G) = C(G) / P(G)

Components include isolated nodes. The empty graph has zero components; its
largest component size and share are zero. CPF is zero for fewer than two nodes.
These conventions mean "no eligible pair", not statistical evidence of failure.

If v belongs to a component of size s_v:

    B_v = C(G) − (s_v − 1)
    A_v = C(G − v)
    lost pairs L_v = B_v − A_v
    structural score S_v = L_v / B_v

`B_v` counts previously connected pairs **among surviving researchers only**.
Pairs involving v are excluded before evaluating fragmentation. If B_v = 0,
the structural score is defined as zero. Otherwise the score is in [0,1].
Researchers are ranked by decreasing S_v, then L_v, then degree, then person ID.

The secondary **component-local pair-loss fraction** is
`local_pair_loss_fraction = L_v / C(s_v-1,2)`. Its denominator
`component_survivor_pairs_before` counts only surviving pairs in v's original
component. Equivalently, if that component splits into fragment sizes f_i,
the numerator is `C(s_v-1,2) - sum C(f_i,2)`: other original components retain
all their connectivity, so this equals the global numerator L_v. The local
fraction is unavailable (`null` in JSON, blank in CSV) when the denominator is
zero, including isolates and two-node components. It is zero for valid pairs
with no loss. Display it alongside original component size and eligible pair
count: a tiny group may have 100% local loss affecting only one pair. It does
not affect global rankings, articulation categories, or summary maxima.

### Ranking ties

`pipeline/rankings.py` supplies the shared deterministic ranking helper.
The co-authorship degree list is exactly ten entries, using descending degree
and ascending person ID. Degree centrality has the same ordering because its
denominator n-1 is constant within a variant. The resilience impact ordering
is unchanged. Secondary tie-breakers stabilize display, not scientific meaning.

Summary comparisons report **both** strict top-ten overlap and tie-inclusive
overlap (plus both inclusive set sizes). Inclusive sets keep every primary-score
tie at the tenth-place boundary, even if secondary fields differ. Impact
comparisons use only positive-loss rows; zero-loss ties are not evidence of
shared high impact. If fewer than ten eligible rows exist, use all of them.
These comparisons use the combined graph before institution/search/role filters.
Resilience scores retain analyzer precision in statistics JSON rather than
being rounded to six decimals, which could manufacture primary-score ties.

Example: remove the middle of a five-node path. Four nodes remain, with six
previously connected pairs. Two components of size two retain two pairs, so
four pairs are lost: score = 4/6. Removing a leaf loses zero surviving pairs.
Removing one node from a complete graph also loses zero surviving pairs.

Both fraction comparisons are exported:

    raw change = CPF(G − v) − CPF(G)
    survivor-adjusted loss = L_v / C(n−1,2)

The raw change may be positive when an isolate is removed because its denominator
changes. It is **not** the ranking score. The adjusted before fraction is
B_v / C(n−1,2); subtract the after fraction to get the adjusted loss. Fractions
with zero possible pairs are zero.

### Per-researcher export dictionary

`faculty_resilience.csv` contains one row per existing faculty node:

| Columns | Meaning |
|---|---|
| `person,name,inst,department` | Existing faculty identity and metadata |
| `degree` | Unweighted number of distinct collaborators before removal |
| `betweenness,community` | Existing baseline metrics; blank when unavailable |
| `neighbor_communities` | Distinct known community labels among collaborators |
| `comparable_community_edges` | Incident links with known communities at both endpoints |
| `cross_community_edges` | Comparable links whose endpoints have different baseline communities |
| `cross_community_fraction` | Cross-community / comparable edges; blank if none are comparable |
| `neighbor_departments` | Distinct nonempty collaborator department labels, excluding Unknown |
| `cross_institution_edges` | Incident links to a differently labeled, known focal institution |
| `original_component_size` | Size of the component containing the removed node before removal |
| `nodes_after,edges_after,components_after` | Full remaining graph sizes, including isolates |
| `largest_component_after,largest_component_share_after` | Largest component size and size / remaining nodes |
| `connected_pairs_before_remaining` | B_v |
| `possible_pairs_after` | C(n−1,2) |
| `connected_pairs_after` | A_v |
| `survivor_connected_pair_fraction_before` | B_v / C(n−1,2) |
| `connected_pair_fraction_after` | CPF(G−v) |
| `connected_pair_fraction_change` | Raw after-minus-original CPF change |
| `connected_pair_fraction_loss` | Nonnegative survivor-adjusted loss L_v / C(n−1,2) |
| `lost_connected_pairs` | L_v: connected surviving pairs that become disconnected |
| `lost_pair_fraction` | S_v, the primary structural score |
| `component_survivor_pairs_before` | C(s_v-1,2), local eligible surviving pairs |
| `local_pair_loss_fraction` | L_v / C(s_v-1,2), blank if denominator is zero |
| `is_articulation,is_hub,is_high_impact_articulation,roles` | Explicit overlapping role flags and human-readable labels |

The original network's node/edge/component counts, largest component size/share,
possible/connected pairs, CPF, removal counts, maxima, role thresholds, and
top-degree/top-impact overlap are in `resilience_summary.csv` (one combined-graph
summary row). Max lost-pair count and max loss fraction need not identify the
same person. The JSON payload additionally contains original component sizes,
role counts, per-removal fragment sizes, and the existing weighted edges.

Build destinations follow the existing variant output directory:

- `outputs/faculty_resilience.csv`, `outputs/resilience_summary.csv`
- `outputs/without_flagged/faculty_resilience.csv`,
  `outputs/without_flagged/resilience_summary.csv`

These files are produced by the normal build, not by importing the module or
running validation tests. They are deliberately **not generated or committed on
this feature branch**. The integrator can regenerate them with the historical
raw snapshot. `stats.compute_stats()` includes the result in `st['resilience']`
for embedding by the existing dashboard generator; no extra network requests
or external libraries are needed for this feature.

## Interpreting roles

Rules are operational, descriptive thresholds, not universal scientific classes.
They are defined together in `pipeline/resilience.py` and included in the payload.

- **High-impact articulation point:** positive lost-pair count and S_v ≥ 1% of previously
  connected surviving pairs. A one-percent threshold makes major effects
  explicit; it is a presentation convention, not a significance test.
  Articulation status is checked by increased component count after vertex
  removal. Positive lost surviving pairs is equivalent on this simple graph;
  it is not inferred from betweenness or degree. The threshold is evaluated
  exactly as `100*L_v >= B_v` before formatting.
- **Lower-impact articulation point:** positive loss below 1%. Such a person can still matter to
  the particular smaller group that is disconnected.
- **Hub:** degree at least the nearest-rank 90th percentile of positive degrees,
  with a minimum cutoff of three. Ties are all included. The cutoff is
  recalculated for each paper variant.
- **Hub, low fragmentation:** a hub below the high-impact articulation loss threshold.
  This can overlap Lower-impact articulation point; it does not promise zero loss.
- **Cross-community connector:** neighbors span at least two known communities,
  and at least one incident link crosses the researcher's own community boundary.
- **Redundant connector:** degree ≥ 2 and zero lost surviving pairs. Alternative
  paths preserve connectivity, although distances may increase after removal.
- **Limited measured structural impact:** fallback when none of these roles
  apply, including isolates and ordinary leaves. This is not a value judgment.

Roles overlap. A high-impact articulation point may operate inside one Louvain community, and
a cross-community connector can be fully redundant. Unknown community values
are not treated as a real community. Weighted strength and betweenness alone
do not determine these classifications.

## Dashboard interaction

The **Network Resilience** tab uses the active `DATA` object, so the global
flagged-paper switch selects the corresponding independent analysis. An absent
result displays an unavailable message and hides old results; there is no
fallback to the wrong paper variant.

Controls synchronize `tab`, `inst` and `flag` into the URL with
`history.replaceState`, preserving other hash parameters. Startup deep links
take precedence over saved local state, so synchronization is necessary to
preserve the visible variant on reload and sharing. The regression test failed
without this update and passed with it; real Chrome reload checks also passed.

The tab contains baseline/role summaries, a top-15 impact chart, a degree versus
impact scatter, searchable and role-filtered sortable rows, and CSV download.
Click a chart point/bar or use the researcher selector to inspect a removal.
The selected view shows full-graph before/after sizes and pairs plus fragments
of that researcher's original component.

The network drawing samples at most 60 surviving nodes across those fragments;
it is not used to compute metrics. An optional ghost node and dashed original
links show where the removed person used to connect. Fragment colors repeat
after eight colors, so use the fragment-size chart and exact counts as evidence.
The chart shows up to 12 largest fragments and reports total fragments, shown
survivors and any omitted fragments/survivors. Its bars sum to all surviving
members of the original component only when no fragments are omitted. The
removed researcher is never counted in those sums. Display layouts use seed 42.

Percentage headers explicitly distinguish global pair loss, component-local
pair loss, and cross-community link share from integer pairs disconnected.
Sort keys and CSV fractions remain numeric in [0,1]; UI percentages multiply by
100. CSV column names are machine-readable definitions, not percentage values.
Schema names now use `is_high_impact_articulation`, `high_impact_articulations`,
and `high_impact_loss_fraction` in place of the previous bridge-named fields.

### Date provenance

`meta.generated` is the original **statistics build** local wall-clock time,
with timezone unrecorded, not a corpus snapshot timestamp. Historical values
are 15 October 2026, 23:54 / 23:55 for the two variants. A corpus snapshot date
is not present in this metadata and is explicitly labeled unrecorded.
`dashboard.write_dashboard()` adds `meta.dashboard_generated_utc` from the
actual UTC clock for each HTML build, preserving the statistics dates and
caller-owned inputs. Regenerating a preview does not date the underlying data
as newly collected. Dates update with the active variant's metadata.

## Calculated findings from committed snapshot

Validated against commit `32640db4a6e657ddb0dc2ac4174bec1608bdb64b`, using exact
faculty edges embedded in its committed dashboard plus its complete faculty
network metric CSVs to restore isolated nodes and baseline metadata. No raw
collection, API calls, full build, or committed output regeneration was needed.
These are new calculations on that historical graph, not newly collected data.

| Measure | All eligible papers | Without >12-author papers |
|---|---:|---:|
| Faculty nodes / edges | 879 / 1,814 | 877 / 1,642 |
| Connected components / isolates | 185 / 171 | 198 / 181 |
| Largest component | 679 (77.247%) | 660 (75.257%) |
| Connected pairs / possible pairs | 230,200 / 385,881 | 217,494 / 384,126 |
| Connected-pair fraction | 59.656% | 56.620% |
| Removals causing any additional fragmentation | 136 | 148 |
| High-impact articulation points under the ≥1% rule | 11 | 23 |
| Redundant connectors (degree ≥2, zero loss) | 421 | 385 |
| Worst single-removal structural score | 2.925% | 10.072% |
| Strict top-ten degree / positive-impact overlap | 0 | 0 |
| Tie-inclusive top-ten overlap | 1 | 0 |
| Tie-inclusive degree / impact set sizes | 12 / 10 | 11 / 10 |
| Variant-specific hub minimum degree | 12 | 10 |

Specific examples from the calculation:

- **Sitharam T G** (`R:IISc:449`, Civil Engineering), degree 8, has the largest
  all-paper loss: **6,713 pairs, 2.925%**. Their original 679-node component
  becomes fragments of **668, 4, 3, 3** after their removal.
- **Sandeepan Gupta** (`R:TIFR:631`, Theoretical Physics), degree 4, disconnects
  **5,360 pairs, 2.335%**, leaving original-component fragments of **670 and 8**.
  Their collaborators share one baseline community: critical connectivity need
  not mean crossing a Louvain boundary.
- **Ambarish Ghosh** (`R:IISc:141`), degree 40, is the largest all-paper degree
  hub, but removal loses **677 pairs, 0.295%**. This is a lower-impact articulation point/hub with
  much smaller fragmentation than the highest-impact articulation points.
- **Raghavan Varadarajan** (`R:IISc:502`, Molecular Biophysics Unit), degree 8 in
  the filtered graph, has zero all-paper loss but the largest filtered loss:
  **21,840 pairs, 10.072%**, splitting the original 660-node component into
  **624 and 35**. Connectivity can depend on alternative paths supplied by
  13–50-author papers even though >50-author papers are excluded in both graphs.
- **Srinivasan Raghavan** (`R:IISc:330`), filtered degree 30, has **zero** lost
  surviving pairs in that variant: a concrete high-degree redundant connector.

The observed all-paper graph has substantial path redundancy, alongside specific
local bottlenecks. The filtered graph is more vulnerable to its worst individual
removals. This does not establish the effects of actual departures or of several
simultaneous removals. Rankings are sensitive to the graph boundary, missing
collaborations, faculty matching, and the selected paper variant.

## Reproducibility, validation and limits

The analyzer is standard-library-only and accepts the existing graph's data.
IDs, result rows, edge endpoints, components and tie-breaks are ordered stably;
input insertion order does not change the result. No random simulation is used.
For fixed edges and metric labels, results are deterministic. Existing upstream
community inference and faculty matching retain their original limitations.
The routine performs one component traversal per node, using O(n+m) working
graph space; the current two committed variants together took about four
seconds in local validation, including reading and parsing the old dashboard.

Run targeted validation without importing config or running the build:

```bash
python -B -m unittest discover -s tests -p 'test_resilience*.py' -v
node --test tests/test_resilience_dashboard.cjs
```

The Node tests use `python` by default; set `DPCN_TEST_PYTHON` to an existing
interpreter if needed. No npm installation is required. Python tests cover
known synthetic graphs, zero denominators, roles, stable identity, deterministic
ordering, non-mutation, temporary CSV exports, and both committed snapshots.
The JS tests execute the actual template controller with DOM/Plotly/vis adapters
and actual snapshot results, covering filtering, variant switching, selection,
chart clicks, downloads, and absent-data handling. They are not visual browser QA.

### Independent audit, 19 October 2026

The audit reproduced the reported results without hard-coding them as test
expectations. An independent reconstruction from `group18_data.csv` and faculty
identifiers matched every weighted edge and every faculty node in both committed
dashboard graphs. Names, institution/department labels and existing centralities
were checked against the faculty exports. A separate union-find calculation
verified all 1,756 researcher-removal experiments, including survivor-only pair
denominators, components, largest components, fractions, and the inclusive 1%
critical threshold. The original synthetic/exhaustive-graph tests also passed.

One dashboard defect was reproduced and corrected: when `DATA_NF` was entirely
absent but persisted state selected flagged exclusion, the common renderer fell
back to all-paper data and the resilience scope label incorrectly described it
as filtered. The resilience renderer now shows unavailable data in that case.
A regression test failed before the one-line correction and passed afterward.
No mathematical definition or reported numerical result changed.

At that audit stage the suite comprised **17 Python tests and 7 controller tests**.
No full rebuild, browser-level rendering test, package installation, research
API request, or generated-output modification was performed. Controller coverage
does not establish visual correctness in a browser. The required historical raw
snapshot is still absent. `AGENTS.md` records the persistent development branch
and the protected-data/main-branch rules for subsequent work.

The clone lacks the historical raw snapshot and a complete pipeline runtime.
No full rebuild or browser rendering is claimed. Existing `outputs/` and
`dashboard/index.html` remain unchanged; the live/committed dashboard will show
this new tab only after an integrator rebuilds and publishes it.

### Evidence-based review follow-up, 19 October 2026

The follow-up independently established the degree-cutoff tie explanation and
kept strict overlap 0/0, adding tie-inclusive overlap 1/0. The analyzer's global
metrics, edges and complete researcher ordering match the pre-review results
exactly. Clearer articulation terminology, secondary component-local loss,
explicit labels, fragment coverage, date provenance and a shared ranking helper
were added. See [the decision and validation report](NETWORK_RESILIENCE_REVIEW.md).
Current targeted validation: **26 Python tests, 18 template/controller tests,
and the same 18 checks against actual generated preview HTML**, all passing.
The latter two runs share one test suite via `DPCN_TEST_HTML`, avoiding divergent
copies of the controller test logic. The Python suite includes independent
union-find checks of all 1,756 real researcher-variant removals and local loss.
Temporary preview generation and CSV verification occur outside the checkout.
Installed Chrome 155 with already bundled Playwright subsequently passed all
14 desktop headless acceptance checks, including real chart clicks, variant
switching, URL/reload state, search/filter/sort, missing-payload guards, CSV
downloads and the other dashboard tabs. All 31,608 rendered table cells and
all fields in six real downloads matched their corresponding variant data.
The exact ZIP-extracted HTML also opened offline and preserved the excluded
variant after reload. The evidence includes 24 screenshots; all previews,
downloads and logs remain outside the checkout. No page/console errors, failed
page requests or external page requests were observed in the final run.
No full raw-input pipeline rebuild, cross-browser or mobile certification is
claimed. Historical data limitations remain unchanged.

Removal does not model future collaborations, replacements, adaptation, paper
withdrawal, path distances, or external researchers. Co-authorship connectivity
is not a measure of scholarly quality, institutional worth, social impact, or
an individual's actual indispensability. Pair counts emphasize larger groups;
losses for different removed researchers overlap and must not be summed as if
they were independent affected populations.
