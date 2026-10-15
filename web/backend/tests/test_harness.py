import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from harness import Harness, Budget, BudgetExceeded, PROFILES, grounded
from internet import Internet, Decisions, public_url


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch):
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', inline)


def request(route='auto', effort='low', ask_user=True):
    message = SimpleNamespace(content='Thông tin về A?', model_dump=lambda: {'role':'user','content':'Thông tin về A?'})
    return SimpleNamespace(messages=[message],route=route,effort=effort,ask_user=ask_user)

PLAN = {'language':'vi','question':'A','steps':['A','B'],'queries':['A']}
FACTS = [{'id':1,'subject':'A','predicate':'relates','object':'B','source_verified':True,'source':'A liên quan B.'}]
GOOD = {'supported':True,'sections':[{'text':'A liên quan B.','citations':[1]}],
        'checks':[{'step':0,'sufficient':True,'citations':[1]},{'step':1,'sufficient':True,'citations':[1]}]}


def harness(internet=None, facts=FACTS, reranker=None):
    graph=SimpleNamespace(refresh=lambda:None,retrieve=lambda queries:facts)
    async def rank(question, evidence, budget):
        budget.take()
        return evidence
    internet = internet or SimpleNamespace(search=AsyncMock(),filter=AsyncMock())
    async def verify(state, questions, budget):
        budget.take()
        return {key: {'choice': 'supported', 'probabilities': {'supported': 1., 'contradicted': 0., 'unknown': 0.}} for key in questions}
    internet.decisions = getattr(internet, 'decisions', SimpleNamespace())
    internet.decisions.predict = AsyncMock(side_effect=verify)
    return Harness(graph,None,'','','',internet,
                   reranker or SimpleNamespace(rerank=AsyncMock(side_effect=rank)))


def test_grounding_rejects_missing_hop_and_forged_ids():
    assert grounded(GOOD,FACTS,PLAN['steps'])
    assert not grounded({**GOOD,'checks':GOOD['checks'][:1]},FACTS,PLAN['steps'])
    assert not grounded({**GOOD,'sections':[{'text':'X','citations':[99]}]},FACTS,PLAN['steps'])
    assert not grounded({**GOOD,'sections':[{'text':'X','citations':[True]}]},FACTS,PLAN['steps'])


def test_graph_and_clarification():
    async def run():
        with patch('harness.complete',AsyncMock(side_effect=[PLAN,GOOD])):
            result=await harness().run(request())
            assert result['route']=='graph' and '#cite-1' in result['answer']
            assert result['usage']['model_calls']==3
        with patch('harness.complete',AsyncMock(return_value=PLAN)):
            result=await harness(facts=[]).run(request())
            assert result['route']=='clarification' and result['reason']=='graph_insufficient'
    asyncio.run(run())


def test_web_and_repeated_query_stop():
    async def run():
        docs=[{'url':'https://example.com','title':'A','text':'A relates B'}]
        internet=SimpleNamespace(search=AsyncMock(return_value=docs),filter=AsyncMock(return_value=docs))
        with patch('harness.complete',AsyncMock(side_effect=[PLAN,GOOD])):
            result=await harness(internet,facts=[]).run(request('web'))
            assert result['route']=='web' and result['citations'][0]['kind']=='web'
        bad={'supported':False,'next_queries':['A']}
        with patch('harness.complete',AsyncMock(side_effect=[PLAN,bad,bad])):
            result=await harness(internet,facts=[]).run(request('web','high'))
            assert result['route']=='clarification'
            assert result['usage']['model_calls']<=PROFILES['high']['calls']
    asyncio.run(run())


def test_budget_and_private_url():
    budget=Budget({'calls':1}); budget.take()
    with pytest.raises(BudgetExceeded): budget.take()
    async def run():
        with pytest.raises(ValueError): await public_url('http://127.0.0.1/private')
        with pytest.raises(ValueError): await public_url('file:///etc/passwd')
    asyncio.run(run())


