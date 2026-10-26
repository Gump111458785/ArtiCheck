from __future__ import annotations

import math


def confusion(rows, threshold=.5):
    if not rows or not math.isfinite(threshold):
        raise ValueError("Nonempty evaluation rows and finite threshold required")
    result = dict(tp=0, fp=0, tn=0, fn=0)
    for row in rows:
        if type(row["label"]) is not int or row["label"] not in (0, 1):
            raise ValueError("Expected binary integer labels")
        if not isinstance(row["score"], (int, float)) or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1:
            raise ValueError("Expected finite scores in [0,1]")
        positive = row["score"] >= threshold
        key = ("tp" if positive else "fn") if row["label"] else ("fp" if positive else "tn")
        result[key] += 1
    return result


def metrics(rows, threshold=.5):
    c = confusion(rows, threshold)
    tp, fp, tn, fn = (c[k] for k in ("tp", "fp", "tn", "fn"))
    def div(x, y):
        return x / y if y else 0.0
    return {**c, "threshold": threshold,
            "macro_f1": (div(2*tp, 2*tp+fp+fn) + div(2*tn, 2*tn+fp+fn)) / 2,
            "issue_recall": div(tp, tp+fn), "false_positive_rate": div(fp, fp+tn),
            "positive_support": tp+fn, "negative_support": tn+fp,
            "abstention_rate": sum(r.get("verdict") == "inconclusive" for r in rows) / len(rows)}


def select_threshold(validation_rows, max_fpr=.05):
    if not 0 <= max_fpr <= 1:
        raise ValueError("max_fpr must be in [0,1]")
    # Validate first. The >1 threshold represents predicting no positive claims.
    metrics(validation_rows)
    if {r["label"] for r in validation_rows} != {0, 1}:
        raise ValueError("Threshold calibration requires both positive and negative validation examples")
    candidates = [0.0, 1.000000001] + [r["score"] for r in validation_rows]
    eligible = [metrics(validation_rows, t) for t in candidates]
    eligible = [m for m in eligible if m["false_positive_rate"] <= max_fpr]
    return max(eligible, key=lambda m: (m["issue_recall"], m["macro_f1"], m["threshold"]))


def join_report(labels, report):
    findings = {r["claim_id"]: r for r in report["findings"]}
    rows = []
    for label in labels:
        if label["paper_id"] != report["paper_id"] or label["repo_id"] != report["repo_id"]:
            continue
        if label["claim_id"] not in findings:
            raise ValueError("Report missing labeled claim")
        finding = findings[label["claim_id"]]
        rows.append({**label, "score": finding["score"], "verdict": finding["verdict"]})
    return rows
