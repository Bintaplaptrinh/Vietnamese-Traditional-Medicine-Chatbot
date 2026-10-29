import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from medical_skills import MedicalSkills, SKILLS_ROOT, VISUALISE
from test_harness import harness, request, inline_workers
from visualisation import normalize_visual, public_visual, normalize_step_draft, answer_markdown


@pytest.mark.parametrize('question, selected', [
    ('So sánh hai phương pháp', True), ('Vẽ sơ đồ các bước', True), ('Compare the two groups in a chart', True),
    ('các biện pháp phòng ngừa covid 19', True), ('Những cách giữ vệ sinh', True),
    ('List prevention measures', True), ('Các biện pháp, chỉ dùng văn bản', False),
    ('các bước làm sạch tay là gì ?', True), ('What are the cleaning steps?', True),
    ('Nhân sâm là gì?', False), ('Compare in plain text only', False), ('So sánh, chỉ dùng văn bản', False)])
def test_visual_skill_is_selected_only_for_suitable_requests(question, selected):
    assert (VISUALISE in MedicalSkills().draft(question, 'vi', []).ids) is selected


def test_upstream_visual_guides_and_license_are_pinned():
    manifest = json.loads((SKILLS_ROOT / 'manifest.json').read_text())
    upstream = manifest['visualisation_upstream']
    assert upstream['repository'] == 'https://github.com/althetinkerer/opengenerativeui'
    assert upstream['revision'] == '38e8c5e41f8f6c010bb71175a8c54081d9b7f385'
    assert hashlib.sha256((SKILLS_ROOT / upstream['license_file']).read_bytes()).hexdigest() == upstream['license_sha256']
    entry = next(row for row in manifest['skills'] if row['id'] == VISUALISE)
    assert len(entry['source_files']) == 3
    for source in entry['source_files']:
        assert hashlib.sha256((SKILLS_ROOT / source['path']).read_bytes()).hexdigest() == source['sha256']


SECTIONS = [{'text': 'Nhóm A có 12 người.', 'citations': [1]}, {'text': 'Nhóm B có 18 người.', 'citations': [1]}]
SPEC = {'kind': 'bar', 'sections': [0, 1], 'values': [12, 18], 'unit': 'người'}


@pytest.mark.parametrize('spec', [
    {'kind': 'html', 'sections': [0, 1]}, {'kind': [], 'sections': [0, 1]}, {'kind': 'cards', 'sections': [True, 1]},
    {'kind': 'cards', 'sections': [0, 0]}, {'kind': 'cards', 'sections': [1]},
    {**SPEC, 'values': [float('nan'), 18]}, {**SPEC, 'values': [-1, 18]},
    {**SPEC, 'values': [12]}, {**SPEC, 'values': [True, 18]}, {**SPEC, 'unit': []}])
def test_malformed_or_incomplete_visuals_are_ignored(spec):
    assert normalize_visual(spec, SECTIONS) is None


def test_public_visual_uses_verified_wording_and_drops_executable_fields():
    spec = normalize_visual({**SPEC, 'html': '<script>bad()</script>', 'title': 'unverified claim'}, SECTIONS)
    public = public_visual(spec, SECTIONS, 'vi')
    assert public['items'] == SECTIONS and public['values'] == [12, 18]
    assert 'html' not in public and 'title' not in public


def test_checklist_keeps_independent_actions_and_their_citations():
    sections = [{'text': 'Đeo kính bảo hộ.', 'citations': [1]}, {'text': 'Buộc tóc gọn.', 'citations': [2]}]
    spec = normalize_visual({'kind': 'checklist', 'sections': [0, 1]}, sections)
    assert public_visual(spec, sections, 'vi') == {'kind': 'checklist', 'items': sections, 'language': 'vi'}


def test_inline_steps_preserve_words_order_context_notes_and_citations():
    text = 'For trained staff only: Step 1: Open the box. Step 2: Take out the item. Note: Keep it dry.'
    draft = {'supported': True, 'sections': [{'text': text, 'citations': [1, 2]}], 'visualization': None}
    result = normalize_step_draft(draft, 'What are the steps?', visual_enabled=True)
    assert result['visualization'] == {'kind': 'steps', 'sections': [1, 2]}
    assert ' '.join(s['text'] for s in result['sections']) == text
    assert all(s['citations'] == [1, 2] for s in result['sections'])
    assert draft['sections'][0]['text'] == text and len(draft['sections']) == 1
    visual = public_visual(normalize_visual(result['visualization'], result['sections']), result['sections'], 'en')
    assert visual['context'][0]['text'] == 'For trained staff only:'
    assert visual['notes'][0]['text'] == 'Note: Keep it dry.'
    assert [s['text'] for s in visual['items']] == ['Step 1: Open the box.', 'Step 2: Take out the item.']
    answer = answer_markdown(result['sections'], result['visualization'])
    assert '\n\nStep 2:' in answer and answer.count('[1](#cite-1)') == 4
    assert '\n\nStep 2:' in answer_markdown(draft['sections'])  # Visual absent/legacy fallback.


