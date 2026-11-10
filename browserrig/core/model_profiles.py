from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    """Application context and compaction defaults shared by agents and evals."""

    context_window: int
    reserve_tokens: int
    keep_last_steps: int
    target_ratio: float
    max_summary_tokens: int


MODEL_PROFILES = {
    "gpt-6.1-terra": ModelProfile(
        context_window=256_000,
        reserve_tokens=8192,
        keep_last_steps=2,
        target_ratio=0.4,
        max_summary_tokens=8192,
    ),
}
