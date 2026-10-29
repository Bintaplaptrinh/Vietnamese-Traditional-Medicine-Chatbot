"""Routing, bounded failover, accounting and shared local startup."""
import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from graph_chat import ModelResponseError
from harness import Budget, BudgetExceeded
from internet import DecisionUnavailable
from local_model import LFM3, LocalModelUnavailable, context_size
from model_router import ModelRouter


def setup(selected="lfm3", ready=True, key="key"):
    async def predict(state, questions, budget):
        budget.take()
        return {"generator": {"choice": selected, "probabilities": {"lfm3": .8, "api": .2}}}
    decisions = SimpleNamespace(predict=AsyncMock(side_effect=predict))
    local = SimpleNamespace(ready=ready, failed=False, complete=AsyncMock(return_value={"text": "local"}))
    router = ModelRouter(None, "https://api.test", key, "api-model", decisions, local)
    return router, local


@pytest.mark.parametrize("selected", ["api", "lfm3"])
def test_jev_selects_generator_and_accounts_calls(selected, caplog):
    caplog.set_level(logging.INFO, logger='uvicorn.error.model_router')
    async def run():
        router, local = setup(selected)
        budget, trace = Budget({"calls": 5}), []
        with patch('model_router.complete', AsyncMock(return_value={"text": "api"})) as api:
            result = await router.complete("instructions", {"question": "xin chào"}, 100, budget, trace)
        assert result["text"] == ("local" if selected == "lfm3" else "api")
        assert budget.calls == 2
        assert budget.local_calls == int(selected == "lfm3")
        assert api.await_count == int(selected == "api")
        assert local.complete.await_count == int(selected == "lfm3")
        assert trace[0]["used"] == selected and not trace[0]["fallback"]
    asyncio.run(run())
    label = 'LFM3-1.7B' if selected == 'lfm3' else 'API Model'
    assert f'decision={label} source=JEV' in caplog.text
    assert f'used={label} fallback=False' in caplog.text
    assert 'instructions' not in caplog.text and 'xin chào' not in caplog.text


@pytest.mark.parametrize("selected", ["api", "lfm3"])
def test_cross_model_fallback_once(selected, caplog):
    caplog.set_level(logging.INFO, logger='uvicorn.error.model_router')
    async def run():
        router, local = setup(selected)
        if selected == "lfm3":
            local.complete.side_effect = ModelResponseError("invalid JSON")
        api = AsyncMock(side_effect=httpx.ConnectError("offline")) if selected == "api" else AsyncMock(return_value={"text": "api"})
        budget, trace = Budget({"calls": 5}), []
        with patch('model_router.complete', api):
            await router.complete("instructions", {}, 100, budget, trace)
        assert api.await_count == local.complete.await_count == 1
        assert trace[0]["fallback"] and len(trace[0]["attempts"]) == 2
        assert budget.calls == 3 and budget.local_calls == 1 and budget.api_calls == 2
    asyncio.run(run())
    assert 'Model failed:' in caplog.text and 'Model fallback:' in caplog.text
    assert 'fallback=True' in caplog.text
    assert 'reason=' in caplog.text


def test_unavailable_local_and_missing_api_key_use_remaining_model():
    async def run():
        for selected, ready, key in [("lfm3", False, "key"), ("api", True, None)]:
            router, local = setup(selected, ready, key)
            with patch('model_router.complete', AsyncMock(return_value={"ok": True})) as api:
                await router.complete("instructions", {}, 100, Budget({"calls": 5}))
            assert api.await_count == int(not ready)
            assert local.complete.await_count == int(ready)
    asyncio.run(run())


def test_both_fail_and_budget_does_not_allow_unbounded_retry():
    async def run():
        router, local = setup()
        local.complete.side_effect = LocalModelUnavailable()
        with patch('model_router.complete', AsyncMock(side_effect=ModelResponseError())) as api:
            with pytest.raises(ModelResponseError):
                await router.complete("instructions", {}, 100, Budget({"calls": 5}))
            assert local.complete.await_count == api.await_count == 1
        with patch('model_router.complete', AsyncMock()) as api:
            with pytest.raises(BudgetExceeded):
                await router.complete("instructions", {}, 100, Budget({"calls": 2}))
            api.assert_not_awaited()
    asyncio.run(run())


def test_routing_outage_prefers_local_without_bypassing_verification(caplog):
    caplog.set_level(logging.INFO, logger='uvicorn.error.model_router')
    async def run():
        router, local = setup()
        router.decisions.predict.side_effect = DecisionUnavailable()
        trace = []
        await router.complete("instructions", {}, 100, Budget({"calls": 5}), trace)
        local.complete.assert_awaited_once()
        assert trace[0]["reason"] == "routing_unavailable"
    asyncio.run(run())
    assert 'decision=LFM3-1.7B source=local fallback (JEV unavailable)' in caplog.text