@pytest.mark.parametrize('text', [
    'Step 1: A. Step 3: B.', 'Step 2: A. Step 3: B.',
    'Step 1: A. Step 1: B.', 'A, followed by B.', 'Step 1: Step 2: B.'])
def test_ambiguous_or_incomplete_step_runs_are_not_reinterpreted(text):
    draft = {'supported': True, 'sections': [{'text': text, 'citations': [1]}]}
    assert normalize_step_draft(draft, 'What are the steps?', True) is draft


def test_procedures_longer_than_six_steps_keep_all_steps_and_separate_notes():
    steps = [{'text': f'Step {i}: Action {i}.', 'citations': [1]} for i in range(1, 8)]
    sections = steps + [{'text': 'Note: For trained staff.', 'citations': [1], 'html': 'never expose'}]
    spec = normalize_visual({'kind': 'steps', 'sections': list(range(7))}, sections)
    visual = public_visual(spec, sections, 'en')
    assert len(visual['items']) == 7 and 'html' not in visual['notes'][0]
    assert normalize_visual({'kind': 'steps', 'sections': [1, 0]}, sections) is None
    assert normalize_visual({'kind': 'steps', 'sections': [0, 2]}, sections) is None
    assert normalize_visual({'kind': 'cards', 'sections': [0, 1]}, sections) is None
    draft = {'supported': True, 'sections': sections, 'visualization': {'kind': 'checklist', 'sections': [0, 1]}}
    recovered = normalize_step_draft(draft, 'What are the steps?', True)
    assert recovered['visualization'] == spec
    assert recovered['sections'] == sections


@pytest.mark.parametrize('text_only, visual_verdict', [(False, 'supported'), (False, 'unknown'), (True, 'supported')])
def test_packed_step_answer_has_paragraphs_with_or_without_verified_visual(text_only, visual_verdict):
    async def run():
        text = 'Bước 1: Mở hộp. Bước 2: Lấy đồ vật. Lưu ý: Giữ khô.'
        runner = harness(facts=[{'id': 1, 'kind': 'text', 'text': text, 'document': 'fixture.pdf'}])
        runner.planner = 'lexical'
        req = request('graph')
        req.messages[0].content = 'Các bước lấy đồ vật?' + (' Chỉ dùng văn bản' if text_only else '')
        async def verify(state, questions, budget):
            budget.take()
            assert state['claims']['0']['claim'] == 'Bước 1: Mở hộp.'
            assert state['claims']['1']['claim'] == 'Bước 2: Lấy đồ vật.'
            assert ('visual:0' in questions) is not text_only
            return {key: {'choice': visual_verdict if key == 'visual:0' else 'supported'} for key in questions}
        runner.internet.decisions.predict.side_effect = verify
        draft = {'supported': True, 'sections': [{'text': text, 'citations': [1]}],
                 'visualization': {'kind': 'checklist', 'sections': [0, 1]}}
        with patch('harness.complete', AsyncMock(return_value=draft)):
            result = await runner.run(req)
        assert result['verification_status'] == 'verified'
        assert '\n\nBước 2:' in result['answer'] and '\n\nLưu ý:' in result['answer']
        assert result['answer'].count('[1](#cite-1)') == 3
        if text_only or visual_verdict != 'supported':
            assert result['visualization'] is None
        else:
            assert result['visualization']['kind'] == 'steps'
            assert len(result['visualization']['items']) == 2
            assert result['visualization']['notes'][0]['text'] == 'Lưu ý: Giữ khô.'
    asyncio.run(run())


def test_removing_only_unrelated_context_keeps_and_reverifies_complete_steps():
    async def run():
        runner = harness(facts=[{'id': 1, 'kind': 'text', 'text': 'Step 1: Open. Step 2: Take out.', 'document': 'fixture.pdf'}])
        runner.planner = 'lexical'
        req = request('graph'); req.messages[0].content = 'What are the steps?'
        draft = {'supported': True, 'sections': [
            {'text': 'Unrelated background.', 'citations': [1]},
            {'text': 'Step 1: Open. Step 2: Take out.', 'citations': [1]}]}
        async def verify(state, questions, budget):
            budget.take()
            if 'claim:0' in questions:
                assert state['visualization']['sections'] == [1, 2]
                return {key: {'choice': 'unknown' if key == 'claim:0' else 'supported'} for key in questions}
            assert state['visualization']['sections'] == [0, 1] and 'visual:0' in questions
            return {key: {'choice': 'supported'} for key in questions}
        runner.internet.decisions.predict.side_effect = verify
        with patch('harness.complete', AsyncMock(return_value=draft)):
            result = await runner.run(req)
        assert result['verification_status'] == 'verified' and result['visualization']['kind'] == 'steps'
        assert 'Unrelated' not in result['answer'] and len(result['visualization']['items']) == 2
        assert runner.internet.decisions.predict.await_count == 2
    asyncio.run(run())


