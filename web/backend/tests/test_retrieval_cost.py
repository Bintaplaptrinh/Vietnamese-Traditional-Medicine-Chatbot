import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from evidence import mask_evidence, pack_evidence
from harness import Budget, Harness, PROFILES
from retrieval import excerpt, lexical_shortlist, source_candidates
from test_harness import harness, request, PLAN, GOOD, inline_workers


def test_graph_uses_local_search_then_bounded_reranking_and_one_generation():
    async def run():
        facts = [{'record_id': str(i), 'kind': 'text', 'branch': 'graph', 'document': f'{i}.pdf',
                  'text': ('Điều trị thoái hóa cột sống được khảo sát trong tài liệu. ' * 90),
                  'retrieval_score': i / 100, 'evidence_ids': ['INTERNAL_PROVENANCE'] * 1000}
                 for i in range(60)]
        app = harness(facts=facts)
        app.planner = 'lexical'
        app.knowledge.retrieve = Mock(return_value=facts)
        req = request('graph')
        req.messages[0].content = 'cách điều trị thoái hóa cột sống'

        async def rerank(question, candidates, budget):
            assert len(candidates) <= PROFILES['low']['candidate_k']
            assert all(len(f['text']) <= PROFILES['low']['snippet_chars'] for f in candidates)
            budget.take(local=True)
            return list(reversed(candidates))
        app.reranker.rerank = AsyncMock(side_effect=rerank)
        with patch('harness.complete', AsyncMock(return_value=GOOD)) as llm:
            result = await app.run(req)
        assert llm.await_count == 1
        assert app.trace['planner_mode'] == 'lexical'
        app.knowledge.retrieve.assert_called_once_with([req.messages[0].content])
        prompt = llm.call_args.args[4]
        assert 'INTERNAL_PROVENANCE' not in prompt
        evidence = json.loads(prompt.split('UNTRUSTED RETRIEVED KNOWLEDGE JSON:\n', 1)[1])
        assert len(evidence) <= PROFILES['low']['top_k']
        assert len(json.dumps(evidence, ensure_ascii=False)) <= PROFILES['low']['context_chars']
        assert llm.call_args.kwargs['max_tokens'] == PROFILES['low']['answer_tokens']
        assert result['usage']['api_calls'] == 2  # Generation + independent verification.
        assert result['usage']['local_calls'] == 1
        assert result['usage']['retrieval'][0]['retrieved_count'] == 60
        assert result['verification_status'] == 'verified'
    asyncio.run(run())


def test_empty_graph_spends_no_model_calls(monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_PLANNER', raising=False)
    async def run():
        dependencies = harness(facts=[])
        app = Harness(dependencies.knowledge, None, '', '', '', dependencies.internet, dependencies.reranker)
        with patch('harness.complete', AsyncMock()) as llm:
            result = await app.run(request('graph'))
        llm.assert_not_awaited()
        app.internet.decisions.predict.assert_not_awaited()
        assert result['reason'] == 'graph_insufficient'
        assert result['usage']['api_calls'] == 0
    asyncio.run(run())


def test_contextual_followup_can_still_resolve_history():
    async def run():
        app = harness()
        app.planner = 'lexical'
        req = request('graph')
        req.messages.append(SimpleNamespace(content='Phương pháp đó có hiệu quả không?', model_dump=lambda: {}))
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])) as llm:
            result = await app.run(req)
        assert app.trace['planner_mode'] == 'llm'
        assert llm.await_count == 2
        assert result['verification_status'] == 'verified'
    asyncio.run(run())


def test_local_bm25_ranks_specific_terms_above_generic_repetition():
    facts = [
        {'kind': 'text', 'record_id': 'decoy', 'text': 'Điều trị bệnh khác. ' * 100},
        {'kind': 'text', 'record_id': 'relevant', 'text': 'Các phương pháp điều trị thoái hóa cột sống.'},
    ]
    assert lexical_shortlist(facts, 'cách điều trị thoái hóa cột sống', limit=1)[0]['record_id'] == 'relevant'


def test_excerpts_preserve_original_negation_and_whole_sentences():
    claim = 'Nghiên cứu trên chuột chưa chứng minh hiệu quả điều trị thoái hóa cột sống ở người.'
    text = 'Nội dung không liên quan. ' * 100 + '\n' + claim + '\nPhải giữ giới hạn nghiên cứu.'
    selected, start = excerpt(text, 'điều trị thoái hóa cột sống', 250)
    assert claim in selected
    assert selected == text[start:start + len(selected)]
    assert len(selected) <= 250
    assert excerpt('x' * 1500, 'x', 1200) == ('', 0)


def test_final_selection_preserves_reranker_order_and_conflict_groups():
    facts = [{'kind': 'text', 'record_id': 'rerank-winner', 'text': 'Nguồn xếp hạng cao.'},
             {'kind': 'text', 'record_id': 'lexical-winner', 'text': 'thoái hóa cột sống'}]
    assert pack_evidence(facts, ['thoái hóa cột sống'], max_items=1, compact=True, per_step=0)[0]['record_id'] == 'rerank-winner'
    conflict = mask_evidence([{'kind': 'graph', 'source_verified': True, 'subject': 'A', 'predicate': 'has',
                              'object': obj, 'source': obj, 'document': obj} for obj in ('B', 'C')])
    assert not pack_evidence(conflict, [], max_items=1, compact=True, per_step=0)


def test_graph_edges_reuse_original_passage_with_provenance_and_conflict_flags():
    text = 'Tài liệu mô tả phối hợp điều trị bằng cả A và B.'
    facts = mask_evidence([
        {'kind': 'graph', 'source_verified': True, 'record_id': value, 'subject': 'Bệnh',
         'predicate': 'điều trị bằng', 'object': value, 'document_id': 'doc', 'text': text,
         'source': text, 'evidence_ids': ['unit']} for value in ('A', 'B')])
    facts.append({'kind': 'text', 'record_id': 'context', 'document_id': 'doc',
                  'evidence_ids': ['unit'], 'text': text + ' Không chứng minh hiệu quả ở người.'})
    selected = source_candidates(facts)
    assert len(selected) == 1
    assert selected[0]['kind'] == 'text'
    assert selected[0]['graph_record_ids'] == ['A', 'B']
    assert selected[0]['conflict_group'] == facts[0]['conflict_group']
    assert 'Không chứng minh' in selected[0]['text']


def test_verification_sends_shared_source_once_for_multiple_claims():
    async def run():
        app = harness()
        app.planner = 'lexical'
        draft = {**GOOD, 'sections': [GOOD['sections'][0], {'text': 'Another supported claim.', 'citations': [1]}]}
        with patch('harness.complete', AsyncMock(return_value=draft)):
            await app.run(request('graph'))
        state = app.internet.decisions.predict.call_args.args[0]
        assert len(state['evidence']) == 1
        assert state['claims']['0']['evidence_ids'] == state['claims']['1']['evidence_ids'] == [1]
        assert 'evidence' not in state['claims']['0']
    asyncio.run(run())


def test_reasoning_and_local_compute_usage_are_distinguished():
    budget = Budget(PROFILES['low'])
    budget.take(100, local=True)
    budget.take(50)
    budget.record_usage({'prompt_tokens': 10, 'completion_tokens': 20,
                         'completion_tokens_details': {'reasoning_tokens': 15}})
    report = budget.report()
    assert report['reasoning_tokens'] == 15
    assert report['api_input_characters'] == 50
    assert report['local_input_characters'] == 100
