"""Exercise first imports in fresh processes; suite imports can hide this race."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", ["qwen", "lfm3"])
def test_concurrent_cold_transformers_imports(first):
    code = '''
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from model_runtime import model_dependencies

barrier = Barrier(2)
def load(kind):
    barrier.wait()
    if kind == "qwen":
        torch, model, tokenizer = model_dependencies("AutoModelForCausalLM", "AutoTokenizer")
        assert model.__name__ == "AutoModelForCausalLM"
    else:
        torch, tokenizer, model = model_dependencies("AutoTokenizer", "AutoModelForCausalLM")
        assert model.__name__ == "AutoModelForCausalLM"
    if kind == "qwen":
        assert tokenizer.__name__ == "AutoTokenizer"
    return kind

with ThreadPoolExecutor(2) as workers:
    assert set(workers.map(load, ORDER)) == {"qwen", "lfm3"}
'''
    order = [first, "lfm3" if first == "qwen" else "qwen"]
    environment = {**os.environ, "USE_TF": "0", "HF_HUB_OFFLINE": "1",
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2"}
    backend = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = backend + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", "ORDER = " + repr(order) + "\n" + code],
                            env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_concurrent_checkpoint_loading_preserves_tied_weights(tmp_path):
    # Tiny real checkpoints exercise Transformers' global no-init contexts,
    # without downloading production weights or relying on suite import order.
    code = '''
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import sys
from model_runtime import model_dependencies, serialized_model_load

torch, Qwen, QwenConfig, Mpt, MptConfig = model_dependencies(
    "Qwen3ForCausalLM", "Qwen3Config", "MptForCausalLM", "MptConfig")
folder = Path(sys.argv[1])
configs = [QwenConfig(vocab_size=32, hidden_size=16, intermediate_size=32,
    num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
    head_dim=8, tie_word_embeddings=True),
    MptConfig(vocab_size=32, d_model=16, n_heads=2, n_layers=1)]
expected = []
for i, (cls, config) in enumerate(zip((Qwen, Mpt), configs)):
    model = cls(config)
    model.save_pretrained(folder / str(i))
    expected.append({name: value.clone() for name, value in model.state_dict().items()})

@serialized_model_load
def load(i):
    model, info = (Qwen, Mpt)[i].from_pretrained(folder / str(i), output_loading_info=True)
    assert not info.get("missing_keys"), info
    assert not info.get("unexpected_keys"), info
    for name, value in model.state_dict().items():
        assert not value.is_meta, name
        assert torch.equal(value, expected[i][name]), name
    assert model.get_output_embeddings().weight is model.get_input_embeddings().weight

barrier = Barrier(2)
def worker(i):
    barrier.wait()
    load(i)
with ThreadPoolExecutor(2) as workers:
    list(workers.map(worker, [0, 1]))
'''
    backend = str(Path(__file__).resolve().parents[1])
    environment = {**os.environ, "USE_TF": "0", "HF_HUB_OFFLINE": "1",
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2"}
    environment["PYTHONPATH"] = backend + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=environment,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
