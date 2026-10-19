"""Stable score rankings shared by statistics and resilience comparisons."""


def ranked_top(rows, score, count=10, *, tie_fields=(), include_ties=False):
    """Rank descending scores, then descending tie fields, then person ID.

    Tie inclusion depends ONLY on the primary score at the cutoff. Secondary
    fields stabilize display; they do not make equal primary scores distinct.
    None scores are unavailable and excluded. Inputs are never changed.
    """
    if count <= 0:
        return []
    ordered = sorted((r for r in rows if r.get(score) is not None),
                     key=lambda r: (-r[score], *(-r[k] for k in tie_fields), r["person"]))
    if not include_ties or len(ordered) <= count:
        return ordered[:count]
    cutoff = ordered[count - 1][score]
    return [r for r in ordered if r[score] >= cutoff]
