"""Run one fresh Codex task and verify its result outside the model's workspace."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from common import ROOT, codex_config, codex_flags, save

TASKS = ["read", "edit"]


def evaluate(task, output, timeout=120):
    output.mkdir(parents=True)
    fixture = ROOT / ".local/fixtures" / secrets.token_hex(8)
    fixture.mkdir(parents=True)
    nonce = secrets.token_hex(16)
    if task == "read":
        (fixture / "proof.txt").write_text(nonce + "\n")
        prompt = "Use your shell to read proof.txt. Respond with only its exact contents. Do not modify files."
    else:
        (fixture / "ranges.py").write_text(
            "def inclusive_range(start, end):\n    return list(range(start, end))\n"
        )
        prompt = (
            "Fix inclusive_range in ranges.py. Return every integer from start through end, including both endpoints. "
            "When start is greater than end, return an empty list. Use tools to inspect and edit the file, then verify the fix."
        )
    cmd = [
        "codex",
        "exec",
        *codex_flags(),
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "read-only" if task == "read" else "workspace-write",
        "-C",
        str(fixture),
        "-o",
        str(output / "final.txt"),
        prompt,
    ]
    save(
        output / "request.json",
        {
            "command": cmd,
            "fixture": str(fixture),
            "expected": nonce if task == "read" else "inclusive endpoints",
        },
    )
    started = time.perf_counter()
    timed_out = False
    with (output / "events.jsonl").open("w") as out, (output / "stderr.txt").open("w") as err:
        process = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            env=dict(os.environ, CODEX_HOME=str(codex_config(fixture))),
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            code = process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    elapsed = time.perf_counter() - started
    events = [
        json.loads(line)
        for line in (output / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    items = [e.get("item", {}) for e in events if e.get("type") == "item.completed"]
    tools = [i for i in items if i.get("type") == "command_execution" and i.get("exit_code") == 0]
    final = (output / "final.txt").read_text().strip() if (output / "final.txt").exists() else ""
    if task == "read":
        read = any(
            "proof.txt" in i.get("command", "") and nonce in i.get("aggregated_output", "")
            for i in tools
        )
        correct = read and final == nonce
        details = {
            "file_read": read,
            "contains_contents": nonce in final,
            "exact_final": final == nonce,
        }
    else:
        # The checker is supplied by this process, never stored in the agent's editable workspace.
        checker = "import runpy; f=runpy.run_path('ranges.py')['inclusive_range']; "
        checker += "assert all(f(a,b)==list(range(a,b+1)) for a,b in [(1,3),(0,0),(-3,2),(4,1),(8,9)]); print('PASS')"
        try:
            check = subprocess.run(
                [sys.executable, "-I", "-c", checker],
                cwd=fixture,
                capture_output=True,
                text=True,
                timeout=5,
            )
            correct = check.returncode == 0
            details = {
                "checker_exit": check.returncode,
                "checker_output": check.stdout + check.stderr,
            }
        except subprocess.TimeoutExpired:
            correct = False
            details = {"checker_error": "timeout"}
        (output / "ranges.py").write_text(
            (fixture / "ranges.py").read_text() if (fixture / "ranges.py").exists() else ""
        )
    usage = [e.get("usage", {}) for e in events if e.get("type") == "turn.completed"]
    result = {
        "task": task,
        "passed": code == 0 and not timed_out and correct,
        "seconds": elapsed,
        "returncode": code,
        "timed_out": timed_out,
        "successful_shell_calls": len(tools),
        "usage": usage,
        **details,
    }
    save(output / "summary.json", result)
    return result


if __name__ == "__main__":
    import re
    import threading

    from common import MODEL_CHOICE, command, environment, memory_snapshot
    from start import start, stop

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    result = {"profile": MODEL_CHOICE, "trials": []}
    finished = threading.Event()
    samples = []
    thread = None
    started = False
    try:
        start()
        started = True
        result["environment"] = environment()
        result["memory_before"] = memory_snapshot()
        pid = result["environment"]["server"]["processes"][0]["pid"]

        def sample():
            while not finished.is_set():
                try:
                    samples.append(int(command("ps", "-p", str(pid), "-o", "rss=")))
                except (ValueError, subprocess.CalledProcessError):
                    pass
                finished.wait(0.25)

        thread = threading.Thread(target=sample, daemon=True)
        thread.start()
        for task in TASKS:
            for repeat in range(args.runs):
                trial = evaluate(task, args.output / f"{task}-{repeat + 1}")
                result["trials"].append(trial)
                save(args.output / "summary.json", result)
                print(
                    f"{MODEL_CHOICE} {task} {repeat + 1}: {'PASS' if trial['passed'] else 'FAIL'} ({trial['seconds']:.2f}s)",
                    flush=True,
                )
        footprint = subprocess.run(
            ["footprint", "-p", str(pid), "-f", "bytes"], capture_output=True, text=True
        )
        (args.output / "footprint.txt").write_text(footprint.stdout + footprint.stderr)
        match = re.search(r"phys_footprint_peak:\s+(\d+) B", footprint.stdout)
        result["peak_footprint_gib"] = int(match[1]) / 1024**3 if match else None
        result["memory_after"] = memory_snapshot()
    except (Exception, SystemExit) as exc:
        result["error"] = str(exc)
    finally:
        finished.set()
        if thread:
            thread.join()
        result["peak_sampled_rss_gib"] = max(samples) / 1024**2 if samples else None
        if "environment" in result:
            log = Path(result["environment"]["server"]["log"])
            if log.exists():
                (args.output / "server.log").write_text(log.read_text())
        if started:
            stop()
        save(args.output / "summary.json", result)
    raise SystemExit(1 if "error" in result else 0)