def test_removing_unverified_step_cannot_publish_a_partial_protocol():
    async def run():
        runner = harness(facts=[{'id': 1, 'kind': 'text', 'text': 'Step 1: Open. Step 2: Unlock. Step 3: Take out.', 'document': 'fixture.pdf'}])
        runner.planner = 'lexical'
        req = request('graph'); req.messages[0].content = 'What are the steps?'
        draft = {'supported': True, 'sections': [
            {'text': 'Step 1: Open. Step 2: Unlock. Step 3: Take out.', 'citations': [1]}]}
        async def verify(state, questions, budget):
            budget.take()
            assert 'partial protocol is insufficient' in questions['step:0']['instructions']
            if 'claim:0' in questions:
                return {key: {'choice': 'unknown' if key == 'claim:1' else 'supported'} for key in questions}
            assert state['visualization'] is None
            return {'step:0': {'choice': 'unknown'}}
        runner.internet.decisions.predict.side_effect = verify
        with patch('harness.complete', AsyncMock(return_value=draft)):
            result = await runner.run(req)
        assert result['verification_status'] == 'insufficient' and not result['citations']
    asyncio.run(run())


def test_latest_user_visual_preference_survives_planner_rewording():
    skills = MedicalSkills()
    assert VISUALISE in skills.draft('A', 'vi', [], requested_question='Vẽ sơ đồ A').ids
    assert VISUALISE not in skills.draft('So sánh A và B', 'vi', [], requested_question='Chỉ dùng văn bản').ids


def test_local_schema_requires_visual_contract_only_when_skill_is_selected():
    from local_model import response_schema
    assert 'visualization' not in response_schema('answer_generation')['required']
    assert 'visualization' in response_schema('answer_generation', visual=True)['required']


@pytest.mark.parametrize('visual_verdict', ['supported', 'unknown', 'contradicted'])
def test_visual_is_independently_verified_in_the_existing_jev_batch(visual_verdict):
    async def run():
        facts = [{'id': 1, 'kind': 'text', 'text': 'Nhóm A có 12 người. Nhóm B có 18 người.', 'document': 'fixture.pdf'}]
        runner = harness(facts=facts)
        runner.planner = 'lexical'
        req = request('graph')
        req.messages[0].content = 'So sánh số người hai nhóm bằng biểu đồ'
        async def verify(state, questions, budget):
            budget.take()
            assert state['visualization'] == SPEC
            assert 'visual:0' in questions
            return {key: {'choice': visual_verdict if key == 'visual:0' else 'supported'} for key in questions}
        runner.internet.decisions.predict.side_effect = verify
        with patch('harness.complete', AsyncMock(return_value={'supported': True, 'sections': SECTIONS, 'visualization': SPEC})):
            result = await runner.run(req)
        assert result['verification_status'] == 'verified'
        assert '[1](#cite-1)' in result['answer']
        assert (result['visualization'] is not None) is (visual_verdict == 'supported')
        runner.internet.decisions.predict.assert_awaited_once()
        assert VISUALISE in result['skills']['drafts'][0]['ids']
    asyncio.run(run())


def test_removed_claims_drop_visual_instead_of_reusing_shifted_indexes():
    async def run():
        runner = harness(facts=[{'id': 1, 'kind': 'text', 'text': 'Nhóm A có 12 người.', 'document': 'fixture.pdf'}])
        runner.planner = 'lexical'
        req = request('graph')
        req.messages[0].content = 'So sánh hai nhóm'
        async def verify(state, questions, budget):
            budget.take()
            return {key: {'choice': 'unknown' if key == 'claim:1' else 'supported'} for key in questions}
        runner.internet.decisions.predict.side_effect = verify
        with patch('harness.complete', AsyncMock(return_value={'supported': True, 'sections': SECTIONS, 'visualization': SPEC})):
            result = await runner.run(req)
        assert result['visualization'] is None
        assert runner.internet.decisions.predict.await_count == 2
        assert 'visual:0' not in runner.internet.decisions.predict.call_args.args[1]
    asyncio.run(run())