@pytest.mark.parametrize("task, result", [("planning", {"question": "A"}),
    ("answer_generation", {"supported": False, "sections": []}), ("claim_extraction", {"claims": []})])
def test_malformed_task_schema_falls_back(task, result):
    async def run():
        router, local = setup()
        local.complete.return_value = {}
        with patch('model_router.complete', AsyncMock(return_value=result)) as api:
            assert await router.complete("instructions", {}, 100, Budget({"calls": 5}), task=task) == result
        api.assert_awaited_once()
    asyncio.run(run())


def test_local_draft_still_requires_independent_jev_verification():
    from test_harness import harness, request, GOOD
    async def run():
        runner = harness()
        runner.planner = 'lexical'
        router, local = setup()
        local.complete.return_value = GOOD
        runner.router = router
        with patch('model_router.complete', AsyncMock()) as api:
            result = await runner.run(request('graph'))
        api.assert_not_awaited()
        assert result['verification_status'] == 'verified'
        runner.internet.decisions.predict.assert_awaited_once()
        assert result['model_routing'][0]['used'] == 'lfm3'
        assert result['usage']['local_calls'] == 1 and result['usage']['api_calls'] == 2
        runner.internet.decisions.predict.side_effect = DecisionUnavailable()
        result = await runner.run(request('graph'))
        assert result['verification_status'] == 'insufficient'
        assert result['reason'] == 'verification_unavailable'
    asyncio.run(run())


@pytest.mark.parametrize('scopes, retained', [
    (['direct', 'irrelevant'], [1]), (['irrelevant', 'irrelevant'], [1, 2]),
    (['direct', 'context'], [1, 2])])
def test_routing_batch_focuses_source_relationship_without_extra_calls(scopes, retained):
    from harness import with_knowledge_context
    from test_harness import GOOD
    async def run():
        router, local = setup()
        local.complete.return_value = GOOD
        evidence = [{'id': 1, 'kind': 'web', 'text': 'Safety measures: wear protective glasses.'},
                    {'id': 2, 'kind': 'text', 'text': 'Research on unrelated diagnoses.'}]
        async def predict(state, questions, budget):
            budget.take()
            assert set(questions) == {'generator', 'source:1', 'source:2'}
            assert state['evidence']['1']['text'] == evidence[0]['text']
            assert evidence[0]['text'] not in state['instructions']
            return {'generator': {'choice': 'lfm3'}, **{
                f'source:{i}': {'choice': scope} for i, scope in enumerate(scopes, 1)}}
        router.decisions.predict.side_effect = predict
        trace, budget = [], Budget({'calls': 4})
        await router.complete(with_knowledge_context('policy', evidence), {'question': 'Safety measures?'},
                              100, budget, trace, task='answer_generation', evidence=evidence)
        actual = json.loads(local.complete.call_args.args[0].split('UNTRUSTED RETRIEVED KNOWLEDGE JSON:\n')[1])
        assert [fact['id'] for fact in actual] == retained
        assert len(evidence) == 2 and budget.calls == 2
        router.decisions.predict.assert_awaited_once()
    asyncio.run(run())


def test_source_focus_keeps_conflict_companions_and_originals_on_decision_outage():
    from harness import with_knowledge_context
    from test_harness import GOOD
    async def run():
        router, local = setup()
        local.complete.return_value = GOOD
        facts = [{'id': i, 'kind': 'text', 'text': str(i), 'conflict_group': 'conflict'} for i in (1, 2)]
        router.decisions.predict.return_value = None
        async def predict(state, questions, budget):
            budget.take()
            return {'generator': {'choice': 'lfm3'}, 'source:1': {'choice': 'direct'}, 'source:2': {'choice': 'irrelevant'}}
        router.decisions.predict.side_effect = predict
        system = with_knowledge_context('policy', facts)
        await router.complete(system, {}, 100, Budget({'calls': 4}), task='answer_generation', evidence=facts)
        assert local.complete.call_args.args[0] == system
        router.decisions.predict.side_effect = DecisionUnavailable()
        await router.complete(system, {}, 100, Budget({'calls': 4}), task='answer_generation', evidence=facts)
        assert local.complete.call_args.args[0] == system
    asyncio.run(run())


