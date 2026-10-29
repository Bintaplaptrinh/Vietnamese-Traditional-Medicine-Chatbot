"""Shared LFM3 generation, loaded alongside Qwen at application startup."""
import asyncio
import json
import logging
import os

from graph_chat import ModelResponseError, json_object
from model_limits import context_tokens, output_tokens
from model_runtime import model_dependencies, serialized_model_load
from visualisation import VISUAL_SCHEMA, VISUAL_INSTRUCTIONS, MAX_SECTIONS, is_process_question

LOG = logging.getLogger("uvicorn.error.lfm3")
MODEL_ID = "LiquidAI/LFM3-1.7B"
REVISION = "ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7"
ANSWER_STYLE = """CÁCH DIỄN ĐẠT CÂU TRẢ LỜI:
Trả lời trực tiếp, tự nhiên và đúng ngôn ngữ người dùng, như đang giải thích cho một người đọc.
Nêu thông tin được hỏi trước; không kể lại quá trình đọc tài liệu hay liệt kê từng file nguồn.
Trong sections.text, không nhắc tên file PDF, mã tài liệu hay đường dẫn để dẫn nhập một ý.
Tên file trong metadata chỉ dùng để tra cứu nguồn qua citations, không phải tên một nghiên cứu.
Không biến mã file thành tên công trình; không viết kiểu "Nghiên cứu CTUMP.195.pdf ghi nhận...",
"Theo tài liệu..." hoặc lặp lại "Nguồn này cho biết..." ở từng đoạn.
Khi cần giới hạn một kết quả nghiên cứu, diễn đạt bằng đối tượng và bối cảnh thực tế, chẳng hạn:
thay "Nghiên cứu CTUMP.195.pdf ghi nhận qua nghiên cứu trên 100 bệnh nhân đau thắt lưng..."
bằng "Trong một nghiên cứu trên 100 bệnh nhân đau thắt lưng,..." rồi nêu đúng kết quả có trong nguồn.
Đây chỉ là ví dụ cách viết: chỉ dùng số 100, bệnh lý hoặc chi tiết khác nếu bằng chứng thực sự có chúng.
Giữ nguyên cỡ mẫu, đối tượng, điều kiện, mức độ chắc chắn và giới hạn nghiên cứu cần thiết;
không biến kết quả trên một nhóm bệnh nhân thành kết luận cho mọi người.
Chỉ nhắc tên tài liệu hoặc file trong phần diễn giải nếu người dùng hỏi rõ về chính nguồn đó.
Luôn giữ đúng JSON/schema và citation IDs; hệ thống sẽ hiển thị tên nguồn cạnh trích dẫn riêng.
"""


def load_config(source, revision):
    from transformers.dynamic_module_utils import get_class_from_dynamic_module
    cls = get_class_from_dynamic_module("configuration_lfm3.Lfm3Config", source, revision=revision)
    if not getattr(cls, "_attention_rope_compat", False):
        standardize = cls.standardize_rope_params

        def attention_rope(self):
            # Transformers 5.17 standardizes every layer type, but LFM3's conv
            # layers have no rotary embeddings. Preserve the architecture while
            # restricting this normalization step to its attention layers.
            layers = self.layer_types
            # The base converter also inserts flat legacy defaults into this
            # nested mapping; each LFM3 attention type already specifies them.
            self.rope_parameters.pop("rope_theta", None)
            self.rope_parameters.pop("partial_rotary_factor", None)
            self.ignore_keys_at_rope_validation = {"partial_rotary_factor"}
            self.layer_types = [layer for layer in layers if layer in self._attention_layer_types]
            try:
                return standardize(self)
            finally:
                self.layer_types = layers

        cls.standardize_rope_params = attention_rope
        cls._attention_rope_compat = True
    config = cls.from_pretrained(source, revision=revision)
    # Base validation rewrites legacy conv names for LFM2. The pinned LFM3
    # implementation uses conv for mask selection and its own cache operators.
    config.layer_types = ["conv" if layer == "linear_attention" else layer for layer in config.layer_types]
    return config