def test_jev_contract_and_filter(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY','test-secret')
    async def run():
        def transport(req):
            import json
            body=json.loads(req.content)
            assert body['model']=='jev-latest' and req.url.path=='/v1/systemone'
            return httpx.Response(200,json={'answers':{key:{'choice':'direct','probabilities':{'direct':.9,'context':.08,'irrelevant':.02}} for key in body['questions']}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            internet=Internet(client); 
            result=await internet.filter('A',[{'url':'https://example.com','title':'A','text':'Concrete evidence for A with detail and a meaningful source statement.'}],Budget(PROFILES['low']))
            assert len(result)==1 and result[0]['decision_score']==.9
    asyncio.run(run())


def test_full_multi_hop_is_not_dropped_at_low_effort():
    async def run():
        plan={**PLAN,'steps':['A','B','C','D']}
        with patch('harness.complete',AsyncMock(side_effect=[plan,GOOD])):
            result=await harness().run(request())
            assert result['route']=='clarification'
    asyncio.run(run())


def test_deadline_returns_bounded_clarification(monkeypatch):
    async def slow(*args,**kwargs):
        await asyncio.sleep(.1)
    monkeypatch.setitem(PROFILES,'test',{'rounds':1,'documents':1,'calls':2,'seconds':.01})
    async def run():
        with patch('harness.complete',slow):
            result=await harness().run(request(effort='test'))
            assert result['reason']=='budget_exhausted' and result['usage']['model_calls']==1
    asyncio.run(run())


def test_fastapi_sse_metadata_and_validation():
    import main
    async def run():
        with patch('main.build_store', return_value={}):
            await check()
    async def check():
        async with main.lifespan(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
                health=(await client.get('/api/health')).json()
                assert 'decision_model' in health and 'TYPESAFE_API_KEY' not in str(health)
                assert health['reranker_model'] == 'Qwen/Qwen3-Reranker-0.6B'
                assert health['skill_profile']['enabled'] is True
                assert len(health['skill_profile']['available']) == 8
                assert len(health['skill_profile']['fingerprint']) == 64
                assert (await client.post('/api/chat',json={'messages':[{'role':'user','content':'A'}],'effort':'unlimited'})).status_code==422
                assert (await client.post('/api/chat',json={'messages':[{'role':'user','content':'A'}],'route':'unknown'})).status_code==422
                with patch('main.Harness.run',AsyncMock(return_value={'answer':'A','citations':[],'route':'graph','usage':{}})) as run:
                    for route in ['auto', 'graph', 'web', 'hybrid']:
                        response=await client.post('/api/chat',json={'messages':[{'role':'user','content':'A'}], 'route':route})
                        assert response.status_code==200 and run.call_args.args[0].route == route
                        assert '"type": "result"' in response.text and '"type": "done"' in response.text
    asyncio.run(run())


def test_definition_beyond_navigation_and_old_page_cap():
    question = 'y học cổ truyền là gì ?'
    navigation = '\n\n'.join('[Y học cổ truyền](https://example.com/category) · [Menu](https://example.com/menu)' for _ in range(220))
    definition = 'Y học cổ truyền là hệ thống kiến thức và thực hành chăm sóc sức khỏe được tích lũy và truyền lại qua nhiều thế hệ.'
    text = navigation + '\n\n' + definition
    assert len(navigation) > 12000
    excerpts = Internet.excerpts(question, text)
    assert any(definition in part for part in excerpts)
    assert len(excerpts) <= 3 and all(part in text and len(part) <= 1200 for part in excerpts)


def test_low_effort_filters_three_sources_in_one_decision_batch():
    async def run():
        docs = [{'url':f'https://example.com/{i}', 'title':str(i), 'text': 'Some substantive content about the requested topic with enough detail for evaluation.'} for i in range(3)]
        internet = Internet(None)
        budget = Budget(PROFILES['low']); budget.take()  # planner
        async def predict(states, questions, budget):
            budget.take()
            assert all(set(state) == {'query', 'text'} for state in states)
            return [{k:{'choice':'direct','probabilities':{'direct':.9,'context':.08,'irrelevant':.02}} for k in questions} for state in states]
        internet.decisions.predict_batch = AsyncMock(side_effect=predict)
        result = await internet.filter('topic', docs, budget)
        assert len(result) == 3 and internet.decisions.predict_batch.await_count == 1
        assert budget.calls == 2
    asyncio.run(run())


def test_decision_false_negative_still_requires_final_evidence_check():
    async def run():
        internet = Internet(None)
        internet.decisions.predict_batch = AsyncMock(return_value=[{'relevance': {'choice':'irrelevant','probabilities':{'direct':.1,'context':.2,'irrelevant':.7}}}])
        text = 'The source contains a relevant definition with enough original detail for evidence checking.'
        result = await internet.filter('definition',[{'url':'https://example.com','title':'source','text':text}],Budget(PROFILES['low']))
        assert result[0]['text'] == text and result[0]['decision_uncertain'] is True
        internet.search = AsyncMock(return_value=result)
        with patch('harness.complete',AsyncMock(side_effect=[PLAN,{'supported':False}])):
            response = await harness(internet,facts=[]).run(request('web'))
            assert response['route']=='clarification' and not response['citations']
    asyncio.run(run())


def test_search_starts_with_actual_question_not_planner_rewording():
    async def run():
        internet = SimpleNamespace(search=AsyncMock(return_value=[]),filter=AsyncMock(return_value=[]))
        plan = {**PLAN,'question':'y học cổ truyền là gì ?', 'steps':['Cần biết định nghĩa trước khi theo học']}
        with patch('harness.complete',AsyncMock(return_value=plan)):
            await harness(internet,facts=[]).run(request('web'))
        assert internet.search.call_args.args[0][0] == plan['question']
    asyncio.run(run())


def test_reader_preserves_late_content_for_excerpt_selection(monkeypatch):
    monkeypatch.delenv('CRAWL4AI_URL',raising=False)
    async def run():
        text = 'navigation\n\n' * 1600 + 'Y học cổ truyền là một hệ thống tri thức được truyền lại qua nhiều thế hệ.'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,text=text))) as client:
            result=await Internet(client).read('https://example.com')
            assert 'Y học cổ truyền là' in result
    asyncio.run(run())


def test_mixed_decision_labels_cannot_delete_definition():
    async def run():
        internet=Internet(None)
        definition='Y học cổ truyền là một hệ thống kiến thức và thực hành chăm sóc sức khỏe được tích lũy qua nhiều thế hệ.'
        context='Y học cổ truyền có lịch sử lâu đời và được giảng dạy trong một số chương trình đào tạo chuyên ngành.'
        text=definition+'\n\n'+context
        internet.decisions.predict_batch=AsyncMock(return_value=[
            {'relevance':{'choice':'irrelevant','probabilities':{'direct':.1,'context':.2,'irrelevant':.7}}},
            {'relevance':{'choice':'context','probabilities':{'direct':.2,'context':.6,'irrelevant':.2}}},
        ])
        result=await internet.filter('y học cổ truyền là gì ?', [{'url':'https://example.com','title':'source','text':text}],Budget(PROFILES['low']))
        assert definition in result[0]['text']
    asyncio.run(run())


def test_cited_definition_is_not_mistaken_for_navigation():
    question='y học cổ truyền là gì ?'
    nav='\n\n'.join('[Y học cổ truyền](https://example.com/menu) · [Menu](https://example.com)' for _ in range(20))
    definition='Y học cổ truyền là hệ thống kiến thức và thực hành chăm sóc sức khỏe được tích lũy qua nhiều thế hệ. '
    references=' '.join(f'[Nguồn {i}](https://example.com/y-hoc-co-truyen/source-{i})' for i in range(6))
    text=nav+'\n\n'+definition+references+'\n\n'+ 'Y học cổ truyền tại một khu chợ và vài thông tin về ngành học.'
    parts=Internet.excerpts(question,text)
    assert any(definition in part for part in parts)


def test_token_usage_sums_reported_api_calls_without_inventing_counts():
    from graph_chat import complete
    async def run():
        budget=Budget(PROFILES['low'])
        budget.take()
        assert budget.report()['input_tokens'] is None
        response={'data':{'choices':[{'finish_reason':'stop','message':{'content':'{"supported": false}'}}],
            'usage':{'prompt_tokens':120,'completion_tokens':17}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,json=response))) as client:
            await complete(client,'https://example.com','test','model','system',{},usage_callback=budget.record_usage)
        budget.take()
        budget.record_usage({'input_tokens':30,'output_tokens':4})
        usage=budget.report()
        assert usage['input_tokens']==150 and usage['output_tokens']==21
        assert usage['token_usage_partial'] is False
        budget.record_usage({'input_tokens':True,'output_tokens':2})
        assert budget.report()['input_tokens']==150
    asyncio.run(run())


