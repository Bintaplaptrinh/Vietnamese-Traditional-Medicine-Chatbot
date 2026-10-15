import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from unittest.mock import Mock

import httpx
import pytest

from evidence import canonical, identity, mask_evidence, pack_evidence
from ingestion import parse_pdf, validate_candidate
from ingestion import extract_document
from harness import Budget, PROFILES
from internet import Decisions, DecisionUnavailable
from knowledge_store import KnowledgeStore, connect, schema, import_ontology
from test_harness import harness, request, PLAN, GOOD


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch):
    async def inline(function, *args):
        return function(*args)
    monkeypatch.setattr(asyncio, 'to_thread', inline)


def test_accent_identity_and_cross_ontology_collisions():
    assert canonical('Trĩ') != canonical('tri')
    assert identity('mesh', 'same') != identity('vietherbs', 'same')
    facts = [{'kind': 'ontology', 'branch': branch, 'record_id': branch, 'subject': 'same', 'text': 'same'} for branch in ['mesh', 'vietherbs']]
    assert len(mask_evidence(facts)) == 2
    assert len(mask_evidence(facts, ['mesh'])) == 1


def test_mask_deduplicates_but_preserves_source_conflicts():
    fact = {'kind': 'graph', 'branch': 'graph', 'record_id': 'a', 'subject': 'A', 'predicate': 'has', 'object': 'B', 'source_verified': True, 'source': 'A has B', 'document': 'one'}
    other = {**fact, 'record_id': 'b', 'document': 'two', 'object': 'C', 'source': 'A has C'}
    values = mask_evidence([fact, dict(fact), other, {**fact, 'inferred': True}, {**fact, 'review_status': 'quarantine'}])
    assert len(values) == 2
    assert values[0]['conflict_group'] == values[1]['conflict_group']
    assert len(pack_evidence(values, ['A'])) == 2
    assert not pack_evidence(values, ['A'], max_items=1)
    assert len(mask_evidence(values, documents=['two'])) == 1


def test_ingestion_keeps_pages_offsets_and_exact_quotes():
    import pymupdf
    with pymupdf.open() as pdf:
        page = pdf.new_page(); page.insert_text((72, 72), 'A contains compound B. Not tested in humans.')
        pdf.new_page()  # An empty/scan-only page is not silently treated as parsed.
        data = pdf.tobytes()
    doc, units = parse_pdf(data, '../../sample.pdf')
    assert doc['name'] == 'sample.pdf' and doc['pages_needing_ocr'] == [2]
    assert units[0]['page'] == 1 and len(units[0]['bbox']) == 4
    assert units[0]['raw_text'] == units[0]['text']
    assert units[0]['offset_end'] - units[0]['offset_start'] == len(units[0]['text'])
    candidate = {'subject': 'A', 'subject_type': 'MedicinalMaterial', 'predicate': 'containsCompound', 'object': 'B', 'object_type': 'Compound',
                 'source': 'A contains compound B.', 'polarity': 'affirmed', 'evidence_type': 'study_finding',
                 'context': dict.fromkeys(['population','dose','preparation','community','study_model'])}
    assert validate_candidate(candidate, units[0]) is None
    assert validate_candidate({**candidate, 'source': 'A treats humans.'}, units[0]) == 'quote_mismatch'
    assert validate_candidate({**candidate, 'object_type': 'BiomedicalDisease'}, units[0]) == 'domain_range'
    assert validate_candidate({**candidate, 'subject_type': []}, units[0]) == 'entity_type'


def test_streaming_ontology_keeps_ids_and_entry_term_role(tmp_path):
    ttl = tmp_path / 'terms.ttl'
    ttl.write_text('@prefix skos: <http://www.w3.org/2004/02/skos/core#> . <urn:a> skos:prefLabel "Trĩ"@vi; skos:altLabel "entry"@en; skos:broader <urn:b> .')
    db = connect(tmp_path / 'db.sqlite'); schema(db)
    # Resource path in the import manifest must be relative to the configured ROOT.
    with patch('knowledge_store.ROOT', tmp_path):
        report = import_ontology(db, ttl, 'mesh')
    assert report['parsed_triples'] == 3
    assert db.execute("SELECT role FROM labels WHERE label='entry'").fetchone()[0] == 'entry_term'
    assert db.execute('SELECT subject_id FROM edges').fetchone()[0] == 'mesh:urn:a'
    assert not db.execute('SELECT concept_id FROM label_search WHERE label_search MATCH ?', ('"tri"',)).fetchall()
    db.close()


