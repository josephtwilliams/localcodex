"""Pinned model selection and shared experiment utilities."""

import datetime as dt
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local/direct"
STATE.mkdir(parents=True, exist_ok=True)
MODELS = json.loads((ROOT / "models.json").read_text())
MODEL_CHOICE = os.environ.get("LOCAL_MODEL", "qwen-omlx")
if MODEL_CHOICE not in MODELS:
    raise SystemExit("Unknown model profile: " + MODEL_CHOICE)
PROFILE = MODELS[MODEL_CHOICE]
if PROFILE["runtime"] not in ("omlx", "llama", "mlx", "rapid"):
    raise SystemExit("Unknown runtime: " + PROFILE["runtime"])
if PROFILE["responses"] not in ("native", "adapter"):
    raise SystemExit("responses must be native or adapter")
if PROFILE.get("architecture_patch") not in (None, "omlx-ling"):
    raise SystemExit("Unknown architecture patch")
if PROFILE.get("architecture_patch") and PROFILE["runtime"] != "mlx":
    raise SystemExit("The Ling architecture patch is only used by the mlx runtime")
BACKEND, MODEL = PROFILE["runtime"], PROFILE["model"]
MODEL_REPO, REVISION = PROFILE["repo"], PROFILE["revision"]
MODEL_FILE = PROFILE.get("file")
MODEL_PATH = (
    Path.home()
    / ".cache/huggingface/hub"
    / ("models--" + MODEL_REPO.replace("/", "--"))
    / "snapshots"
    / REVISION
)
if MODEL_FILE:
    MODEL_PATH /= MODEL_FILE
BASE_URL = "http://127.0.0.1:8091"
CODEX_URL = BASE_URL if PROFILE["responses"] == "native" else "http://127.0.0.1:8092"
CONTEXT = PROFILE.get("context", 8192)
AUTO_COMPACT = PROFILE.get("auto_compact", 6500)


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def api(path, payload=None, timeout=600, base=BASE_URL):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode()}") from exc


def result_dir(kind):
    p = ROOT / "results" / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + kind)
    p.mkdir(parents=True)
    return p


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def memory_snapshot():
    return {"swap": command("sysctl", "vm.swapusage"), "vm_stat": command("vm_stat")}


def environment():
    state = json.loads((STATE / "server.json").read_text())
    if state["model"] != MODEL or state["backend"] != BACKEND:
        raise RuntimeError("Running model differs from LOCAL_MODEL")
    return {
        "utc": dt.datetime.now(dt.UTC).isoformat(),
        "chip": command("sysctl", "-n", "machdep.cpu.brand_string"),
        "memory_bytes": int(command("sysctl", "-n", "hw.memsize")),
        "macos": command("sw_vers"),
        "codex": command("codex", "--version"),
        "server": state,
        "backend": BACKEND,
        "model_repository": MODEL_REPO,
        "model_revision": REVISION,
        "profile": PROFILE,
        "base_url": BASE_URL,
        "codex_url": CODEX_URL,
    }


def model_catalog():
    path = STATE / "models.json"
    entries = []
    for model in sorted({p["model"] for p in MODELS.values()}):
        entries.append(
            dict(
                slug=model,
                display_name=model,
                description="Local text model",
                default_reasoning_level=None,
                supported_reasoning_levels=[],
                shell_type="default",
                visibility="list",
                supported_in_api=True,
                priority=0,
                base_instructions=(ROOT / "prompts/codex.md").read_text(),
                context_window=CONTEXT,
                max_context_window=CONTEXT,
                input_modalities=["text"],
                supports_search_tool=False,
                support_verbosity=False,
                truncation_policy={"mode": "bytes", "limit": 10000},
                experimental_supported_tools=[],
            )
        )
    save(path, {"models": entries})
    return path


def codex_config(project=ROOT):
    home = STATE / "codex-home"
    home.mkdir(exist_ok=True)
    # Persist the provider for the interactive startup account check as well.
    (home / "config.toml").write_text(f'''model_provider = "local_direct"
model = "{MODEL}"
model_catalog_json = {json.dumps(str(model_catalog()))}
model_context_window = {CONTEXT}
model_auto_compact_token_limit = {AUTO_COMPACT}
[model_providers.local_direct]
name = "Direct {BACKEND}"
base_url = "{CODEX_URL}/v1"
wire_api = "responses"
requires_openai_auth = false
[projects.{json.dumps(str(project))}]
trust_level = "trusted"
''')
    return home


def codex_flags():
    flags = [
        "-m",
        MODEL,
        "-c",
        'model_provider="local_direct"',
        "-c",
        f'model_providers.local_direct.name="Direct {BACKEND}"',
        "-c",
        "model_catalog_json=" + json.dumps(str(model_catalog())),
        "-c",
        f'model_providers.local_direct.base_url="{CODEX_URL}/v1"',
        "-c",
        'model_providers.local_direct.wire_api="responses"',
        "-c",
        "model_providers.local_direct.requires_openai_auth=false",
        "-c",
        f"model_context_window={CONTEXT}",
        "-c",
        f"model_auto_compact_token_limit={AUTO_COMPACT}",
        "-c",
        'web_search="disabled"',
    ]
    flags += ["-c", "model_instructions_file=" + json.dumps(str(ROOT / "prompts/codex.md"))]
    for feature in [
        "multi_agent",
        "plugins",
        "apps",
        "browser_use",
        "computer_use",
        "image_generation",
        "goals",
        "workspace_dependencies",
    ]:
        flags += ["--disable", feature]
    return flags
