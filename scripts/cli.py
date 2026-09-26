"""One entry point for chat, installation and Codex comparisons."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from common import MODELS, ROOT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "action", nargs="?", choices=["chat", "list", "setup", "compare"], default="chat"
)
parser.add_argument(
    "profiles", nargs="*", help="Profiles for setup or compare; defaults to the selected model"
)
parser.add_argument(
    "-m", "--model", choices=MODELS, default=os.environ.get("LOCAL_MODEL", "qwen-omlx")
)
parser.add_argument("-C", "--cd", type=Path, default=Path.cwd())
parser.add_argument("--runs", type=int, default=3, help="Repeats per comparison task")
parser.add_argument("--prompt", help="Initial chat prompt")
args = parser.parse_args()
profiles = args.profiles or [args.model]
if any(p not in MODELS for p in profiles):
    parser.error("Unknown profile; run localcodex list")
if args.runs < 1:
    parser.error("--runs must be positive")
env = dict(os.environ, LOCAL_MODEL=args.model)
if args.action == "list":
    for name, p in MODELS.items():
        print(f"{name:16} {p['runtime']:6} {p['repo']}")
    raise SystemExit()
if args.action == "chat":
    if args.profiles:
        parser.error("Use -m PROFILE to select a chat model")
    cmd = ["chat.py", "-C", str(args.cd)]
    if args.prompt:
        cmd.append(args.prompt)
else:
    cmd = [args.action + ".py", *profiles]
    if args.action == "compare":
        cmd += ["--runs", str(args.runs)]
raise SystemExit(
    subprocess.call([sys.executable, str(ROOT / "scripts" / cmd[0]), *cmd[1:]], env=env)
)