def context_size():
    return context_tokens()


def response_schema(task, visual=False):
    strings = {"type": "array", "items": {"type": "string"}}
    ids = {"type": "array", "items": {"type": "integer", "minimum": 1}}
    if task == "answer_generation":
        return {"type": "object", "properties": {
            "supported": {"type": "boolean"}, "sections": {"type": "array", "maxItems": MAX_SECTIONS,
                "items": {"type": "object", "properties": {"text": {"type": "string"}, "citations": ids},
                          "required": ["text", "citations"], "additionalProperties": False}},
            "checks": {"type": "array", "items": {"type": "object", "properties": {
                "step": {"type": "integer"}, "sufficient": {"type": "boolean"}, "citations": ids},
                "required": ["step", "sufficient", "citations"], "additionalProperties": False}},
            "next_queries": strings, "clarification": {"type": ["string", "null"]},
            "visualization": VISUAL_SCHEMA},
            "required": ["supported", "sections"] + (["visualization"] if visual else []), "additionalProperties": False}
    if task == "planning":
        return {"type": "object", "properties": {"question": {"type": "string"},
            "language": {"type": "string"}, "queries": strings, "steps": strings, "options": strings,
            "ambiguous": {"type": "boolean"}, "clarification": {"type": ["string", "null"]}},
            "required": ["question", "language", "steps"], "additionalProperties": False}
    if task == "claim_extraction":
        return {"type": "object", "properties": {"claims": {"type": "array", "maxItems": 12,
            "items": {"type": "object"}}}, "required": ["claims"], "additionalProperties": False}
    return {"type": "object"}


class LocalModelUnavailable(RuntimeError):
    pass


