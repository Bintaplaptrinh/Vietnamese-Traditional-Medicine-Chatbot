"""Shared API/local limits, bounded by LFM3's supported context window."""
import os


def context_tokens():
    return max(512, min(262144, int(os.getenv("MODEL_CONTEXT_TOKENS", "262144"))))


def output_tokens():
    return max(1, min(32768, context_tokens() - 1, int(os.getenv("MODEL_MAX_OUTPUT_TOKENS", "32768"))))
