# Follow the Idea: reproducible citation reach

This independent study asks which disciplines cite original IISc Bangalore and
TIFR Mumbai papers. It preserves conventional **citing -> cited** edges and
displays the reverse relationship, **seed -> citer**, labelled **is cited by**.
Citation linkage is not proof of idea adoption, causal influence, correctness,
commercialization or societal impact. Actual method/result reuse needs accessible
paper text and citation-passage evidence.

## Isolation and inputs

Run the module directly; do not run `run.py build`. The new modules never import
the directory-creating legacy `config`. They use the Python standard library,
including SQLite, urllib, gzip and CSV. No package installation is required.
Legacy CSVs, generated dashboard and resilience code are read-only inputs.

Required inputs are `outputs/citation_paper_metrics.csv`,
`outputs/group18_data.csv`, and, for a legacy-boundary audit,
`outputs/citation_network.csv`. The seed populations must agree by valid OpenAlex
ID. Repeated faculty/institution attribution rows do not become extra papers.
Initialization records SHA-256 hashes of all output CSVs, external CSVs and the
historical dashboard; `verify-inputs` checks them again.

Both study data and review directories must be explicitly configured outside the
checkout, separate from each other. Nonempty unrecognized directories are refused.
An existing recognized study must have matching cutoff, repository and input
hashes. Existing owned preview HTML is archived by hash before regeneration.

## Commands and checkpoints

The following PowerShell example uses the existing bundled runtimes; set paths
for another machine. Run from the repository root. A credential belongs in a
private file outside the study/review artifact trees, or `OPENALEX_API_KEY`.
The ignored legacy `openalex_key.txt` is also supported. Never supply a key value
as a command-line argument, commit it, or put it in a manifest.

```powershell
$py = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$repo = 'C:\Users\HP\Desktop\dpcn\assignment\DPCN_A2_readonly'
$study = 'C:\Users\HP\Desktop\dpcn\assignment\idea_flow_study_data'
$review = 'C:\Users\HP\Desktop\dpcn\assignment\idea_flow_study_review'
$credential = 'C:\Users\HP\Desktop\dpcn\assignment\.idea_flow_credentials\openalex.key'

& $py -B -m pipeline.idea_flow prepare --repo $repo --study $study
& $py -B -m pipeline.idea_flow budget --study $study --credential-file $credential
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage pilot-metadata
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage pilot
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage pilot-check
# Replay the completed pilot: zero new work requests are required.
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage pilot
& $py -B -m pipeline.idea_flow validate-pilot --study $study
```

Only after `pilot_acceptance.passed` is true:

```powershell
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage full-metadata
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage full --workers 8 --interval 0.15
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage full-check
& $py -B -m pipeline.idea_flow analyze --study $study
& $py -B -m pipeline.idea_flow status --study $study
```

Reissue **the same stage command** after a time/budget/network stop. A completed
page is not requested again. A received snapshot saved just before a crash can be
replayed without another request. Nodes/edges, evidence and the next cursor commit
in one transaction. A process file lock prevents two acquisition processes from
running on the same study. Analysis, selection, preview and integrity commands
take the same lock so exports cannot race acquisition. OS release allows resumption after a
crash; no stale lock deletion is necessary.

The default per-run bounds are 9,800 work requests, one hour, six workers and
0.25 seconds between request starts. At most eight workers are allowed. Retries
count toward the request ceiling and conservatively reserve credit for ambiguous
network failures. Those ceilings can stop a run before the provider's allowance;
they do not certify completion. Status/verification JSON, not exit code alone,
determines whether a stage is exhausted. Unresolved provider IDs remain recorded.

The full corpus has **no 25,000-edge cap**. It proceeds while the approved free
allowance and run resources permit. A partial run is useful as a checkpoint, not
as a complete institution-wide estimate.

## Provider contract and no-paid-spend rule

The current contract was checked against official OpenAlex documentation on
19 October 2026. Core scope is explicit (`corpus=core`) for citers. Seed metadata
lookups use `corpus=all` to resolve every historical seed, including records outside
the current default core. The original institution/type/year collection is frozen
independently of the wider citing-work population.

