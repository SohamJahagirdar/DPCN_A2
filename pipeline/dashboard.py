"""Step 5 - interactive dashboard: one self-contained HTML file (data and JS libraries embedded),
so it opens offline and can be sent as a single attachment."""
import json
import re
from pathlib import Path

import requests

import config

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
VENDOR = config.EXTERNAL / "vendor"


def _inline_scripts(html):
    """Replace <script src="https://..."> tags with the library code itself (downloaded once, cached)."""
    VENDOR.mkdir(exist_ok=True)

    def repl(m):
        url = m.group(1)
        path = VENDOR / re.sub(r"[^A-Za-z0-9._-]", "_", url.split("//", 1)[1])
        if not path.exists():
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
        code = path.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f"<script>/* {url} */\n{code}\n</script>"

    return re.sub(r'<script src="(https://[^"]+)"></script>', repl, html)


def _js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def write_dashboard(st, st_without_flagged=None, comparison=None):
    if st_without_flagged:   # the full flagged-paper list is shown from the main data only
        st_without_flagged = dict(st_without_flagged, flagged=[])
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("/*__DATA__*/null", _js(st))
            .replace("/*__DATA_NF__*/null", _js(st_without_flagged))
            .replace("/*__COMPARE__*/null", _js(comparison)))
    try:
        html = _inline_scripts(html)
    except requests.RequestException as e:   # offline: keep CDN links (page then needs internet)
        print(f"[dashboard] could not embed JS libraries ({e}); keeping CDN links")
    config.DASHBOARD_FILE.write_text(html, encoding="utf-8")
    print(f"[dashboard] {config.DASHBOARD_FILE} ({len(html) / 1e6:.1f} MB)")


def write_dashboard_from_outputs():
    """Regenerate the dashboard from committed generated outputs.

    This path is for the repository snapshot, where ``data/raw`` and
    ``data/processed`` are intentionally absent. The existing dashboard
    supplies the previously generated statistics; the advanced network
    section is recomputed from the committed CSV outputs.
    """
    from pipeline import advanced_networks

    existing = config.DASHBOARD_FILE.read_text(encoding="utf-8")

    def embedded(name, next_declaration):
        start = existing.index(f"const {name} = ") + len(f"const {name} = ")
        value, _ = json.JSONDecoder().raw_decode(existing[start:])
        return value

    data_all = embedded("DATA_ALL", "const DATA_NF")
    data_nf = embedded("DATA_NF", "const COMPARE")
    compare = embedded("COMPARE", "let DATA")
    advanced_networks.run()
    advanced = advanced_networks.load_results()
    data_all["advanced"] = advanced
    if data_nf:
        data_nf["advanced"] = advanced
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("/*__DATA__*/null", _js(data_all))
            .replace("/*__DATA_NF__*/null", _js(data_nf))
            .replace("/*__COMPARE__*/null", _js(compare)))
    config.DASHBOARD_FILE.write_text(html, encoding="utf-8")
    print(f"[dashboard] {config.DASHBOARD_FILE} regenerated from committed outputs")
