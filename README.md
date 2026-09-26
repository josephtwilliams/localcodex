# localcodex

A local Codex fallback for when there’s no Wi-Fi, built for a 24 GB Apple Silicon MacBook.
Run models locally and compare new ones through the Codex CLI.
Default: Qwen3.5 9B on oMLX. Both oMLX profiles use 32K context and compaction at 28K.

## Run

Requires Apple Silicon, uv and Codex CLI. llama.cpp also needs Homebrew.
Download the runtime and model with `setup` while online; local inference then works offline.

```sh
uv sync
./chat setup qwen-omlx
./chat -C ~/Development/my-project
```

Use `-C` to work in another project. `/exit` stops inference and unloads the model.

```sh
./chat -m ling-omlx
./chat list
./chat compare ling-omlx qwen-omlx --runs 3
```

To try a new model, copy a profile in [models.json](models.json), set its checkpoint
and pinned revision, then run `./chat setup NAME` and `./chat compare NAME qwen-omlx`.

## Results

Measured on a 24 GB M4 Pro with 8K context, 26 September 2026.

### Codex tasks

One attempt per task. Read requires a tool call and an exact answer;
edit fixes a Python function and passes five external checks.

| Model / runtime | Read | Read time | Edit | Edit time | Peak RSS | Peak footprint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ling 3.0 Tiny / oMLX | 0/1 | 8.22 s | 1/1 | 26.51 s | 4.76 GiB | 6.79 GiB |
| Qwen3.5 9B / oMLX | 1/1 | 14.71 s | 1/1 | 57.01 s | 5.19 GiB | 7.06 GiB |
| Ling 3.0 Tiny / patched MLX-LM | 1/1 | 5.34 s | 1/1 | 17.22 s | 4.63 GiB | 5.00 GiB |

Ling/oMLX read the correct contents but added extra text. These are integration checks,
not a general coding-quality score.

### Runtime comparison

Three warm generations per pairing, 256-token cap. Speed was measured directly
against the inference server; the separate file-read checks used Codex.

| Model | Runtime | tok/s | Peak RSS | Peak footprint | Exact Codex reads |
| --- | --- | ---: | ---: | ---: | ---: |
| Ling 3.0 Tiny | llama.cpp | 106.08 | 4.75 GiB | 0.34 GiB | 3/3 |
| Ling 3.0 Tiny | MLX-LM 0.32.0 + Ling patch | 122.91 | 4.62 GiB | 4.84 GiB | 3/3 |
| Ling 3.0 Tiny | Rapid-MLX | 157.97 | 1.92 GiB | 4.72 GiB | 1/3 |
| Ling 3.0 Tiny | oMLX, published oQ4e | 163.61 | 4.75 GiB | 4.93 GiB | 2/3 |
| Qwen3.5 9B | llama.cpp | 35.10 | 6.06 GiB | 0.65 GiB | 1/3 |
| Qwen3.5 9B | MLX-LM | 48.20 | 5.13 GiB | 5.46 GiB | 0/3 |
| Qwen3.5 9B | Rapid-MLX | 47.76 | 4.87 GiB | 5.83 GiB | 3/3 |
| Qwen3.5 9B | oMLX | 48.76 | 5.28 GiB | 5.43 GiB | 3/3 |

Memory in this table covers generation only. RSS and footprint are non-additive
engine measurements, not total RAM use; llama.cpp's low footprint excludes clean
mapped weights. Checkpoints, quantization and API adapters differ across some
profiles. Qwen/MLX-LM read the files but returned blank final answers.

Comparisons run file-read and code-edit tasks through Codex, one model at a time.
Timing includes model inference and tools. Results are saved locally under
`results/`, which Git ignores.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

Inference runtimes have separate pinned environments under `.local/`.
