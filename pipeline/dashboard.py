"""Step 5 - interactive dashboard: one self-contained HTML file with the statistics embedded."""
import json
from pathlib import Path

import config

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def write_dashboard(st):
    data = json.dumps(st, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    config.DASHBOARD_FILE.write_text(html, encoding="utf-8")
    print(f"[dashboard] {config.DASHBOARD_FILE} ({len(html) / 1e6:.1f} MB)")