def test_native_load_uses_exact_checkpoint_cuda_and_shared_caps(monkeypatch, caplog):
    monkeypatch.setenv('LFM3_DEVICE', 'cuda')
    monkeypatch.delenv('LFM3_MODEL_PATH', raising=False)
    caplog.set_level(logging.INFO, logger='uvicorn.error.lfm3')
    cuda = SimpleNamespace(is_available=lambda: True, is_bf16_supported=lambda: True,
        get_device_name=lambda: 'GPU', memory_allocated=lambda: 3 * 1024**3)
    torch = SimpleNamespace(cuda=cuda, bfloat16='bfloat16', float16='float16', float32='float32')
    model = Mock()
    model.to.return_value.eval.return_value = model
    model.config.max_position_embeddings = 262144
    tokenizer, factory = Mock(), Mock()
    factory.from_pretrained.return_value = model
    with patch('local_model.model_dependencies', return_value=(torch, tokenizer, factory)), \
         patch('local_model.load_config', return_value=SimpleNamespace(layer_types=['conv', 'full_attention'])):
        local = LFM3()
        local._load()
    assert factory.from_pretrained.call_args.args == ('LiquidAI/LFM3-1.7B',)
    assert factory.from_pretrained.call_args.kwargs['trust_remote_code'] is True
    assert factory.from_pretrained.call_args.kwargs['attn_implementation'] == 'sdpa'
    assert local.runtime_info['backend'] == 'cuda'
    assert local.runtime_info['context_tokens'] == 262144
    assert local.runtime_info['max_output_tokens'] == 32768
    assert 'LFM3 loaded:' in caplog.text


def test_shared_caps_and_oversized_generation_do_not_call_either_model(monkeypatch):
    from model_limits import output_tokens
    monkeypatch.delenv('MODEL_CONTEXT_TOKENS', raising=False)
    monkeypatch.delenv('MODEL_MAX_OUTPUT_TOKENS', raising=False)
    assert context_size() == 262144 and output_tokens() == 32768
    async def run():
        router, local = setup()
        with patch('model_router.complete', AsyncMock()) as api:
            with pytest.raises(ModelResponseError, match='Output token limit'):
                await router.complete('instructions', {}, 32769, Budget({'calls': 5}))
        local.complete.assert_not_awaited()
        api.assert_not_awaited()
        router.decisions.predict.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('selected', ['api', 'lfm3'])
def test_max_output_cap_is_identical_for_api_and_local(selected):
    async def run():
        router, local = setup(selected)
        with patch('model_router.complete', AsyncMock(return_value={'text': 'ok'})) as api:
            await router.complete('instructions', {}, 32768, Budget({'calls': 5}))
        state = router.decisions.predict.call_args.args[0]
        assert state['local_context_tokens'] == state['api_context_tokens'] == 262144
        assert state['shared_output_cap'] == 32768
        if selected == 'api':
            assert api.call_args.kwargs['max_tokens'] == 32768
        else:
            assert local.complete.call_args.args[2] == 32768
    asyncio.run(run())


def test_lfm3_config_preserves_conv_architecture_and_nested_rope():
    from local_model import load_config
    class Config:
        _attention_layer_types = ('full_attention', 'sliding_attention')
        def standardize_rope_params(self):
            assert 'conv' not in self.layer_types
            assert 'rope_theta' not in self.rope_parameters
            assert self.rope_parameters['full_attention']['rope_theta'] == 1000000
        @classmethod
        def from_pretrained(cls, source, revision):
            config = cls()
            config.layer_types = ['conv', 'full_attention', 'conv', 'sliding_attention']
            config.rope_parameters = {'rope_theta': 10000,
                'full_attention': {'rope_theta': 1000000, 'partial_rotary_factor': .5},
                'sliding_attention': {'rope_theta': 10000}}
            config.standardize_rope_params()
            config.layer_types = ['linear_attention' if layer == 'conv' else layer for layer in config.layer_types]
            return config
    with patch('transformers.dynamic_module_utils.get_class_from_dynamic_module', return_value=Config):
        config = load_config('source', 'revision')
    assert config.layer_types == ['conv', 'full_attention', 'conv', 'sliding_attention']
    assert config.rope_parameters['full_attention'] == {'rope_theta': 1000000, 'partial_rotary_factor': .5}


def test_shared_input_and_output_reservation_prevents_calls_beyond_context():
    async def run():
        router, local = setup('api')
        local.count_input_tokens = AsyncMock(return_value=262140)
        with patch('model_router.complete', AsyncMock()) as api:
            with pytest.raises(ModelResponseError, match='Shared context limit'):
                await router.complete('instructions', {}, 10, Budget({'calls': 5}))
        api.assert_not_awaited()
        local.complete.assert_not_awaited()
        router.decisions.predict.assert_not_awaited()
    asyncio.run(run())


