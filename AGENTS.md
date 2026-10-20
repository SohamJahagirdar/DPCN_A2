# Agent instructions: Group 18 DPCN project

Read `HANDOVER.md` completely before changing anything. Then read `README.md` §3–§6 and `config.py`.

## Hard rules
1. **Scope.** IISc Bangalore and TIFR Mumbai only. TIFR's other centres (NCBS, NCRA, ICTS, TIFR Hyderabad, TIFR-CAM, HBCSE) stay excluded. Do not add institutions.
2. **Ask before fetching.** `python run.py fetch` spends the user's daily OpenAlex budget and can take hours. Ask first, and use `--steps` and `--max-calls`. `python run.py build` makes no API calls (~4–5 min); run it whenever needed.
3. **No raw data, no build.** If `data/raw/` is missing, stop and ask the user for the shared data snapshot (HANDOVER §3.2).
4. **Generated files.** Never edit `outputs/` or `dashboard/index.html` by hand; change the code and rebuild. On feature branches, run `git restore outputs dashboard/index.html` before committing. Only the integrator commits generated files, on `main`.
5. **Public repo.** Never commit, print or paste API keys (`openalex_key.txt`), personal emails or phone numbers. Also keep `data/raw/`, `data/cache/`, `data/processed/`, logs, zip files and `QUESTIONS_FOR_PROFESSOR.md` out of git. Check `git status` before every commit.
6. **No AI attribution.** Do not add `Co-Authored-By:` trailers or other AI credit lines to commits. Only team members should appear as contributors.
7. **Settings in one place.** New thresholds go in `config.py`, with a comment giving their source.
8. **Statistics go through `stats.compute_stats()`.** That way they exist both with and without the flagged (> 12 authors) papers. In the dashboard, renderers read `DATA` so the *Flagged* switch keeps working.
9. **Keep the dashboard clean.** Each chart lives in one place only. Remove unused panels and the statistics behind them. Every measure shown is defined, with its source, on its tab or in the README.
10. **Docs travel with code.** When a definition, threshold or tab changes, update `README.md` and HANDOVER §2 in the same change.
11. **Reproducible output.** Wherever iteration order can reach an output, iterate in sorted order, and keep Louvain at `seed=42`. The same `data/raw/` must give byte-identical CSVs.
12. **Verify before reporting.** After a build, check the numbers (`data/processed/stats.json`, `outputs/stats/`) and screenshot the tab you changed (HANDOVER §10.3). Report failures as they are.

## Windows notes
- Write patch scripts with a file-writing tool, not bash heredocs: `\b` can become a literal backspace character and silently break regexes. Check with `grep -c $'\x08' pipeline/*.py`; every count should be 0.
- Set `PYTHONIOENCODING=utf-8` when printing author names or titles.
