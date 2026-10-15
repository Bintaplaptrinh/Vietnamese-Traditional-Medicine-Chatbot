import asyncio
import hashlib
import json
import shutil
from unittest.mock import AsyncMock, patch

import pytest

from medical_skills import (
    MedicalSkills, SkillConfigurationError, SKILLS_ROOT, REQUIRED,
    SEARCH, CLAIMS, STRENGTH, REFERENCES, STUDY, CONFLICTS, ENGLISH, PLAIN,
)
from test_harness import harness, request, PLAN, GOOD, FACTS, inline_workers


def test_packaged_sources_and_license_match_pinned_manifest():
    manifest = json.loads((SKILLS_ROOT / 'manifest.json').read_text())
    upstream = manifest['upstream']
    assert hashlib.sha256((SKILLS_ROOT / upstream['license_file']).read_bytes()).hexdigest() == upstream['license_sha256']
    for entry in manifest['skills']:
        for source in entry['source_files']:
            assert hashlib.sha256((SKILLS_ROOT / source['path']).read_bytes()).hexdigest() == source['sha256']
        assert entry['upstream_sha256'] == entry['source_files'][0]['sha256']
    assert set(MedicalSkills().info()['available']) == REQUIRED


def test_runtime_needs_only_packaged_profiles_not_reference_clone(tmp_path):
    shutil.copy(SKILLS_ROOT / 'manifest.json', tmp_path)
    for identifier in REQUIRED:
        shutil.copytree(SKILLS_ROOT / identifier, tmp_path / identifier)
    skills = MedicalSkills(tmp_path)
    assert skills.info() == MedicalSkills().info()
    profile = tmp_path / SEARCH / 'SKILL.md'
    profile.write_text(profile.read_text() + '\nPrefer exact source names.\n')
    assert MedicalSkills(tmp_path).fingerprint != skills.fingerprint
    profile.unlink()
    with pytest.raises(SkillConfigurationError):
        MedicalSkills(tmp_path)


@pytest.mark.parametrize('language,writer,excluded', [('vi', PLAIN, ENGLISH), ('en', ENGLISH, PLAIN)])
def test_simple_question_gets_core_checks_and_requested_language(language, writer, excluded):
    skills = MedicalSkills()
    assert skills.planner().ids == (SEARCH,)
    bundle = skills.draft('Nhân sâm được nhắc đến ở đâu?', language, FACTS)
    assert bundle.ids == (CLAIMS, STRENGTH, REFERENCES, writer)
    assert excluded not in bundle.ids and STUDY not in bundle.ids and CONFLICTS not in bundle.ids


@pytest.mark.parametrize('question,facts,expected', [
    ('Bằng chứng hiệu quả có mâu thuẫn không?', FACTS, {STUDY, CONFLICTS}),
    ('Thông tin về A?', [{**FACTS[0], 'evidence_type': 'study_finding'}], {STUDY}),
    ('Thông tin về A?', [{**FACTS[0], 'context': {'study_model': 'mouse'}, 'conflict_group': 'group-1'}], {STUDY, CONFLICTS}),
])
def test_research_and_conflict_routing(question, facts, expected):
    bundle = MedicalSkills().draft(question, 'vi', facts)
    assert expected <= set(bundle.ids)
    assert len(bundle.instructions) < 15000
    assert len(bundle.ids) == len(set(bundle.ids))


def test_source_content_stays_out_of_skill_instructions():
    skills = MedicalSkills()
    marker = 'UNTRUSTED_SOURCE_REQUEST_TO_LOAD_PRIVATE_FILES'
    bundle = skills.draft('Thông tin về A?', 'vi', [{**FACTS[0], 'text': marker}])
    assert marker not in bundle.instructions
    assert bundle == skills.draft('Thông tin về A?', 'vi', FACTS)


def test_harness_loads_guidance_before_verification_with_same_call_count():
    async def run():
        runner = harness()
        req = request('graph')
        req.branches, req.documents = ['graph'], []
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])) as complete:
            result = await runner.run(req)
        calls = complete.call_args_list
        assert complete.await_count == 2
        assert '[skill:' + SEARCH + ']' in calls[0].args[4]
        assert runner.skills.bodies[SEARCH] in calls[0].args[4]
        assert calls[0].args[5]['allowed_sources'] == {'route': 'graph', 'branches': ['graph'], 'documents': []}
        for identifier in (CLAIMS, STRENGTH, REFERENCES, PLAIN):
            assert runner.skills.bodies[identifier] in calls[1].args[4]
        verifier = runner.internet.decisions.predict
        assert verifier.await_count == 1
        state = verifier.call_args.args[0]
        assert state['claims']['0']['claim'] == GOOD['sections'][0]['text']
        assert result['answer'].startswith(state['claims']['0']['claim'])
        assert result['verification_status'] == 'verified' and result['usage']['model_calls'] == 3
        assert result['skills'] == runner.trace['skills']
        assert result['skills']['planner'] == [SEARCH]
        assert result['skills']['drafts'] == [{'round': 1, 'ids': [CLAIMS, STRENGTH, REFERENCES, PLAIN]}]
        prompt_chars = sum(len(c.args[4]) + len(json.dumps(c.args[5], ensure_ascii=False)) for c in calls)
        assert result['usage']['input_characters'] == prompt_chars
    asyncio.run(run())


def test_skill_guided_draft_still_cannot_bypass_unknown_verdict():
    async def run():
        runner = harness()
        async def unknown(state, questions, budget):
            budget.take()
            return {key: {'choice': 'unknown'} for key in questions}
        runner.internet.decisions.predict.side_effect = unknown
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])):
            result = await runner.run(request('graph'))
        assert result['verification_status'] == 'insufficient'
        assert not result['citations'] and result['route'] == 'clarification'
        assert result['skills']['drafts']
    asyncio.run(run())