def test_local_long_input_prefill_keeps_all_tokens_and_checks_context(monkeypatch):
    import torch
    from transformers import BatchEncoding
    local = LFM3()
    local.tokenizer = Mock()
    inputs = BatchEncoding({'input_ids': torch.ones((1, 5000), dtype=torch.long),
                            'attention_mask': torch.ones((1, 5000), dtype=torch.long)})
    local.tokenizer.apply_chat_template.return_value = inputs
    local.tokenizer.eos_token_id = 2
    local.tokenizer.pad_token_id = 0
    local.tokenizer.decode.return_value = '{"text":"ok"}'
    local.model = Mock()
    local.model.device = 'cpu'
    local.model.config.max_position_embeddings = 262144
    local.model.generation_config.eos_token_id = 2
    local.model.return_value = SimpleNamespace(past_key_values='cache')
    local.model.generate.return_value = torch.cat([inputs['input_ids'], torch.tensor([[7, 2]])], dim=1)
    local._format_filter = Mock(return_value=lambda batch, ids: [2])
    monkeypatch.setattr('local_model.model_dependencies', lambda *names: (torch,))
    source = 'Original evidence preserved'
    assert local._generate(source, {'question': 'A'}, 32768) == '{"text":"ok"}'
    assert [call.kwargs['input_ids'].shape[-1] for call in local.model.call_args_list] == [2048, 2048]
    kwargs = local.model.generate.call_args.kwargs
    assert kwargs['input_ids'].shape[-1] == 5000 and kwargs['logits_to_keep'] == 1
    assert kwargs['max_new_tokens'] == 32768
    messages = local.tokenizer.apply_chat_template.call_args.args[0]
    assert messages[0]['content'] == source
    monkeypatch.setenv('MODEL_CONTEXT_TOKENS', '4096')
    with pytest.raises(ModelResponseError, match='context limit'):
        local._generate(source, {}, 100)


def test_local_warmup_reused_and_invalid_json_is_request_failure():
    async def run():
        local = LFM3()
        local._generate = Mock(return_value='{"text":"ok"}')
        await local.warmup()
        await local.warmup()
        assert local._generate.call_count == 1
        assert await local.complete("instructions", {}, 10) == {"text": "ok"}
        local._generate.return_value = "bad JSON"
        with pytest.raises(ModelResponseError):
            await local.complete("instructions", {}, 10)
        assert local.ready and not local.failed
    asyncio.run(run())


def test_local_answer_reminds_task_after_context_without_rewriting_request():
    local = LFM3()
    local.tokenizer = Mock()
    payload = {'question': 'các biện pháp phòng ngừa covid 19', 'language': 'vi'}
    original = dict(payload)
    local._encode('policy\n[skill:visualise]\nOriginal source', payload, 'answer_generation')
    messages = local.tokenizer.apply_chat_template.call_args.args[0]
    user = messages[-1]['content']
    assert user.startswith(json.dumps(payload, ensure_ascii=False))
    assert 'MỖI hành động là MỘT section' in user and 'checklist' in user
    assert 'Original source' in messages[0]['content'] and payload == original
    local._encode('policy', payload, 'planning')
    assert local.tokenizer.apply_chat_template.call_args.args[0][-1]['content'] == json.dumps(payload, ensure_ascii=False)


def test_local_timeout_does_not_reload_or_overlap_workers(monkeypatch):
    async def run():
        local = LFM3()
        local.ready = True
        release = asyncio.Event()
        async def worker(*args):
            await release.wait()
            return '{}'
        monkeypatch.setattr(asyncio, 'to_thread', worker)
        monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', '.01')
        with pytest.raises(LocalModelUnavailable):
            await local.complete("instructions", {}, 10)
        assert local.failed
        with pytest.raises(LocalModelUnavailable):
            await local.complete("instructions", {}, 10)
        release.set()
        await local.task
    asyncio.run(run())


def test_startup_waits_for_lfm3_and_survives_failure():
    import main
    async def run(fail):
        started, release = asyncio.Event(), asyncio.Event()
        async def warmup():
            started.set()
            await release.wait()
            if fail:
                raise LocalModelUnavailable()
        local = SimpleNamespace(warmup=AsyncMock(side_effect=warmup), ready=False, failed=fail)
        store = SimpleNamespace(refresh=Mock(), warmup=Mock(), close=Mock())
        app = SimpleNamespace(state=SimpleNamespace())
        with patch('main.LFM3', return_value=local), \
             patch('main.GraphKnowledge', return_value=SimpleNamespace(store=store)), \
             patch('main.QwenReranker.warmup', AsyncMock()), \
             patch('main.DocumentJobs', return_value=SimpleNamespace(close=AsyncMock())), \
             patch('main.build_store', Mock()):
            lifecycle = main.lifespan(app)
            startup = asyncio.create_task(lifecycle.__aenter__())
            await started.wait()
            assert not startup.done()
            release.set()
            await startup
            assert app.state.model_router.local is local
            assert app.state.model_router.decisions is app.state.internet.decisions
            await lifecycle.__aexit__(None, None, None)
    asyncio.run(run(False))
    asyncio.run(run(True))
