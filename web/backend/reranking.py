"""Shared Qwen3 reranking, warmed before the application accepts requests."""
import asyncio
import json
import math
import os

from model_runtime import model_dependencies, serialized_model_load


MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
# The checkpoint measured by docs/benchmark, rather than a moving model revision.
REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
GRAPH_TOP_K = 10


class RerankerUnavailable(Exception):
    pass


class QwenReranker:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.lock = asyncio.Lock()
        self.task = None
        self.failed = False
        self.ready = False

    @serialized_model_load
    def _load(self):
        torch, AutoModelForCausalLM, AutoTokenizer = model_dependencies("AutoModelForCausalLM", "AutoTokenizer")

        device = os.getenv("QWEN_RERANKER_DEVICE", "auto")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device.startswith("cuda") and torch.cuda.is_bf16_supported() else (
            torch.float16 if device.startswith("cuda") else torch.float32)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION, padding_side="left")
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=REVISION, dtype=dtype, attn_implementation="sdpa").to(device).eval()
        prefix = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        self.prefix = self.tokenizer.encode(prefix, add_special_tokens=False)
        self.suffix = self.tokenizer.encode(suffix, add_special_tokens=False)
        self.yes = self.tokenizer.convert_tokens_to_ids("yes")
        self.no = self.tokenizer.convert_tokens_to_ids("no")

    def _score(self, question, texts):
        import torch

        if self.model is None:
            self._load()
        scores = []
        for offset in range(0, len(texts), 9):
            pairs = [f"<Instruct>: Given a web search query, retrieve relevant passages that answer the query\n<Query>: {question}\n<Document>: {text}"
                     for text in texts[offset:offset + 9]]
            encoded = self.tokenizer(pairs, padding=False, truncation=True,
                                     max_length=8192 - len(self.prefix) - len(self.suffix),
                                     add_special_tokens=False, return_attention_mask=False)
            rows = [self.prefix + row + self.suffix for row in encoded["input_ids"]]
            data = self.tokenizer.pad({"input_ids": rows}, padding=True, return_tensors="pt").to(self.model.device)
            with torch.inference_mode():
                # Only the final token needs the vocabulary head; no text generation.
                logits = self.model(**data, use_cache=False, logits_to_keep=1).logits[:, -1, :]
                scores.extend(torch.softmax(logits[:, [self.no, self.yes]].float(), dim=1)[:, 1].cpu().tolist())
        return scores

    async def rerank(self, question, evidence, budget):
        if not evidence:
            return []
        owners, texts = [], []
        for index, fact in enumerate(evidence):
            if fact["kind"] == "web":
                parts = [text for text in fact["text"].split("\n\n") if text.strip()]
            elif fact["kind"] in {"text", "ontology"}:
                parts = [fact["text"]]
            else:
                parts = [json.dumps({k: fact[k] for k in ("subject", "predicate", "object", "source", "text", "context", "inferred") if k in fact}, ensure_ascii=False)]
            owners.extend([index] * len(parts))
            texts.extend(parts)
        async with self.lock:
            if self.failed or (self.task is not None and not self.task.done()):
                raise RerankerUnavailable()
            budget.take(len(question) + sum(map(len, texts)), local=True)
            scores = await self._run_scores(question, texts, float(os.getenv("QWEN_RERANKER_TIMEOUT_SECONDS", "60")))
        best = [0.0] * len(evidence)
        for owner, score in zip(owners, scores):
            best[owner] = max(best[owner], score)
        ranked = sorted(({**fact, "rerank_score": best[i]} for i, fact in enumerate(evidence)),
                        key=lambda fact: fact["rerank_score"], reverse=True)
        # Retain every bounded web source: benchmark top-2 lost necessary evidence.
        # Graph selection uses the measured top-10 baseline. IDs are assigned later.
        # The harness packs for need coverage and retains conflict companions.
        return ranked

    async def warmup(self):
        """Load weights and run inference without charging a request budget."""
        async with self.lock:
            if self.ready:
                return
            await self._run_scores("startup warmup", ["startup warmup"],
                                   float(os.getenv("QWEN_RERANKER_STARTUP_TIMEOUT_SECONDS", "180")))

    async def _run_scores(self, question, texts, timeout):
        # Called under the shared lock by warmup and normal requests alike.
        if self.failed or (self.task is not None and not self.task.done()):
            raise RerankerUnavailable()
        self.task = asyncio.create_task(asyncio.to_thread(self._score, question, texts))
        self.task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        try:
            scores = await asyncio.wait_for(asyncio.shield(self.task), timeout)
            if len(scores) != len(texts) or any(type(s) not in (int, float) or not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
                raise ValueError("Invalid reranker scores")
        except (TimeoutError, ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            self.failed = True
            raise RerankerUnavailable() from exc
        self.ready = True
        return scores
