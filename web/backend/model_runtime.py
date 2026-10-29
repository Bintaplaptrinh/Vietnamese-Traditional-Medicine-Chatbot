"""Protect Transformers imports and its process-wide initialization contexts."""
from functools import wraps
from threading import RLock


_RUNTIME_LOCK = RLock()


def serialized_model_load(function):
    @wraps(function)
    def load(*args, **kwargs):
        # from_pretrained temporarily changes class-level initialization hooks.
        # Overlapping calls can leave another model's tied weights uninitialized.
        with _RUNTIME_LOCK:
            return function(*args, **kwargs)
    return load


def model_dependencies(*names):
    # Transformers exposes classes through lazy module attributes. Concurrent
    # first imports can see a partially initialized package and raise ImportError.
    # Include torch in this critical section because Transformers imports it too.
    with _RUNTIME_LOCK:
        import torch
        import transformers

        return (torch, *(getattr(transformers, name) for name in names))
