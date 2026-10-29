import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from graph_chat import ModelResponseError, complete, thinking_options


def test_deepseek_v4_disables_thinking_for_api_and_gateway(monkeypatch):
    monkeypatch.delenv('FPT_ENABLE_THINKING', raising=False)
    assert thinking_options('DeepSeek-V4-Flash') == {
        'thinking': {'type': 'disabled'}, 'chat_template_kwargs': {'thinking': False}}


@pytest.mark.parametrize('model, setting, expected', [
    ('gemma-4-31B-it', None, False),
    ('google/gemma-4-31B-it', '1', True),
    ('another-model', None, None),
])
def test_bounded_gemma_json_calls_disable_thinking_by_default(monkeypatch, model, setting, expected):
    monkeypatch.delenv('FPT_ENABLE_THINKING', raising=False)
    if setting is not None:
        monkeypatch.setenv('FPT_ENABLE_THINKING', setting)

    def transport(request):
        body = json.loads(request.content)
        if expected is None:
            assert 'chat_template_kwargs' not in body
        else:
            assert body['chat_template_kwargs'] == {'enable_thinking': expected}
        assert body['max_tokens'] == 3000
        return httpx.Response(200, json={'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"supported": false}'}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            assert await complete(client, 'https://example.com', 'key', model, 'system', {}) == {'supported': False}
    asyncio.run(run())


@pytest.mark.parametrize('body', [
    [], {'data': None}, {'choices': None}, {'choices': [None]},
    {'choices': [{'message': None}]},
    {'choices': [{'message': {'content': 'ordinary text'}}]},
    {'choices': [{'finish_reason': 'length', 'message': {'content': '{"supported":'}}]},
])
def test_invalid_completions_have_a_model_error(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body))) as client:
            with pytest.raises(ModelResponseError):
                await complete(client, 'https://example.com', 'key', 'model', 'system', {})
    asyncio.run(run())


def test_chat_identifies_model_errors_and_logs_failed_stage(monkeypatch, caplog):
    import main
    monkeypatch.setenv('FPT_API_KEY', 'test')

    async def run():
        runner = AsyncMock()
        runner.trace = {'stage': 'answer_generation'}
        runner.run.side_effect = ModelResponseError('Invalid completion')
        with patch('main.Harness', return_value=runner):
            # Exercise the real SSE handler without warming local models.
            response = await main.chat(main.ChatRequest(
                messages=[main.Message(role='user', content='cách điều trị thoái hóa cột sống')], route='graph'))
            events = ''.join([chunk async for chunk in response.body_iterator])
        assert 'invalid_model_response' in events
        assert 'Mô hình trả về' in events
        assert 'đồ thị tri thức' not in events
        assert 'answer_generation' in caplog.text
        assert 'ModelResponseError' in caplog.text

    # The handler only needs these dependencies when constructing the harness.
    for name in ('knowledge', 'client', 'internet', 'reranker', 'skills', 'model_router'):
        monkeypatch.setattr(main.app.state, name, None, raising=False)
    asyncio.run(run())