Global direct-citer requests use `filter=cites:W...|W...` and a publication-date
cutoff, never the India affiliation filter. Each returned `referenced_works` list
is intersected with the requested canonical target set to recover all exact edges.
A result matching several targets is one work and several citation relationships.
An unmatched result or inconsistent distinct-result count prevents completion.

Batch size is 1-100, `per_page=100`, with opaque cursor paging. A null terminal
cursor and reconciled unique results establish query exhaustion; an empty
terminal page is also supported. A repeated cursor, premature empty page, changed
count or unexplained mismatch is not silently accepted. Every page is retained
with its original response metadata and UTC retrieval time. Independent
individual-seed queries cross-check the batched graph. Live index drift can make
this comparison fail; investigate its actual evidence rather than hard-coding
expected numbers or relaxing the gate to force success.

The rate-limit endpoint currently reports daily budget, daily used/remaining USD
and operation costs. Before work requests, the client establishes a conservative
ceiling equal to the lesser of remaining provider budget and the unused portion
of the documented $1 daily free allowance. It never adds prepaid balances or
rotates through other people's keys. The contract currently prices list calls at
$0.0001 and singleton lookups at zero. Changed/unknown budget schemas or tariffs
stop acquisition. A 20-credit safety reserve and periodic live refreshes leave
room for in-flight requests. Credit reservations and page writes are serialized
even when HTTP requests run concurrently. Shared-account spending remains a
reason to monitor provider quota; the client does not authorize any paid upgrade.

Authentication is bearer-header only. Snapshots contain sanitized parameters,
selected work metadata, hashes and timestamps, not authorization headers.
Unanticipated credential echoes are redacted. HTTP errors are logged by status,
not by a potentially sensitive response body or request URL.

