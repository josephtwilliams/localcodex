"""Run upstream MLX-LM with a bounded reusable allocator cache.

This is not a process memory cap. Peak allocations are measured separately.
"""

import mlx.core as mx
from common import PROFILE

if PROFILE.get("architecture_patch") == "omlx-ling":
    from omlx.patches.bailing_hybrid import apply_bailing_hybrid_patch

    apply_bailing_hybrid_patch()

from mlx_lm.server import main  # noqa: E402

mx.set_cache_limit(256 * 1024**2)
main()
