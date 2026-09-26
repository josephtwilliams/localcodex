"""Start one direct engine; save its command, version and log path."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from common import (
    BACKEND,
    BASE_URL,
    CODEX_URL,
    CONTEXT,
    MODEL,
    MODEL_PATH,
    PROFILE,
    ROOT,
    STATE,
    api,
    command,
    save,
)


def alive(pid):
    try:
        os.kill(pid, 0)
        status = command("ps", "-p", str(pid), "-o", "stat=")
        return not any(flag in status for flag in ("Z", "E"))
    except (ProcessLookupError, subprocess.CalledProcessError):
        return False


def stop():
    path = STATE / "server.json"
    if not path.exists():
        return
    state = json.loads(path.read_text())
    for p in reversed(state["processes"]):
        if alive(p["pid"]):
            actual = command("ps", "-p", str(p["pid"]), "-o", "command=")
            if p["identity"] not in actual:
                raise RuntimeError("PID has been reused; refusing to stop another process")
            os.kill(p["pid"], signal.SIGTERM)
            for _ in range(100):
                if not alive(p["pid"]):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Server did not stop; inspect its process before restarting")
    path.unlink()


def start():
    path = STATE / "server.json"
    if path.exists():
        state = json.loads(path.read_text())
        if all(alive(p["pid"]) for p in state["processes"]):
            if (
                state["model"] != MODEL
                or state["backend"] != BACKEND
                or state.get("checkpoint") != str(MODEL_PATH)
                or state.get("context") != CONTEXT
            ):
                raise SystemExit(
                    "A different model or context setting is running. Exit its chat before restarting."
                )
            api("/v1/models", timeout=3)
            print(f"{MODEL} is already running")
            return
        stop()
    # Avoid silently adding another model to a 24 GiB desktop workload.
    processes = command("ps", "-axo", "pid=,stat=,comm=,args=")
    conflicts = []
    for line in processes.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) < 4 or any(flag in fields[1] for flag in ("Z", "E")):
            continue
        executable, args = fields[2], fields[3]
        if (
            Path(executable).name == "llama-server"
            or (
                Path(executable).name.lower().startswith("python")
                and ("mlx_lm.server" in args or "/scripts/mlx_server.py" in args)
            )
            or ("rapid-mlx" in args and "serve" in args)
            or "omlx-server" in executable
            or ("/omlx " in args and "serve" in args)
            or (Path(executable).name == "ollama" and "runner" in args)
        ):
            conflicts.append(fields[0] + " " + executable)
    if conflicts:
        raise SystemExit(
            "Another inference process is running; stop it before loading a comparison model:\n"
            + "\n".join(conflicts)
        )
    if not MODEL_PATH.exists():
        raise SystemExit(f"Missing pinned checkpoint: {MODEL_PATH}")
    if BACKEND == "llama":
        binary = shutil.which("llama-server")
        if not binary:
            raise SystemExit("Install llama.cpp first: brew install llama.cpp")
        cmd = [
            binary,
            "-m",
            str(MODEL_PATH),
            "--alias",
            MODEL,
            "--host",
            "127.0.0.1",
            "--port",
            "8091",
            "-c",
            str(CONTEXT),
            "-np",
            "1",
            "-ngl",
            "99",
            "--jinja",
            "-fa",
            "on",
            "-b",
            "512",
            "-ub",
            "512",
        ]
        version = command(binary, "--version")
        identity = "llama-server"
    elif BACKEND == "omlx":
        base = STATE / ("omlx-" + MODEL)
        models = base / "models"
        models.mkdir(parents=True, exist_ok=True)
        link = models / MODEL
        if link.is_symlink() and link.resolve() != MODEL_PATH.resolve():
            link.unlink()
        if not link.exists():
            link.symlink_to(MODEL_PATH, target_is_directory=True)
        save(
            base / "model_settings.json",
            {
                "version": 1,
                "models": {
                    MODEL: {
                        "model_type_override": "llm",
                        "max_context_window": CONTEXT,
                        "max_tokens": 2048,
                        "is_pinned": True,
                        "is_default": True,
                        "mtp_enabled": False,
                        "vlm_mtp_enabled": False,
                        "dflash_enabled": False,
                    }
                },
            },
        )
        python = ROOT / ".local/omlx-env/bin/python"
        cmd = [
            str(python),
            str(ROOT / "scripts/omlx_server.py"),
            "serve",
            "--base-path",
            str(base),
            "--model-dir",
            str(models),
            "--host",
            "127.0.0.1",
            "--port",
            "8091",
            "--no-hf-cache",
            "--max-concurrent-requests",
            "1",
            "--memory-guard-gb",
            "12",
            "--no-cache",
        ]
        version = command(
            str(python),
            "-c",
            'import importlib.metadata as m; print({k:m.version(k) for k in ["omlx","mlx","mlx-lm"]})',
        )
        identity = "omlx"
    elif BACKEND == "rapid":
        python = ROOT / ".local/rapid-env/bin/python"
        cmd = [
            str(ROOT / ".local/rapid-env/bin/rapid-mlx"),
            "serve",
            str(MODEL_PATH),
            "--served-model-name",
            MODEL,
            "--host",
            "127.0.0.1",
            "--port",
            "8091",
            "--max-num-seqs",
            "1",
            "--max-concurrent-requests",
            "1",
            "--prefill-step-size",
            "128",
            "--max-tokens",
            "2048",
            "--cache-memory-mb",
            "256",
            "--kv-cache-dtype",
            "bf16",
            "--gpu-memory-utilization",
            "0.5",
            "--force-hybrid" if PROFILE.get("hybrid", False) else "--no-hybrid",
            "--no-mllm",
            "--no-spec-decode",
            "--pflash",
            "off",
            "--response-cache-entries",
            "0",
            "--stream-interval",
            "1",
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            PROFILE.get("tool_parser", "hermes"),
            "--reasoning-parser",
            "qwen3",
        ]
        version = command(
            str(python),
            "-c",
            'import importlib.metadata as m; print({k:m.version(k) for k in ["rapid-mlx","mlx","mlx-lm"]})',
        )
        identity = "rapid-mlx"
    else:
        python = ROOT / (
            ".local/omlx-env/bin/python"
            if PROFILE.get("architecture_patch") == "omlx-ling"
            else ".local/mlx-env/bin/python"
        )
        cmd = [
            str(python),
            str(ROOT / "scripts/mlx_server.py"),
            "--model",
            str(MODEL_PATH),
            "--host",
            "127.0.0.1",
            "--port",
            "8091",
            "--decode-concurrency",
            "1",
            "--prompt-concurrency",
            "1",
            "--prefill-step-size",
            "128",
            "--max-tokens",
            "2048",
            "--prompt-cache-size",
            "1",
        ]
        version = command(
            str(python),
            "-c",
            'import importlib.metadata as m; print({k:m.version(k) for k in ["mlx","mlx-lm","transformers"]})',
        )
        identity = "mlx_server.py"
    cmd.extend(PROFILE.get("args", []))
    # Fail before spawning if either managed port is occupied.
    import socket

    for port in [8091] if CODEX_URL == BASE_URL else [8091, 8092]:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
    logfile = STATE / f"{BACKEND}-server.log"
    with logfile.open("w") as out:
        process = subprocess.Popen(cmd, stdout=out, stderr=out, start_new_session=True)
    state = {
        "model": MODEL,
        "checkpoint": str(MODEL_PATH),
        "backend": BACKEND,
        "context": CONTEXT,
        "version": version,
        "command": cmd,
        "log": str(logfile),
        "processes": [{"pid": process.pid, "identity": identity}],
    }
    if BACKEND == "omlx":
        state["model_settings"] = json.loads((base / "model_settings.json").read_text())
    save(path, state)
    try:
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError(logfile.read_text()[-4000:])
            try:
                api("/v1/models", timeout=1)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Server startup timed out")
        if BACKEND == "omlx":
            # Listing models does not mean their weights loaded successfully.
            api(
                "/v1/chat/completions",
                {
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                timeout=120,
            )
        if CODEX_URL != BASE_URL:
            adapter_cmd = [sys.executable, str(ROOT / "scripts/responses_adapter.py")]
            with (STATE / "adapter.log").open("w") as out:
                adapter = subprocess.Popen(
                    adapter_cmd, stdout=out, stderr=out, start_new_session=True
                )
            state["processes"].append({"pid": adapter.pid, "identity": "responses_adapter.py"})
            state["adapter_command"] = adapter_cmd
            save(path, state)
            for _ in range(30):
                try:
                    api("/health", base=CODEX_URL, timeout=1)
                    break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Adapter startup failed")
        print(f"{MODEL} ready at {BASE_URL}; Codex endpoint {CODEX_URL}")
    except BaseException:
        for p in state["processes"]:
            try:
                os.kill(p["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    stop() if args.stop else start()