def test_independent_verifier_rejects_forged_self_approval():
    async def run():
        app = harness()
        app.internet.decisions.predict = AsyncMock(return_value={'claim:0': {'choice': 'unknown'}, 'step:0': {'choice': 'supported'}, 'step:1': {'choice': 'supported'}})
        with patch('harness.complete', AsyncMock(side_effect=[PLAN, GOOD])):
            result = await app.run(request('graph'))
        assert result['verification_status'] == 'insufficient' and result['citations'] == []
        assert app.internet.decisions.predict.await_count == 1
    asyncio.run(run())


def test_jev_missing_key_and_invalid_probabilities_fail_closed(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    async def run():
        with pytest.raises(DecisionUnavailable):
            await Decisions(None).predict({}, {}, Budget(PROFILES['low']))
    asyncio.run(run())
    with pytest.raises(ValueError):
        Decisions.validate({'x': {'choice': 'ok', 'probabilities': {'ok': float('nan'), 'unknown': 0.}}}, {'x': {'criteria': {'ok': '', 'unknown': ''}}})


def test_new_claim_admission_requires_source_and_separate_jev():
    candidate = {'subject': 'A', 'subject_type': 'MedicinalMaterial', 'predicate': 'containsCompound', 'object': 'B', 'object_type': 'Compound',
                 'source': 'A contains B.', 'polarity': 'affirmed', 'evidence_type': 'study_finding',
                 'context': dict.fromkeys(['population','dose','preparation','community','study_model'])}
    unit = {'record_id': 'u1', 'text': 'A contains B.', 'raw_text': 'A contains B.', 'page': 1, 'bbox': [0,0,10,10]}
    async def run():
        async def verify(state, questions, budget):
            budget.take()
            return {'0': {'choice': 'unknown'}}
        decisions = SimpleNamespace(predict=AsyncMock(side_effect=verify))
        with patch('graph_chat.complete', AsyncMock(return_value={'claims': [candidate, {**candidate, 'source': 'Fabricated.'}]})):
            result = await extract_document({'id': 'doc1', 'name': 'one.pdf'}, [unit], None, '', '', '', decisions, Budget(PROFILES['low']))
        assert result['extraction_status'] == 'complete'
        assert all(c['review_status'] == 'quarantine' for c in result['claims'])
        assert result['claims'][0]['semantic_support'] == 'unknown'
        assert result['claims'][1]['validation_reason'] == 'quote_mismatch'
        assert decisions.predict.await_count == 1
    asyncio.run(run())


def test_upload_api_validates_pdf_and_is_idempotent(tmp_path, monkeypatch):
    import hashlib
    import main
    import pymupdf
    from starlette.formparsers import MultiPartParser
    monkeypatch.setattr(MultiPartParser, 'spool_max_size', 2 * 1024 * 1024)
    with pymupdf.open() as pdf:
        page = pdf.new_page(); page.insert_text((72, 72), 'A source statement.')
        data = pdf.tobytes()
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setenv('PDF_UPLOAD_MAX_MB', '1')
    async def run():
        with patch('main.build_store', return_value={}):
            async with main.lifespan(main.app):
                main.app.state.jobs.folder = tmp_path
                main.app.state.jobs.submit = Mock(return_value={'id': digest, 'status': 'queued'})
                main.app.state.knowledge.store.documents = Mock(return_value=[])
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                    assert (await client.post('/api/documents', files={'file': ('bad.pdf', b'not PDF')})).status_code == 415
                    assert (await client.post('/api/documents', files={'file': ('large.pdf', b'%PDF-' + b'x'*1048576)})).status_code == 413
                    response = await client.post('/api/documents', files={'file': ('new.pdf', data, 'application/pdf')})
                    assert response.status_code == 202 and response.json()['id'] == digest
                    main.app.state.jobs.submit.assert_called_once()
                    main.app.state.knowledge.store.documents.return_value = [{'sha256': digest, 'name': 'old.pdf', 'id': 'document:' + digest}]
                    response = await client.post('/api/documents', files={'file': ('renamed.pdf', data)})
                    assert response.json()['status'] == 'already_indexed'
                    main.app.state.jobs.submit.assert_called_once()
                    assert (await client.get('/api/documents/not-a-hash')).status_code == 404
    asyncio.run(run())