class LFM3:
    def __init__(self):
        self.model = self.tokenizer = None
        self.ready = self.failed = False
        self.lock = asyncio.Lock()
        self.task = None
        self.runtime_info = {}
        self.format_tokenizer = None

    @serialized_model_load
    def _load(self):
        torch, AutoTokenizer, AutoModelForCausalLM = model_dependencies("AutoTokenizer", "AutoModelForCausalLM")
        device = os.getenv("LFM3_DEVICE", "auto")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device not in {"cuda", "cpu"}:
            raise ValueError("LFM3_DEVICE must be auto, cpu or cuda")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("LFM3_DEVICE=cuda requires an available CUDA device")
        dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32
        source = os.getenv("LFM3_MODEL_PATH") or MODEL_ID
        revision = os.getenv("LFM3_REVISION", REVISION)
        LOG.info("LFM3 loading: model=%s backend=%s context_tokens=%s max_output_tokens=%s", MODEL_ID,
                 device, context_size(), output_tokens())
        config = load_config(source, revision)
        layer_types = list(config.layer_types)
        self.tokenizer = AutoTokenizer.from_pretrained(source, revision=revision, trust_remote_code=True, config=config)
        self.model = AutoModelForCausalLM.from_pretrained(source, revision=revision, trust_remote_code=True,
            config=config, dtype=dtype, attn_implementation="sdpa").to(device).eval()
        self.model.config.layer_types = layer_types
        self.runtime_info = {"backend": device, "dtype": str(dtype), "model": MODEL_ID, "revision": revision,
            "context_tokens": min(context_size(), self.model.config.max_position_embeddings),
            "max_output_tokens": output_tokens(), "prefill_chunk_tokens": self._chunk_size()}
        if device == "cuda":
            self.runtime_info["gpu_name"] = torch.cuda.get_device_name()
            self.runtime_info["torch_allocated_mib"] = round(torch.cuda.memory_allocated() / 1024**2)
        LOG.info("LFM3 loaded: %s", json.dumps(self.runtime_info))

    @staticmethod
    def _chunk_size():
        return max(128, min(8192, int(os.getenv("LFM3_PREFILL_CHUNK_TOKENS", "2048"))))

    def _format_filter(self, task="generation", visual=False):
        from lmformatenforcer import JsonSchemaParser, TokenEnforcer, TokenEnforcerTokenizerData
        if self.format_tokenizer is None:
            # Use the core API: the packaged Transformers integration imports a
            # tokenizer base class from a path removed by Transformers 5.
            zero = self.tokenizer.encode("0", add_special_tokens=False)[-1]
            special = set(self.tokenizer.all_special_ids)
            regular = []
            for token in range(len(self.tokenizer)):
                if token in special:
                    continue
                after_zero = self.tokenizer.decode([zero, token])[1:]
                alone = self.tokenizer.decode([token])
                regular.append((token, after_zero, len(after_zero) > len(alone)))
            self.format_tokenizer = TokenEnforcerTokenizerData(regular,
                lambda ids: self.tokenizer.decode(ids).rstrip("\ufffd"), self.tokenizer.eos_token_id,
                False, len(self.tokenizer))
        # A fresh parser per request; the shared tokenizer index is immutable.
        enforcer = TokenEnforcer(self.format_tokenizer, JsonSchemaParser(response_schema(task, visual)))
        return lambda batch, ids: enforcer.get_allowed_tokens(ids.tolist()).allowed_tokens

    def _encode(self, system, payload, task="generation"):
        user = json.dumps(payload, ensure_ascii=False)
        if task == "answer_generation":
            system += "\n\n" + ANSWER_STYLE
            # A small generator needs the actual task immediately before its
            # response, rather than just a JSON question after a long context.
            user += ("\n\nHãy trả lời câu hỏi trong dữ liệu trên, không tóm tắt từng nguồn. "
                     "Chỉ dùng bằng chứng được cung cấp; bỏ thông tin không trả lời câu hỏi. "
                     "Mỗi section viết một ý ngắn, trực tiếp, kèm đúng citation ID. "
                     "Không dẫn nhập bằng tên tài liệu, tên cơ quan, file PDF hay URL. "
                     "Giữ đúng ngôn ngữ yêu cầu, phạm vi và giới hạn của bằng chứng. Chỉ trả JSON theo hợp đồng.")
            if "[skill:visualise]\n" in system:
                system += "\n\n" + VISUAL_INSTRUCTIONS
                if is_process_question(payload.get("question", "")):
                    user += ("\nĐây là câu hỏi về QUY TRÌNH: dùng visualization.kind=steps. "
                             "Mỗi bước là MỘT phần tử riêng trong sections, theo đúng thứ tự một quy trình trong nguồn. "
                             "Không viết tất cả các bước trong một đoạn. Giữ đủ các bước, kể cả khi nhiều hơn sáu. "
                             "visualization.sections liệt kê đúng chỉ số các bước, không chứa lời mở đầu hay ghi chú. "
                             "Lưu ý chung có section riêng, không lặp lại. Không thêm thời điểm/chỉ định thực hiện khi không được hỏi. "
                             "Không trộn phiên bản quy trình khác nhau. Không dùng checklist cho quy trình.")
                else:
                    user += ("\nTách riêng từng mục trong sections và thêm visualization phù hợp. "
                         "Nếu hỏi các biện pháp/cách thực hiện, viết 2–6 hành động: MỖI hành động là MỘT section, "
                         "không gộp danh sách vào một đoạn. Dùng visualization.kind=checklist, "
                         "visualization.sections chứa đủ các chỉ số từ 0. Không cần dùng hết nguồn hay chép đủ mọi mục. "
                         "Khi nguồn đủ cho nhiều hành động, không trả visualization=null.")
        return self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=True, return_dict=True, return_tensors="pt", add_generation_prompt=True, enable_thinking=False)

    async def count_input_tokens(self, system, payload, task="generation"):
        if self.tokenizer is None:
            return None
        encoded = await asyncio.to_thread(self._encode, system, payload, task)
        return encoded["input_ids"].shape[-1]

    def _generate(self, system, payload, max_tokens, task="generation"):
        torch, = model_dependencies()
        if self.model is None:
            self._load()
        if not 1 <= max_tokens <= output_tokens():
            raise ModelResponseError(f"Output token limit exceeded: requested={max_tokens} limit={output_tokens()}")
        inputs = self._encode(system, payload, task).to(self.model.device)
        length = inputs["input_ids"].shape[-1]
        context = min(context_size(), self.model.config.max_position_embeddings)
        LOG.info("LFM3 input: task=%s input_tokens=%s max_output_tokens=%s context_tokens=%s", task, length, max_tokens, context)
        if length + max_tokens > context:
            raise ModelResponseError(f"LFM3 context limit exceeded: input_tokens={length} output_tokens={max_tokens} context_tokens={context}")
        # Keep activations bounded during long prefills; allocate KV cache only
        # for actual input, and never compute vocabulary logits for every token.
        cache = None
        chunk = self._chunk_size()
        with torch.inference_mode():
            for start in range(0, max(0, length - chunk), chunk):
                end = min(start + chunk, length - 1)
                prefilled = self.model(input_ids=inputs["input_ids"][:, start:end],
                    attention_mask=inputs["attention_mask"][:, :end], past_key_values=cache,
                    use_cache=True, logits_to_keep=1)
                cache = prefilled.past_key_values
                del prefilled
            generated = self.model.generate(**inputs, past_key_values=cache, max_new_tokens=max_tokens,
                do_sample=False, repetition_penalty=1.1, use_cache=True, logits_to_keep=1,
                prefix_allowed_tokens_fn=self._format_filter(task, visual="[skill:visualise]\n" in system),
                pad_token_id=self.tokenizer.pad_token_id, eos_token_id=self.tokenizer.eos_token_id)
        completion = generated[0][length:]
        eos = self.model.generation_config.eos_token_id
        eos_ids = eos if isinstance(eos, list) else [eos, self.tokenizer.eos_token_id]
        if len(completion) >= max_tokens and int(completion[-1]) not in eos_ids:
            raise ModelResponseError("LFM3 completion exceeded token limit")
        text = self.tokenizer.decode(completion, skip_special_tokens=True).strip()
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        if not text or text.startswith("<think>"):
            raise ModelResponseError("LFM3 returned no completed answer")
        return text

    async def _run(self, system, payload, max_tokens, timeout, task="generation"):
        async with self.lock:
            if self.failed or (self.task is not None and not self.task.done()):
                raise LocalModelUnavailable("LFM3 unavailable")
            self.task = asyncio.create_task(asyncio.to_thread(self._generate, system, payload, max_tokens, task))
            self.task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            try:
                return await asyncio.wait_for(asyncio.shield(self.task), timeout)
            except ModelResponseError:
                raise
            except (TimeoutError, ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                self.failed, self.ready = True, False
                raise LocalModelUnavailable("LFM3 inference failed") from exc

    async def warmup(self):
        if self.ready:
            return
        try:
            await self._run('Return only JSON with a text field.', {"question": "Hello"}, 8,
                            float(os.getenv("LFM3_STARTUP_TIMEOUT_SECONDS", "600")))
        except ModelResponseError:
            pass  # Warmup checks inference, rather than eight-token JSON validity.
        self.ready = True
        LOG.info("LFM3 ready: backend=%s context_tokens=%s max_output_tokens=%s", self.runtime_info.get("backend", "unknown"),
                 context_size(), output_tokens())

    async def complete(self, system, payload, max_tokens, task="generation"):
        if not self.ready:
            raise LocalModelUnavailable("LFM3 startup warmup did not complete")
        text = await self._run(system, payload, max_tokens, float(os.getenv("MODEL_TIMEOUT_SECONDS", "600")), task)
        try:
            return json_object(text)
        except ValueError as exc:
            raise ModelResponseError("LFM3 returned invalid JSON") from exc