def test_small_graph_pool_skips_reranking_and_never_searches():
    async def run():
        internet = SimpleNamespace(search=AsyncMock(), filter=AsyncMock())
        app = harness(internet)
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])) as llm:
            response = await app.run(request('graph'))
        app.reranker.rerank.assert_not_awaited()
        internet.search.assert_not_awaited()
        internet.filter.assert_not_awaited()
        assert llm.call_args.args[5]['evidence'][0]['kind'] == 'graph'
        assert response['route'] == 'graph'
    asyncio.run(run())


def test_only_internet_never_reads_graph_or_calls_qwen():
    async def run():
        docs = [{'url': 'https://example.com', 'title': 'A', 'text': 'A relates B'}]
        internet = SimpleNamespace(search=AsyncMock(return_value=docs), filter=AsyncMock(return_value=docs))
        app = harness(internet)
        app.knowledge.refresh = lambda: pytest.fail('Web route accessed graph')
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])):
            response = await app.run(request('web'))
        app.reranker.rerank.assert_not_awaited()
        assert response['route'] == 'web'
    asyncio.run(run())


def test_low_effort_hybrid_merges_and_reserves_independent_verification():
    async def run():
        docs = [{'url': 'https://example.com', 'title': 'B', 'text': 'B is supported by a separate source containing substantive evidence.'}]
        internet = Internet(None)
        internet.search = AsyncMock(return_value=docs)
        async def predict(states, questions, budget):
            budget.take()
            return [{'relevance': {'choice': 'direct', 'probabilities': {'direct': .9, 'context': .08, 'irrelevant': .02}}} for state in states]
        internet.decisions.predict_batch = AsyncMock(side_effect=predict)
        app = harness(internet)
        async def rank(question, evidence, budget):
            budget.take()
            assert {fact['kind'] for fact in evidence} == {'graph', 'web'}
            return list(reversed(evidence))  # Citation IDs must follow final order.
        app.reranker.rerank = AsyncMock(side_effect=rank)
        supported = {'supported': True, 'sections': [{'text': 'Both sources support A and B.', 'citations': [1, 2]}],
                     'checks': [{'step': 0, 'sufficient': True, 'citations': [2]}, {'step': 1, 'sufficient': True, 'citations': [1]}]}
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, supported])) as llm:
            result = await app.run(request('hybrid'))
        assert result['route'] == 'mixed'
        assert result['usage']['model_calls'] == 4
        assert {fact['kind'] for fact in result['citations']} == {'graph', 'web'}
        assert [fact['id'] for fact in result['citations']] == [1, 2]
        assert llm.await_count == 2  # No graph-only early answer.
        internet.search.assert_awaited_once()
        app.reranker.rerank.assert_not_awaited()
    asyncio.run(run())


