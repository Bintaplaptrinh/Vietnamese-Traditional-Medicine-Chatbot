import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest

from harness import Budget, PROFILES
from internet import Decisions
from reranking import GRAPH_TOP_K, QwenReranker, RerankerUnavailable


@pytest.fixture(autouse=True)
def inline_model_stubs(monkeypatch):
    # Model stubs need no native worker; sandbox blocks asyncio's socket wakeups.
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', inline)


def test_qwen_joint_scores_preserve_web_sources_and_graph_metadata():
    async def run():
        graph = [{'id': i + 1, 'kind': 'graph', 'subject': str(i), 'predicate': 'relates',
                  'object': 'B', 'source': 'graph.json', 'inferred': True} for i in range(12)]
        web = [{'kind': 'web', 'url': 'https://example.com', 'title': 'A',
                'text': 'First excerpt\n\nSecond excerpt', 'decision_score': .1}]
        reranker = QwenReranker()
        def score(question, texts):
            assert '"inferred": true' in texts[0] and 'graph.json' in texts[0]
            assert texts[-2:] == ['First excerpt', 'Second excerpt']
            return [.2 + i / 100 for i in range(12)] + [.01, .99]
        reranker._score = Mock(side_effect=score)
        budget = Budget(PROFILES['low'])
        ranked = await reranker.rerank('A', graph + web, budget)
        assert ranked[0]['kind'] == 'web' and ranked[0]['rerank_score'] == .99
        assert len(ranked) == 13 and budget.calls == 1
        assert [fact['subject'] for fact in ranked[1:]] == [str(i) for i in range(11, -1, -1)]
        assert all(fact['inferred'] and fact['source'] == 'graph.json' for fact in ranked[1:])
        assert 'rerank_score' not in graph[0]
    asyncio.run(run())


@pytest.mark.parametrize('scores', [[float('nan')], [float('inf')], [-.1], [1.1], [True], []])
def test_qwen_invalid_scores_fail_closed(scores):
    async def run():
        reranker = QwenReranker()
        reranker._score = Mock(return_value=scores)
        with pytest.raises(RerankerUnavailable):
            await reranker.rerank('A', [{'kind': 'graph', 'subject': 'A'}], Budget(PROFILES['low']))
    asyncio.run(run())


def test_qwen_timeout_does_not_launch_a_second_worker(monkeypatch):
    monkeypatch.setenv('QWEN_RERANKER_TIMEOUT_SECONDS', '.01')
    async def run():
        reranker = QwenReranker()
        reranker._score = Mock(return_value=[.9])
        async def slow_worker(function, *args):
            await asyncio.sleep(.05)
            return function(*args)
        monkeypatch.setattr(asyncio, 'to_thread', slow_worker)
        evidence = [{'kind': 'graph', 'subject': 'A'}]
        with pytest.raises(RerankerUnavailable):
            await reranker.rerank('A', evidence, Budget(PROFILES['low']))
        with pytest.raises(RerankerUnavailable):
            await reranker.rerank('A', evidence, Budget(PROFILES['low']))
        await asyncio.sleep(.06)
        assert reranker._score.call_count == 1
    asyncio.run(run())


def test_jev_batches_isolated_excerpts_in_one_remote_call(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-key')
    async def run():
        import json
        def transport(request):
            body = json.loads(request.content)
            assert body['model'] == 'jev-latest'
            assert body['state']['chunks'] == {'0': 'First', '1': 'Second'}
            assert set(body['questions']) == {'0:relevance', '1:relevance'}
            assert 'only chunks.1' in body['questions']['1:relevance']['instructions']
            return httpx.Response(200, json={'answers': {key: {'choice': 'context',
                'probabilities': {'direct': .2, 'context': .7, 'irrelevant': .1}} for key in body['questions']}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            decisions = Decisions(client)
            budget = Budget(PROFILES['low'])
            results = await decisions.predict_batch([{'query': 'A', 'text': 'First'}, {'query': 'A', 'text': 'Second'}],
                {'relevance': {'instructions': 'Evaluate text.', 'criteria': {'direct': '', 'context': '', 'irrelevant': ''}}}, budget)
            assert len(results) == 2 and results[1]['relevance']['choice'] == 'context'
            assert budget.calls == 1 and budget.api_calls == 1
    asyncio.run(run())
