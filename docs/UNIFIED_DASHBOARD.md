# Unified Research Map dashboard

The permanent development branch includes a single offline `dashboard/index.html`
with all original Research Map tabs, Network Resilience and a native Follow the
Idea tab. It uses the original horizontal navigation, neutral surfaces, existing
Plotly/vis libraries, shared institution/paper controls and light/dark/system
colors. The theme button cycles explicit themes back to system; a shared URL can
specify `theme=light`, `dark` or `system`.

## Scope and interpretation

The header selects Both/IISc/TIFR and includes/excludes **seed papers with more
than twelve authors**. Joint-home papers belong to each institution; their
membership totals cannot be added to form a combined total. Worldwide citing
papers remain in scope even when flagged original seed papers are excluded.
External citer author counts were not acquired and are not guessed.

Follow the Idea tiles describe the header population. Search, field, year,
query-state, pilot and sort controls refine the seed table and its CSV. Every
matching row is exported, including rows beyond the thirty displayed on the
current page. Changing filters clears/replaces an incompatible selected seed.
Combined distinct-citer totals are computed from citation pair sets in SQLite;
per-seed distinct counts are never summed to obtain a combined unique count.

The full-study acquisition panel is explicitly separate from the filtered
population. Unknown seed/citer fields, unresolved identities and censored age
windows remain visible. Pooled cross-field shares require a known seed field
and known citing field; they measure primary-field label differences, not causal
idea adoption or institutional quality. Direct reach, equal-age composition and
conditional sampled G2 are separate views. The fixed two-seed G2 sample is not
resampled by header controls. Both edge proofs remain attached to displayed G2
paths; shared descendants/overlaps do not become fictitious new direct works.
Path export is the displayed excerpt, with explicit omitted/unavailable states.

The three source-inspected stories retain access, author/collaboration,
chronology and interpretation limits, including **zero independent human
reviews**. Automatic candidates are distinguished from those source inspections.

## Required frozen inputs

Generation needs an explicitly supplied external study. A clone alone does not
contain the 4.18GB database or seed-metric JSON. The compact review ZIP also omits
them. On the original workstation the verified study is at:

`C:\Users\HP\Desktop\dpcn\assignment\idea_flow_study_data`

The independently preserved original dashboard is at:

`C:\Users\HP\Desktop\dpcn\assignment\follow_the_idea_review_work_2026-10-20\bundle\comparison\research-map-committed.html`

It is also in the review ZIP under `comparison/research-map-committed.html`.
Another machine must receive these inputs explicitly, verify their hashes, and
pass their actual local paths. The generator has no API fallback and never reads
credentials. Historical raw/cache/processed inputs and vendor caches are absent;
this is a dashboard-only frozen-snapshot render, not a full legacy raw rebuild.

The renderer pins the exact release manifest SHA-256
`eb5a560ea85a6607fb51f973c7e114c34fbda11cfe7c180a59cf48ceeaeca844`,
the original dashboard SHA-256
`38d05a4062a151ff68b098bd72908eda4007038a6fd3c873ca40c7a5f8e34ddc`,
and the two pilot/G2 selection manifests. The pinned release then verifies the
study manifest, SQLite database, seed metrics, summary, G2 summary and case
inspection records. All other protected historical CSVs are hash-checked too;
the new unified HTML is the sole authorized historical-output exception.
Missing, modified or live/uncheckpointed inputs fail before output replacement.
Adopting a later study requires an explicitly reviewed new pin, not disabling
verification.

`build_payload` performs read-only queries against a caller-owned connection.
It does not construct Study, call acquisition/analyze, write candidate results or
import project config. SQLite opens with `mode=ro&immutable=1` and query-only
enabled; supply the frozen checkpoint, never discard or ignore a live WAL.
The historical graph's two resilience variants are recomputed from exact pinned
edges and faculty metrics; baseline communities and betweenness are retained.
Other historical statistics remain intact except the documented deterministic
degree ranking correction. The two vendor bodies are extracted from the pinned
baseline, checked by URL/version and hash-recorded; offline generation fails
instead of retaining remote script links.

## Generate to a new external staging destination

From the development checkout, using an existing Python 3 runtime:

```powershell
$py = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$study = 'C:\Users\HP\Desktop\dpcn\assignment\idea_flow_study_data'
$baseline = 'C:\Users\HP\Desktop\dpcn\assignment\follow_the_idea_review_work_2026-10-20\bundle\comparison\research-map-committed.html'
$historical = 'C:\Users\HP\Desktop\dpcn\assignment\beginner_dashboard_verification_2026-10-20\historical-repo'
$hostBaseline = 'C:\Users\HP\Desktop\dpcn\assignment\integration_verification_2026-10-20\main\dashboard\index.html'
# Record one actual UTC timestamp and use exactly the same value for both builds.
$buildUtc = [DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss+00:00')
& $py -B -m pipeline.dashboard_snapshot `
  --repo . --study $study `
  --release-manifest "$study\verification\release_manifest.json" `
  --baseline-html $baseline --build-utc $buildUtc `
  --historical-repo $historical --host-baseline-html $hostBaseline `
  --output '<new external staging directory>\a\index.html' `
  --standalone-output '<new external staging directory>\standalone\index.html'
& $py -B -m pipeline.dashboard_snapshot `
  --repo . --study $study `
  --release-manifest "$study\verification\release_manifest.json" `
  --baseline-html $baseline --build-utc $buildUtc `
  --historical-repo $historical --host-baseline-html $hostBaseline `
  --output '<same external staging directory>\b\index.html'