def test_hybrid_missing_hop_remains_unsupported():
    async def run():
        docs = [{'url': 'https://example.com', 'title': 'A', 'text': 'A relates B'}]
        internet = SimpleNamespace(search=AsyncMock(return_value=docs), filter=AsyncMock(return_value=docs))
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, {**GOOD, 'checks': GOOD['checks'][:1]}])):
            result = await harness(internet).run(request('hybrid'))
        assert result['reason'] == 'evidence_insufficient' and result['citations'] == []
    asyncio.run(run())


def test_hybrid_second_round_reranks_full_pool_with_unique_ids():
    async def run():
        first = [{'url': 'https://example.com/a', 'title': 'A', 'text': 'First source'}]
        second = [{'url': 'https://example.com/b', 'title': 'B', 'text': 'Second source'}]
        internet = SimpleNamespace(search=AsyncMock(side_effect=[first, second]),
                                   filter=AsyncMock(side_effect=[first, second]))
        app = harness(internet)
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, {'supported': False, 'next_queries': ['missing B']}, GOOD])) as llm:
            result = await app.run(request('hybrid', 'medium'))
        assert result['rounds'] == 2 and app.reranker.rerank.await_count == 0
        evidence = llm.call_args.args[5]['evidence']
        assert [fact['id'] for fact in evidence] == [1, 2, 3]
        assert {fact.get('url') for fact in evidence if fact['kind'] == 'web'} == {'https://example.com/a', 'https://example.com/b'}
    asyncio.run(run())


def test_qwen_failure_preserves_retrieval_and_requires_answer_verification():
    from reranking import RerankerUnavailable
    async def run():
        reranker = SimpleNamespace(rerank=AsyncMock(side_effect=RerankerUnavailable()))
        facts = [{**FACTS[0], 'record_id': str(i), 'document': str(i)} for i in range(11)]
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])) as llm:
            app = harness(reranker=reranker, facts=facts)
            result = await app.run(request('graph'))
        assert result['verification_status'] == 'verified' and result['citations']
        assert llm.await_count == 2 and app.internet.decisions.predict.await_count == 1
    asyncio.run(run())
