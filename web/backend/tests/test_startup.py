"""Startup owns local model loading; requests reuse warmed instances."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from harness import Budget, PROFILES
from knowledge_store import KnowledgeStore
from reranking import QwenReranker, RerankerUnavailable


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch):
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', inline)


def test_qwen_warmup_is_idempotent_and_does_not_charge_request_budget():
    async def run():
        reranker = QwenReranker()
        reranker._score = Mock(return_value=[.9])
        await reranker.warmup()
        await reranker.warmup()
        assert reranker.ready and reranker._score.call_count == 1
        budget = Budget(PROFILES['low'])
        result = await reranker.rerank('A', [{'kind': 'text', 'text': 'A'}], budget)
        assert result[0]['rerank_score'] == .9
        assert budget.calls == 1 and reranker._score.call_count == 2
    asyncio.run(run())


def test_failed_warmup_does_not_reload_on_first_request():
    async def run():
        reranker = QwenReranker()
        reranker._score = Mock(side_effect=OSError('Missing model'))
        with pytest.raises(RerankerUnavailable):
            await reranker.warmup()
        with pytest.raises(RerankerUnavailable):
            await reranker.rerank('A', [{'kind': 'text', 'text': 'A'}], Budget(PROFILES['low']))
        assert reranker.failed and not reranker.ready
        assert reranker._score.call_count == 1
    asyncio.run(run())


def test_bm25_warmup_reuses_model_and_index_and_retains_model_on_snapshot_change(tmp_path, monkeypatch):
    monkeypatch.setattr('knowledge_store.DATA', tmp_path)
    def snapshot(name):
        (tmp_path / 'current.json').write_text(json.dumps({'snapshot': name, 'bm25_model': 'Qdrant/bm25'}))
        folder = tmp_path / 'bm25' / name
        folder.mkdir(parents=True)
        (folder / 'evidence.jsonl').write_text('')
    snapshot('one')
    vector = SimpleNamespace(indices=SimpleNamespace(tolist=lambda: [1]), values=SimpleNamespace(tolist=lambda: [1.]))
    model = Mock()
    model.query_embed.side_effect = lambda query: iter([vector])
    clients = [Mock(), Mock()]
    for client in clients:
        client.query_points.return_value = SimpleNamespace(points=[])
    embedding = Mock(return_value=model)
    factory = Mock(side_effect=clients)
    with patch.dict('sys.modules', {
        'fastembed': SimpleNamespace(SparseTextEmbedding=embedding),
        'qdrant_client': SimpleNamespace(QdrantClient=factory, models=Mock()),
    }):
        store = KnowledgeStore()
        store.warmup()
        store.bm25('First user query')
        assert embedding.call_count == factory.call_count == 1
        assert model.query_embed.call_count == 2
        snapshot('two')
        store.warmup()
        assert embedding.call_count == 1 and factory.call_count == 2
        clients[0].close.assert_called_once()
        store.close()
        clients[1].close.assert_called_once()


def test_application_waits_for_both_local_models_before_accepting_requests():
    import main
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        store = SimpleNamespace(refresh=Mock(), warmup=Mock(), close=Mock())
        reranker = SimpleNamespace(warmup=None)
        async def warmup():
            started.set()
            await release.wait()
        reranker.warmup = AsyncMock(side_effect=warmup)
        jobs = SimpleNamespace(close=AsyncMock())
        application = SimpleNamespace(state=SimpleNamespace())
        with patch('main.GraphKnowledge', return_value=SimpleNamespace(store=store)), \
                patch('main.QwenReranker', return_value=reranker), \
                patch('main.DocumentJobs', return_value=jobs), \
                patch('main.build_store', Mock()):
            lifecycle = main.lifespan(application)
            startup = asyncio.create_task(lifecycle.__aenter__())
            await started.wait()
            assert not startup.done(), 'Application must wait for local inference warmup'
            release.set()
            await startup
            store.warmup.assert_called_once()
            reranker.warmup.assert_awaited_once()
            await lifecycle.__aexit__(None, None, None)
            store.close.assert_called_once()
            jobs.close.assert_awaited_once()
    asyncio.run(run())


def test_application_keeps_existing_fallback_when_qwen_is_unavailable():
    import main
    async def run():
        store = SimpleNamespace(refresh=Mock(), warmup=Mock(), close=Mock())
        reranker = SimpleNamespace(warmup=AsyncMock(side_effect=RerankerUnavailable()))
        application = SimpleNamespace(state=SimpleNamespace())
        with patch('main.GraphKnowledge', return_value=SimpleNamespace(store=store)), \
                patch('main.QwenReranker', return_value=reranker), \
                patch('main.DocumentJobs', return_value=SimpleNamespace(close=AsyncMock())), \
                patch('main.build_store', Mock()):
            async with main.lifespan(application):
                store.warmup.assert_called_once()
    asyncio.run(run())