```

Replace the staging placeholders with an actual new external directory. Existing
outputs are preserved; select a new destination rather than overwriting evidence.
Repository/study input paths are forbidden as output destinations. Optional
`--standalone-output` renders a new compatibility preview with the shared
controller; it does not replace the released standalone explorer or its report.

Each integrated output has an adjacent `index.manifest.json` with explicit build
UTC, input/source/vendor hashes, six exact scope summaries, size and HTML digest.
Original study/data acquisition timestamps and the publication cutoff remain
distinct from this new dashboard build time. Identical frozen inputs, current
source and explicit build UTC produce identical UTF-8 bytes. Pure rendering has
no network/vendor download or config-directory side effects.

## Validation and branch copy

```powershell
& $py -B -m unittest discover -s tests -p 'test_*.py' -v
$env:DPCN_TEST_PYTHON = $py
$node = 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $node --test tests/test_resilience_dashboard.cjs tests/test_idea_flow_dashboard.cjs
$env:IDEA_FLOW_PLAYWRIGHT = 'C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
$env:IDEA_FLOW_CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
& $node tests/test_idea_flow_browser.cjs '<staging>\standalone\index.html' '<new evidence dir 1>'
& $node tests/test_unified_dashboard_browser.cjs '<staging>\a\index.html' '<new evidence dir 2>'
& $py -B tests/prepare_resilience_browser_fixtures.py '<staging>\a\index.html'
& $node tests/test_resilience_browser.cjs '<staging>\a\index.html' '<new evidence dir 3>'
```

Use installed Chrome/Playwright; no packages or research data are downloaded.
The resilience fixture helper creates three prominently labelled synthetic or
missing-payload pages alongside staging without changing the real staged file.
The native browser checks cover thirteen tabs in all six header scopes, complete
CSV values, direct/age/G2 details, stories, URL reload, themes, offline mobile and
performance. The separate resilience browser test preserves removal/network,
chart-click, variant identity, role/search/sort, export, small-component and
fragment/missing-data scenarios. The adapter tests keep using the explicitly
hash-pinned historical baseline, independent of the new repository HTML.

Compare the two staged SHA-256 values, inspect screenshots and browser errors,
record performance/size and confirm unchanged study/protected inputs. Copy only
the exact accepted staged bytes to `dashboard/index.html` on
the explicitly authorized development/integration branch, then verify the copy's hash. The generation
CLI intentionally does not perform that branch copy or any Git operation.
Keep dashboard manifests, raw study and test screenshots/downloads outside Git.
Main deliberately tracks the final `report/18_IISc_TIFR.pdf`; its intermediate HTML
and report manifest remain ignored. Do not change main or a deployment
configuration. The current task authorizes a local integration commit, with no
push or publication. See [integration/report status](INTEGRATION_REPORT.md).

## New main host and preserved historical study

Main advanced through Impact on India, its case-study expansion, UI updates,
network null-model/growth/tail tests and the first-round PDF generator to
`fa79f72d0d3cbab4baae4b08a4cffbc152f88f30`. The integration merge preserves its code,
generated CSVs and all eleven original/upstream tabs; the unified page now has
thirteen tabs, including the upstream story-first navigation and Method disclosures.
The readability additions are confined to Network Resilience,
Follow the Idea and the shared controller those two sections require.

The study is still the original pinned release. It must not be silently
relabelled as an analysis of a new data release. Supply `--historical-repo` as a
separate external copy of its 62 protected original outputs, checked against the
study's original hashes. On this workstation those files were preserved before
merging main. They contain original project deliverables, not the raw study
database or 9,102 API snapshots. Another machine needs that verified historical
directory explicitly, in addition to the study and old baseline described above.

`--host-baseline-html` supplies the newer main dashboard, extracted as raw Git
blob bytes from the pinned main commit. Its SHA-256 is
`f8d19cf22cc23d721c419ebf1de71ca0d463fa553aded78c1a6d0edcd42f87b2`.
`pipeline/dashboard_host_snapshot.json` pins that host and 62 current-main output
and reference files; Windows CRLF/LF differences are normalized only for these
Git-file checks. The original study input checks remain byte-exact. The renderer
uses the newer host's complete payloads and independently recomputes resilience
from its exact graph and faculty metadata; it retains the original study's
verified seed metrics. Both old/new memberships and author flags are checked.
Missing, mismatched or mixed host/history inputs fail before writing outputs.
Neither host mode nor historical mode acquires research data.

## Beginner explanations and denominator reconciliation

Both analysis tabs now introduce the research question, use explicitly labelled
illustrative examples, provide keyboard-operable learning disclosures and a
numbered walkthrough, and explain selected records before technical detail.
Network Resilience explains nodes, edges, components, degree, articulation,
global/local surviving-pair loss, betweenness, variant-specific thresholds and
why degree/impact rankings disagree. Its walkthrough and comparison button use
actual matching researchers, while baseline comparisons stay explicitly global.

Follow the Idea distinguishes stored citing→cited direction from outward
“is cited by” traversal, links from unique works, seed filters from worldwide
citer scope, primary-field labels from idea adoption, query exhaustion from
scholarly completeness, and sampled/censored/unknown evidence from zero counts.
Header totals remain separate from local table/CSV filters. New helper text
does not change research algorithms, payload values or CSV schemas/precision.

The full-population denominator reconciles exactly: **807,678** total direct
links − **1,339** links with unknown citing fields − **8 additional** links with
known citing fields but unavailable seed fields = **806,331** classifiable
incidences. **184,420 / 806,331 = 22.87%**. One other unavailable-seed-field link
also has an unknown citing field and is already in the first exclusion; it must
not be subtracted twice. The per-scope breakdown is derived from stored totals,
checked for reconciliation and shown beside the cross-field tile. This is a
descriptive link-level primary-field statistic, not unique-work idea adoption
or research quality. The source-inspected examples retain zero independent
human reviews.
