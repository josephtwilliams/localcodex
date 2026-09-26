"""Compare selected profiles using the same Codex tasks, sequentially."""

import argparse
import fcntl
import json
import os
import statistics
import subprocess
import sys

from common import MODELS, ROOT, STATE, result_dir, save
from evaluate import TASKS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("profiles", nargs="+", choices=MODELS)
parser.add_argument("--runs", type=int, default=3)
args = parser.parse_args()
if args.runs < 1:
    parser.error("--runs must be positive")
lock = (STATE / "chat.lock").open("w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("Another local chat or comparison is running. Exit it first.") from None
directory = result_dir("codex")
rows = []
print(f"Results: {directory}", flush=True)
for profile in dict.fromkeys(args.profiles):
    output = directory / profile
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/evaluate.py"),
            str(output),
            "--runs",
            str(args.runs),
        ],
        env=dict(os.environ, LOCAL_MODEL=profile),
    )
    path = output / "summary.json"
    rows.append(
        json.loads(path.read_text())
        if path.exists()
        else {"profile": profile, "error": "Worker failed before saving results", "trials": []}
    )
    save(directory / "summary.json", rows)
lines = [
    "# Codex comparison",
    "",
    "| Profile | "
    + " | ".join(f"{task} pass | {task} seconds" for task in TASKS)
    + " | Peak engine RSS GiB | Peak footprint GiB |",
    "| --- | " + " ---: |" * (len(TASKS) * 2 + 2),
]
for row in rows:
    trials = row["trials"]
    scores = []
    for task in TASKS:
        selected = [t for t in trials if t["task"] == task]
        scores.append(f"{sum(t['passed'] for t in selected)}/{args.runs}")
        scores.append(
            f"{statistics.median(t['seconds'] for t in selected):.2f}" if selected else "—"
        )
    numbers = [row.get("peak_sampled_rss_gib"), row.get("peak_footprint_gib")]
    cells = [f"{n:.2f}" if n is not None else "—" for n in numbers]
    lines.append("| " + " | ".join([row["profile"], *scores, *cells]) + " |")
    if row.get("error"):
        lines.append(f"\n{row['profile']}: {row['error']}\n")
lines += [
    "",
    "Times are medians per task, including Codex, prompt processing, generation and tools; they are not decode tok/s.",
    "All trials, including failures, contribute to the median. Raw per-task timings and token usage are saved.",
    "RSS and footprint are non-additive engine metrics, not whole-system RAM. They exclude the Codex client.",
    "Servers start once per profile; later tasks may reuse runtime caches. No warm-up trials are discarded.",
    "These read and edit checks test basic Codex integration, not general coding quality.",
    "Compare checkpoint revisions, quantization, runtime flags and cache settings in each saved environment.",
]
report = "\n".join(lines) + "\n"
(directory / "report.md").write_text(report)
(ROOT / "results/latest.md").write_text(
    report + f"\nRaw results: `{directory.name}/summary.json`\n"
)
print(report)
raise SystemExit(1 if any(r.get("error") for r in rows) else 0)
