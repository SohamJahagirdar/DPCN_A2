"""Step 5 - interactive dashboard: one self-contained HTML file (data and JS libraries embedded),
so it opens offline and can be sent as a single attachment."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def _inline_scripts(html):
    """Replace <script src="https://..."> tags with the library code itself (downloaded once, cached)."""
    import config
    import requests
    vendor = config.EXTERNAL / "vendor"
    vendor.mkdir(exist_ok=True)

    def repl(m):
        url = m.group(1)
        path = vendor / re.sub(r"[^A-Za-z0-9._-]", "_", url.split("//", 1)[1])
        if not path.exists():
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
        code = path.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f"<script>/* {url} */\n{code}\n</script>"

    return re.sub(r'<script src="(https://[^"]+)"></script>', repl, html)


def _js(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_dashboard(st, st_without_flagged=None, comparison=None, *, idea_flow=None,
                     build_utc, vendor_sources=None):
    """Pure rendering from explicit payloads; frozen mode never fetches vendors."""
    stamp = datetime.fromisoformat(build_utc.replace("Z", "+00:00"))
    if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError("build_utc must be an explicit UTC timestamp")
    # Record this HTML build, without rewriting the statistics/corpus dates or
    # mutating caller-owned payloads (previews may reuse historical statistics).
    built = build_utc
    def stamped(payload):
        return dict(payload, meta=dict(payload["meta"], dashboard_generated_utc=built))
    st = stamped(st)
    if st_without_flagged is not None:
        st_without_flagged = stamped(st_without_flagged)
    if st_without_flagged:   # the full flagged-paper list is shown from the main data only
        st_without_flagged = dict(st_without_flagged, flagged=[])
    html = TEMPLATE.read_text(encoding="utf-8")
    markers = {"/*__DATA__*/null": _js(st), "/*__DATA_NF__*/null": _js(st_without_flagged),
               "/*__COMPARE__*/null": _js(comparison), "/*__IDEA_DATA__*/null": _js(idea_flow),
               "/*__IDEA_VIEW__*/": Path(__file__).with_name("idea_flow_view.js").read_text(encoding="utf-8").replace("</script", "<\\/script")}
    for marker, value in markers.items():
        if html.count(marker) != 1:
            raise ValueError("Missing or duplicated dashboard marker: " + marker)
        html = html.replace(marker, value)
    if vendor_sources is not None:
        def inline(match):
            url = match.group(1)
            if url not in vendor_sources:
                raise ValueError("Missing frozen vendor: " + url)
            return "<script>/* " + url + " */\n" + vendor_sources[url].replace("</script", "<\\/script") + "\n</script>"
        html = re.sub(r'<script src="(https://[^"]+)"></script>', inline, html)
        if re.search(r'<script\s+src=', html):
            raise ValueError("Frozen dashboard contains a remote script")
    return html


def write_dashboard(st, st_without_flagged=None, comparison=None, *, idea_flow=None):
    """Legacy raw-build wrapper. Snapshot generation uses the pure interface."""
    import config
    import requests
    html = render_dashboard(st, st_without_flagged, comparison, idea_flow=idea_flow,
                            build_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        html = _inline_scripts(html)
    except requests.RequestException as e:   # offline: keep CDN links (page then needs internet)
        print(f"[dashboard] could not embed JS libraries ({e}); keeping CDN links")
    config.DASHBOARD_FILE.write_text(html, encoding="utf-8")
    print(f"[dashboard] {config.DASHBOARD_FILE} ({len(html) / 1e6:.1f} MB)")
