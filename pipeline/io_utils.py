import gzip
import json


def write_jsonl(path, records):
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def read_jsonl(path):
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
