# localcodex

Run models offline with Codex on a 24 GB Apple Silicon MacBook.
Default: Qwen3.5 9B on oMLX, with 32K context.

## Run

Requires Apple Silicon, uv and Codex CLI. Run setup online once.

```sh
uv sync
./chat setup qwen-omlx
./chat -C ~/Development/my-project
```

`/exit` unloads the model.

## Compare models

```sh
./chat list
./chat setup ling-omlx
./chat -m ling-omlx
./chat compare ling-omlx qwen-omlx --runs 3
```

To add a model, copy a profile in [models.json](models.json), update its checkpoint
and revision, then run `./chat setup NAME` and `./chat compare NAME qwen-omlx`.

## Results

Measured on a 24 GB M4 Pro with 8K context, 26 September 2026.

### Codex tasks

One attempt each: read a file exactly, then fix a function. Times include Codex and tools.

| Model / runtime | Read | Read time | Edit | Edit time | Peak RSS | Peak footprint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ling 3.0 Tiny / oMLX | 0/1 | 8.22 s | 1/1 | 26.51 s | 4.76 GiB | 6.79 GiB |
| Qwen3.5 9B / oMLX | 1/1 | 14.71 s | 1/1 | 57.01 s | 5.19 GiB | 7.06 GiB |
| Ling 3.0 Tiny / patched MLX-LM | 1/1 | 5.34 s | 1/1 | 17.22 s | 4.63 GiB | 5.00 GiB |

These are basic integration checks, not coding-quality scores.

### Runtime comparison

Three warm generations, capped at 256 tokens. Speed tests use the server directly; file-read tests use Codex.

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

RSS and footprint are separate engine memory measurements, not total system RAM.
llama.cpp's footprint excludes clean mapped weights. Checkpoints and quantization
vary across some profiles.
