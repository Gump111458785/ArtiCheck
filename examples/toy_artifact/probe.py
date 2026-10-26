"""Trusted, original teaching fixture; no third-party artifact code."""
import json
from pathlib import Path

config = json.loads(Path("experiment.json").read_text())
truth, prediction = config["y_true"], config["y_pred"]
if config["metric_average"] == "macro":
    scores = []
    for label in sorted(set(truth)):
        tp = sum(a == b == label for a, b in zip(truth, prediction))
        fp = sum(a != label and b == label for a, b in zip(truth, prediction))
        fn = sum(a == label and b != label for a, b in zip(truth, prediction))
        scores.append(2 * tp / (2 * tp + fp + fn))
    metric = sum(scores) / len(scores)
elif config["metric_average"] == "micro":
    metric = sum(a == b for a, b in zip(truth, prediction)) / len(truth)
else:
    raise ValueError("Unsupported average")
print(json.dumps({"macro_f1": metric, "train_ids": config["train_ids"], "test_ids": config["test_ids"],
                  "method_steps": config["method_steps"], "baseline_steps": config["baseline_steps"]}))
