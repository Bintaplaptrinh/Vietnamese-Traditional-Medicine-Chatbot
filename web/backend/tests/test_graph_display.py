"""Complete graph browsing must not silently omit data or mix snapshots."""
import asyncio
import json

import httpx
import pytest

from knowledge_store import KnowledgeStore, add_concept, connect, schema


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('knowledge_store.DATA', tmp_path)
    (tmp_path / 'current.json').write_text(json.dumps({'snapshot': 'fixture'}))
    db = connect(tmp_path / 'fixture.sqlite')
    schema(db)
    # More than the old 80-edge cap and 12-search-seed cap, plus isolated nodes.
    for i in range(211):
        add_concept(db, f'g{i}', 'graph', f'Common concept {i}')
    add_concept(db, 'm0', 'mesh', 'Common other branch')
    for i in range(179):
        db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?)', (
            f'e{i}', 'graph', f'g{i}', 'urn:predicate#relates', f'g{i + 1}',
            json.dumps({'review_status': 'pending', 'source': f'quote {i}', 'page': i + 1})))
    # Parallel and self edges remain distinct, with their evidence intact.
    for key, subject, obj in [('parallel', 'g0', 'g1'), ('self', 'g0', 'g0')]:
        db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?)', (key, 'graph', subject, 'relates', obj, '{}'))
    db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?)', ('mesh-edge', 'mesh', 'm0', 'relates', 'm0', '{}'))
    db.commit(); db.close()
    return KnowledgeStore()


def collect_pages(store, branch='graph', query='', limit=31):
    result = {'nodes': [], 'edges': []}
    cursor = {}
    while True:
        page = store.graph(branch, query, limit, **cursor)
        result['nodes'].extend(page['nodes']); result['edges'].extend(page['edges'])
        assert len(page['nodes']) <= limit and len(page['edges']) <= limit
        assert page['limited'] == bool(page['next'])
        if not page['next']:
            return result
        cursor = {**page['next'], 'snapshot': page['snapshot']}


def test_full_graph_includes_every_node_and_edge(store):
    full = store.graph()
    assert full['total_nodes'] == len(full['nodes']) == 211
    assert full['total_edges'] == len(full['edges']) == 181
    assert not full['limited'] and full['next'] is None
    assert any(node['id'] == 'g210' for node in full['nodes'])  # isolated
    assert all(node['branch'] == 'graph' for node in full['nodes'])
    first = full['edges'][0]
    assert first['source'] == 'quote 0' and first['page'] == 1
    assert first['from'] == 'g0' and first['to'] == 'g1'
    assert first['label'] == 'relates' and first['review_status'] == 'pending'
    paged = collect_pages(store)
    assert paged['nodes'] == full['nodes'] and paged['edges'] == full['edges']


def test_search_has_no_seed_cap_and_keeps_branch_scope(store):
    result = collect_pages(store, query='Common', limit=17)
    assert len(result['nodes']) == 211 and len(result['edges']) == 181
    assert not store.graph(query='nonexistent')['nodes']
    assert not store.graph(query='!!!')['nodes']
    assert len(store.graph('mesh', 'Common')['nodes']) == 1
    assert [edge['id'] for edge in store.graph('mesh', 'Common')['edges']] == ['mesh-edge']


def test_exact_page_boundary_has_no_false_truncation(store):
    page = store.graph('mesh', limit=1)
    assert len(page['nodes']) == len(page['edges']) == 1
    assert not page['limited'] and page['next'] is None


def test_snapshot_change_requires_restart(store):
    with pytest.raises(ValueError, match='graph_snapshot_changed'):
        store.graph(limit=31, snapshot='older')


def test_graph_api_paging_and_validation(store, monkeypatch):
    import main
    from types import SimpleNamespace
    monkeypatch.setattr(main.app.state, 'knowledge', SimpleNamespace(store=store), raising=False)
    monkeypatch.setattr(main.app.state, 'index_status', 'ready', raising=False)
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', inline)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            page = (await client.get('/api/graph?limit=31')).json()
            assert page['total_nodes'] == 211 and page['next']
            response = await client.get('/api/graph', params={**page['next'], 'limit': 31, 'snapshot': page['snapshot']})
            assert response.status_code == 200
            assert not {n['id'] for n in page['nodes']} & {n['id'] for n in response.json()['nodes']}
            assert (await client.get('/api/graph?snapshot=older')).status_code == 409
            for query in ['limit=0', 'limit=10001', 'after_node=-1', 'branch=unknown']:
                assert (await client.get('/api/graph?' + query)).status_code == 422
            assert len((await client.get('/api/graph')).json()['nodes']) == 211
    asyncio.run(run())