Official sources: [authentication/budget](https://help.openalex.org/api/authentication/),
[pricing](https://help.openalex.org/access/example-costs/),
[paging](https://help.openalex.org/api/paging/),
[work attributes](https://help.openalex.org/data/works/attributes/),
[core/expansion scope](https://help.openalex.org/data/works/corpus/),
[citation filter direction](https://help.openalex.org/access/oql-spec/).
The metadata license is CC0; retain source attribution and provenance. This does
not authorize redistribution of publisher full text.

## Identity, fields and dates

Validated short `W...` IDs and HTTPS OpenAlex work URLs normalize to one ID form.
DOI case/prefix normalization is a cross-reference aid, not an automatic merge.
Different IDs with equal DOIs remain separate, flagged candidates. There is no
fuzzy title merge. If a requested singleton resolves to a different provider ID,
store its requested/canonical ID, snapshot evidence and UTC retrieval time.
Canonical alias summaries count a paper once and union its institutional homes.

Minimum selected metadata includes work ID/external IDs, DOI/title, publication
year/date, type, venue, primary topic/hierarchy, citation count, references and
update provenance. `works` keeps the first-seen record for a frozen study, while
all later response pages remain evidence. Seed and citer classification uses
the same selected field and taxonomy, `primary_topic.field.id`. Legacy sampling
labels remain separate, and field drift is exposed. Secondary topics are not
treated as independent fields. Worldwide affiliations/abstract enrichment are
not collected in the baseline release and cannot support geographic or semantic
adoption claims.

The default publication cutoff is 2026-10-15 UTC. Acquisition occurs later and
includes later metadata corrections/backfills; it is **not** the historical index
state on that date. No cited-by total substitutes for enumerated edge IDs.
Missing dates/years stay missing. Same-year edges are order-indeterminate; earlier
citing years are flagged, preserved, and excluded from chronological age-window
measures with explicit counts. No unconditional DAG assumption is made.
Provider same-ID references are flagged in seed/work exports and preserved in
the full raw reference lists. They return to G0 and are explicitly excluded from
G1 and distinct-paper edges; they are different from author self-citations.
An available provider date is exported with unverified precision; a date string
alone does not establish a historically exact publication day.

## Pilot and full-corpus populations

The deterministic pilot uses 24 cells: two institutions, the shared fields Physics
and Astronomy / Mathematics / Biochemistry, Genetics and Molecular Biology,
cohorts 2016-2018 / 2019-2022, and stored citation bands 0-9 / 10-99.
Candidates require ID/title/year/primary field and no unresolved original DOI
conflict. Freeze `SHA256('follow-idea-pilot-v1|42|' + work_id)`, candidate frame,
exclusion reasons, cell counts/ranks, selected paper and skipped joint collisions.
Joint papers retain both homes but are selected once. A failed cell is reported,
never replaced according to how impressive its reach looks.

Pilot gates require 24 resolved identities, exhausted queries, actual multi-page
paging, matching individual-query checks, zero duplicate-request resume, correct
known/unknown denominators and usable retrieved seed fields. These checks use
actual responses, not the earlier audit's citation totals. Workload forecasts are
scenarios: the modest three-field pilot is not representative of all citation
volumes/fields, and old citation totals need not match retrievable edges.

Full acquisition includes every original ID, including metadata-poor seeds,
high-citation works, recent papers and all original disciplines. Missing provider
IDs receive explicit states after singleton checks. All resolvable canonical
seeds receive direct-citer queries. Query completeness and scholarly/metadata
coverage are different facts. If a full batch is pending but a pilot query for
the same target was exhausted, the earlier completed query remains available;
`full_batch_status` separately records the full-stage state. The full acceptance
gate still requires every planned full frontier and six independent cross-checks.

## Measures and denominators

The unit is a distinct canonical citing work per seed. A shared citer contributes
one node and one edge to each seed it cites. Let n be all observed G1 works, k
those with a primary field, u=n-k unknown, and c known-field citers differing
from the seed's retrieved primary field.

- Composition: counts per citing primary-field ID, with known denominator k and
  unknown count u.
- Cross-field share: c/k; unavailable for k=0 or unknown seed field. Missing
  citing fields never become in-field. Bounds among retrieved works are c/n to
  (c+u)/n, not bounds on unindexed scholarship.
- Breadth: distinct known primary fields, shown beside k. Exact expected richness
  in a uniform without-replacement sample of ten known citers is
  `sum_f(1 - choose(k-n_f,10)/choose(k,10))`; unavailable below ten. This is an
  exact resampling expectation and needs no RNG; it does not fix indexing bias.
- Age comparison: seed year through year+3 inclusive, only when that entire
  calendar window ends before the cutoff. Recent windows are right-censored;
  missing years and inversions have separate exclusion counts.
- Group summaries: canonical seeds once with unioned homes. Membership summaries
  for IISc and TIFR overlap on joint papers. Pooled cross-field shares are
  citation-volume weighted; medians use complete-query seed shares. Separate
  field/year/type/stored-volume strata support descriptive matched comparisons.
  `institution_matched_stratum` also splits each such stratum by institutional
  membership, allowing comparisons inside identical declared groups.
- Group exports include known-year/date/type incidences, unresolved identities,
  original DOI conflicts, field-label drift, chronology counts, complete-query
  rarefaction medians and exact eligible/censored age-window denominators. These
  are descriptive summaries, without causal institutional interpretations.
- `field_flows.csv` preserves the seed-field to citing-field matrix for All,
  IISc and TIFR membership, including unknown categories, pair counts and distinct
  endpoint IDs. Citing-work counts are nonadditive across matrix cells; the
  matrix describes citation relationships rather than a distinct-person census.

Do not rank institution quality or infer causal effects from these quantities.
Absent/failed acquisition does not show zero interdisciplinary influence. Even
an exhausted empty query means no matches in the declared source/query/run.

## Sampled G2 and case evidence

After the full direct gate passes:

```powershell
& $py -B -m pipeline.idea_flow sample-g2 --study $study
& $py -B -m pipeline.idea_flow acquire --study $study --credential-file $credential --stage g2
& $py -B -m pipeline.idea_flow analyze --study $study
```

Choose one unique eligible seed per institutional allocation by
`g2-seed-v1|42|` hash, retaining all homes: completed direct query, resolved
identity, at least ten known-field G1 works and 90% field coverage. The separate
`g2-intermediates-v1|42|<seed>|` hash chooses ten intermediates uniformly from the
entire G1 list, including unknown fields, with selection probability 10/|G1|.
No cross-field outcome ranks these seeds. Unfilled slots remain explicit.
G2 has a per-run 500-request ceiling and a study-wide conservative 25,000-edge
cap; budget/wall limits still apply. Reaching a cap leaves a partial checkpoint,
not a complete generation claim.

`reach.csv` uses minimum distance: direct citers remain G1 even when also reached
at two steps. Shared descendants count once in new G2. `sampled_paths.csv`
preserves alternative links, overlaps and return-to-seed cycle flags. Counts are
conditional on sampled intermediate frontiers, with no unweighted global G2
estimate. Unvisited branches are unknown.

Case candidate ranking is separate: complete queries, >=5 known citers, >=90%
field coverage, and no original DOI conflict; choose deterministic cross-field,
modest-volume and comparison candidates with reasons and candidate counts.
These remain **bibliographic candidates** until actual versions, citation edges,
contributions and citing passages are manually examined. Record accessible source
URLs, passage location, supported use/background/comparison/criticism, reviewer
status and uncertainty outside the source checkout. Provider labels or generated
narratives are not ground truth. Inaccessible text permits only a linkage-level
account, not a stronger interpretation.

## Artifacts and explorer

- `study_manifest.json`, `manifests/`: frozen inputs, scope, candidate/selection
  rules and hashes; no credentials.
- `snapshots/<sha256>.json.gz`: immutable, content-addressed sanitized response
  envelopes. Filename is SHA-256 of exact compressed bytes, gzip timestamp zero.
- `study.sqlite3`: normalized works, original seeds, provider aliases, citations,
  page/edge provenance, frontiers and request/budget ledger. This is the durable
  checkpoint; preserve its WAL files when copying a live study.
- `verification/`: latest acquisition/acceptance/budget results.
- `results/`: full seed metrics, group summaries, normalized CSVs, alias/DOI
  conflicts, reach/path tables, G2 summary and candidate metadata. They are
  generated, separately stored study outputs, never source-commit candidates.

```powershell
& $py -B -m pipeline.idea_flow preview --study $study --review $review
& $py -B -m pipeline.idea_flow verify-inputs --study $study
& $py -B -m pipeline.idea_flow verify-study --study $study
& $py -B -m http.server 8018 --bind 127.0.0.1 --directory $review
# Open http://127.0.0.1:8018/index.html, or open the HTML directly offline.
```

The standalone explorer embeds original seed summaries and bounded path excerpts,
not millions of edges. Search/filter/sort, field composition, coverage, age-window
status, unknowns, DOI/provider links and path evidence remain visible. Excerpts
state displayed/omitted counts; G2 is sampled. CSV exports use the complete
filtered seed scope, full numeric precision and fixed headers even when empty.
Path export is explicitly the displayed excerpt. Full acquired data stays in
normalized external tables. There are no third-party browser scripts or external
page requests.

## Tests

```powershell
& $py -B -m unittest discover -s tests -p 'test_idea_flow.py' -v
& $py -B -m unittest discover -s tests -p 'test_resilience*.py' -v
$env:DPCN_TEST_PYTHON = $py
$node = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $node --test tests/test_resilience_dashboard.cjs
# Use an already installed Playwright and Chrome; never install for validation.
$env:IDEA_FLOW_PLAYWRIGHT = 'C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
$env:IDEA_FLOW_CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
& $node tests/test_idea_flow_browser.cjs "$review/index.html" "$review/evidence/new-unique-run"
```

Synthetic/mocked tests cover direction, multi-seed edges, pagination/exhaustion,
counts, transactions, aliases/DOI conflicts, unknowns, time/cycles, selection,
joint homes, full coverage/gates, concurrency-safe free-credit reservations,
retry/cache/resume, G2 overlaps and precision. Browser tests are separate real
installed-browser checks with actual controls/downloads, offline/mobile load,
explicit synthetic negative states and runtime/network-error reporting.

The native **Follow the Idea** tab now shares the Research Map's top navigation,
institution/seed-paper flag controls and light/dark/system styling. The released
standalone explorer remains preserved outside the checkout. See
[Unified dashboard generation](UNIFIED_DASHBOARD.md) for the implemented pure
payload builder, deterministic offline command, pinned external inputs and tests.

The user has authorized the generated unified `dashboard/index.html` on the
permanent development branch in addition to source, tests and methods.
Keep the actual run report, acquired data, previews, screenshots and logs outside
the checkout. Other historical outputs remain protected. Publication or changes
to main require separate authorization. Phase 2 stops before committing/pushing.
