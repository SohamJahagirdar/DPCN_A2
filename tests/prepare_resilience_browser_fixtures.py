"""Explicit labelled negative/synthetic fixtures beside an external staged HTML.

Does not rebuild the actual dashboard or touch the repository/study.
"""
from pathlib import Path
import copy
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.resilience import analyze_resilience


def main():
    source = Path(sys.argv[1]).resolve()
    out = source.parent / "fixtures"
    if source.is_relative_to(ROOT) or out.exists():
        raise ValueError("Use external staged HTML with no existing fixture directory")
    raw = source.read_bytes()
    html = raw.decode("utf-8")
    payloads = {name: json.loads(re.search(r"^const " + name + r" = (.*);[^\r\n]*$", html, re.M).group(1))
                for name in ("DATA_ALL", "DATA_NF")}
    # These labelled fixtures test resilience only. No research data is removed
    # from the actual staged artifact; its complete bytes remain unchanged.
    fixture_base = re.sub(r"^const IDEA_DATA = .*;[^\r\n]*$", "const IDEA_DATA = null;", html, flags=re.M)
    missing = copy.deepcopy(payloads["DATA_NF"])
    missing.pop("resilience")
    star = copy.deepcopy(payloads["DATA_ALL"])
    star["resilience"] = analyze_resilience({"star" + str(i): dict(name="Synthetic " + str(i), inst="IISc", dept="Fixture") for i in range(16)},
                                           [("star0", "star" + str(i), dict(weight=1)) for i in range(1, 16)])
    out.mkdir()
    hashes = {}
    for label, all_data, nf_data in [("missing-filtered-payload", payloads["DATA_ALL"], None),
                                     ("missing-filtered-resilience", payloads["DATA_ALL"], missing),
                                     ("synthetic-15-fragments", star, None)]:
        text = fixture_base
        for name, value in [("DATA_ALL", all_data), ("DATA_NF", nf_data)]:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
            text = re.sub(r"^const " + name + r" = .*;[^\r\n]*$", lambda m: "const " + name + " = " + encoded + ";", text, flags=re.M)
        text = text.replace("<body>", '<body><div style="background:#ffe58a;color:#111;padding:12px;font-weight:bold">VERIFICATION FIXTURE: ' + label + ' — not an observed research result</div>')
        p = out / (label + ".html")
        p.write_text(text, encoding="utf-8", newline="\n")
        hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    assert source.read_bytes() == raw
    (out / "manifest.json").write_text(json.dumps(dict(source_sha256=hashlib.sha256(raw).hexdigest(), labelled_fixtures=hashes), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(directory=str(out), files=list(hashes))))


if __name__ == "__main__":
    main()
