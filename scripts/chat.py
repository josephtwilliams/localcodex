"""Launch Codex with a direct local engine, stopping the server on exit."""

import argparse
import fcntl
import os
import subprocess
from pathlib import Path

from common import STATE, codex_config, codex_flags
from start import start, stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-C",
        "--cd",
        type=Path,
        default=Path.cwd(),
        help="Project directory; defaults to the current folder",
    )
    parser.add_argument("prompt", nargs="?")
    args = parser.parse_args()
    project = args.cd.expanduser().resolve()
    if not project.is_dir():
        parser.error(f"Not a directory: {project}")
    lock = (STATE / "chat.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another local chat is open; exit it before starting another.") from None
    start()
    try:
        cmd = [
            "codex",
            "--no-daemon",
            *codex_flags(),
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "on-request",
            "-C",
            str(project),
        ]
        if args.prompt:
            cmd.append(args.prompt)
        return subprocess.run(
            cmd, env=dict(os.environ, CODEX_HOME=str(codex_config(project)))
        ).returncode
    finally:
        print("Stopping local inference and releasing model memory...")
        stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
