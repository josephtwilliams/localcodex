"""Install only the selected runtimes and pinned checkpoints."""

import argparse
import os
import subprocess

from common import MODELS, ROOT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("profiles", nargs="+", choices=MODELS)
args = parser.parse_args()
profiles = [MODELS[name] for name in args.profiles]
runtimes = {
    "omlx" if p.get("architecture_patch") == "omlx-ling" else p["runtime"] for p in profiles
}


def run(*cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


if "llama" in runtimes:
    run("brew", "install", "llama.cpp")
# Use the small MLX environment for HF downloads when installing llama alone.
for runtime in sorted((runtimes - {"llama"}) | ({"mlx"} if runtimes == {"llama"} else set())):
    python = ROOT / f".local/{runtime}-env/bin/python"
    run("uv", "venv", "--python", "3.12", str(python.parent.parent), "--allow-existing")
    run("uv", "pip", "sync", "--python", str(python), str(ROOT / f"requirements/{runtime}.txt"))
download_runtime = next(iter(sorted(runtimes - {"llama"})), "mlx")
python = ROOT / f".local/{download_runtime}-env/bin/python"
for p in profiles:
    code = "from huggingface_hub import snapshot_download; snapshot_download(" + repr(p["repo"])
    code += ", revision=" + repr(p["revision"])
    patterns = (
        [p["file"], "README.md"]
        if p.get("file")
        else ["*.json", "*.safetensors", "*.jinja", "*.model", "README.md"]
    )
    code += ", allow_patterns=" + repr(patterns) + ")"
    run(str(python), "-c", code, env=dict(os.environ, HF_HUB_DISABLE_XET="1"))
print("Ready. Run ./chat -m PROFILE or ./chat compare PROFILE.")
