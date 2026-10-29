"""Versioned local ontology + corpus store; bounded RDF import and Qdrant BM25."""
import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import shutil
import threading
import time

from evidence import VERSION, canonical, identity, mask_evidence, search_terms

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "knowledge" / "shared"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
LOG = logging.getLogger(__name__)


def connect(path, readonly=False):
    db = sqlite3.connect(f"file:{path}?mode=ro" if readonly else path, uri=readonly)
    db.row_factory = sqlite3.Row
    return db


def schema(db):
    db.executescript('''
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE concepts (id TEXT PRIMARY KEY, branch TEXT, uri TEXT, label TEXT, type TEXT);
    CREATE TABLE labels (concept_id TEXT, label TEXT, language TEXT, role TEXT,
      UNIQUE(concept_id,label,language,role));
    CREATE VIRTUAL TABLE label_search USING fts5(concept_id UNINDEXED, branch UNINDEXED, label,
      tokenize='unicode61 remove_diacritics 0');
    CREATE TABLE edges (id TEXT PRIMARY KEY, branch TEXT, subject_id TEXT, predicate TEXT,
      object_id TEXT, payload TEXT);
    CREATE INDEX edge_subject ON edges(subject_id);
    CREATE INDEX edge_object ON edges(object_id);
    CREATE TABLE documents (id TEXT PRIMARY KEY, name TEXT, sha256 TEXT, status TEXT, payload TEXT);
    CREATE TABLE units (id TEXT PRIMARY KEY, document_id TEXT, text TEXT, payload TEXT);
    CREATE VIRTUAL TABLE unit_search USING fts5(unit_id UNINDEXED,text,
      tokenize='unicode61 remove_diacritics 0');
    ''')


def add_concept(db, cid, branch, label, kind="Concept", uri=None, language="", role="preferred"):
    db.execute("INSERT OR IGNORE INTO concepts VALUES (?,?,?,?,?)", (cid, branch, uri, label, kind))
    if role == "preferred":
        db.execute("UPDATE concepts SET label=? WHERE id=?", (label, cid))
    row = db.execute("INSERT OR IGNORE INTO labels VALUES (?,?,?,?)", (cid, label, language, role))
    if row.rowcount:
        db.execute("INSERT INTO label_search VALUES (?,?,?)", (cid, branch, label))


def import_ontology(db, path, branch):
    """Native streaming RDF parsing into selected, source-scoped terminology.

    Blank-node OWL restrictions are never flattened into medical assertions.
    """
    from pyoxigraph import parse, RdfFormat, NamedNode, Literal
    selected = {RDFS + "label", SKOS + "prefLabel", SKOS + "altLabel",
                SKOS + "definition", RDFS + "comment", RDFS + "subClassOf",
                SKOS + "broader", SKOS + "narrower", SKOS + "related",
                SKOS + "exactMatch", SKOS + "closeMatch", OWL + "versionInfo"}
    parsed, retained = 0, 0
    LOG.info("Importing %s (%s bytes), native streaming parser", branch, path.stat().st_size)
    fmt = RdfFormat.TURTLE if path.suffix == ".ttl" else RdfFormat.RDF_XML
    for triple in parse(path=path, format=fmt, base_iri=path.as_uri()):
        parsed += 1
        s, p, o = triple.subject, triple.predicate, triple.object
        predicate = p.value
        if not isinstance(s, NamedNode) or predicate not in selected:
            continue
        cid = branch + ":" + s.value
        if predicate in {RDFS + "label", SKOS + "prefLabel", SKOS + "altLabel"} and isinstance(o, Literal):
            role = "entry_term" if predicate == SKOS + "altLabel" else "preferred"
            add_concept(db, cid, branch, o.value, uri=s.value, language="vi" if o.language == "vn" else o.language or "", role=role)
        elif isinstance(o, NamedNode):
            oid = branch + ":" + o.value
            for node, uri in [(cid, s.value), (oid, o.value)]:
                db.execute("INSERT OR IGNORE INTO concepts VALUES (?,?,?,?,?)", (node, branch, uri, uri.rsplit('#',1)[-1].rsplit('/',1)[-1], "Concept"))
            eid = identity(branch + ":edge", s.value, predicate, o.value)
            payload = {"record_id": eid, "branch": branch, "kind": "ontology", "subject_id": cid,
                       "predicate_id": predicate, "predicate": predicate, "object_id": oid,
                       "document": path.name, "source": s.value, "mapping_status": "source_asserted"}
            db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?)", (eid, branch, cid, predicate, oid, json.dumps(payload, ensure_ascii=False)))
        elif isinstance(o, Literal):
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (branch + ":" + s.value + ":" + predicate, o.value))
        retained += 1
        if retained % 25000 == 0:
            db.commit()
            LOG.info("%s: parsed %s triples, retained %s", branch, parsed, retained)
    db.commit()
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    versions = [row[0] for row in db.execute("SELECT value FROM metadata WHERE key LIKE ?", (branch + ":%:" + OWL + "versionInfo",))]
    return {"file": str(path.relative_to(ROOT)), "parsed_triples": parsed, "selected_triples": retained,
            "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns, "parser": "pyoxigraph-stream",
            "sha256": digest, "source_versions": versions}


def add_units(db, document, units):
    db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)", (document["id"], document["name"], document["sha256"], document["status"], json.dumps(document, ensure_ascii=False)))
    for unit in units:
        row = db.execute("INSERT OR IGNORE INTO units VALUES (?,?,?,?)", (unit["record_id"], document["id"], unit["text"], json.dumps(unit, ensure_ascii=False)))
        if row.rowcount:
            db.execute("INSERT INTO unit_search VALUES (?,?)", (unit["record_id"], unit["text"]))


def import_corpus(db, cache_db=None):
    from ingestion import parse_pdf
    parsed = {}
    def read_document(path, name):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if cache_db:
            row = cache_db.execute("SELECT payload FROM documents WHERE id=?", ("document:" + digest,)).fetchone()
            if row:
                document = json.loads(row[0])
                if document.get("ontology_version") == VERSION and document.get("name") == name:
                    units = [json.loads(r[0]) for r in cache_db.execute("SELECT payload FROM units WHERE document_id=?", (document["id"],))]
                    return document, units
        return parse_pdf(data, name)
    for path in sorted((ROOT / "Dataset").glob("*.pdf")):
        document, units = read_document(path, path.name)
        add_units(db, document, units)
        parsed[path.name] = (document, units)
    upload_path = DATA / "uploads"
    for path in sorted(upload_path.glob("*.pdf")):
        document, units = parse_pdf(path.read_bytes(), path.stem + ".pdf")
        receipt = upload_path / (path.stem + ".json")
        if receipt.exists():
            document["name"] = json.loads(receipt.read_text())["name"]
        add_units(db, document, units)
        parsed[document["name"]] = (document, units)
        if receipt.exists():
            for claim in json.loads(receipt.read_text()).get("claims", []):
                if not all(isinstance(claim.get(k), str) for k in ("subject", "object", "predicate")):
                    continue
                nodes = []
                for side in ("subject", "object"):
                    kind = claim.get(side + "_type", "Concept")
                    kind = kind if isinstance(kind, str) else "Concept"
                    cid = identity("graph:entity", canonical(claim[side]), kind, document["id"])
                    add_concept(db, cid, "graph", claim[side], kind)
                    nodes.append(cid)
                payload = {**claim, "subject_id": nodes[0], "object_id": nodes[1]}
                db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?)", (claim["record_id"], "graph", nodes[0], claim["predicate"], nodes[1], json.dumps(payload, ensure_ascii=False)))
    path = Path(os.getenv("KNOWLEDGE_GRAPH_PATH", "knowledge/dataset-run/dataset_graph.json"))
    path = path if path.is_absolute() else ROOT / path
    for triple in json.loads(path.read_text()):
        document, units = parsed.get(triple.get("document"), ({}, []))
        nodes = []
        for side in ("subject", "object"):
            label = triple[side]
            kind = triple.get(side + "_type", "Concept")
            # Unknown historical entity typing cannot establish cross-source identity.
            cid = identity("graph:entity", canonical(label), kind, triple.get("document"))
            add_concept(db, cid, "graph", label, kind)
            nodes.append(cid)
        quote = canonical(triple.get("source", ""))
        matches = [u for u in units if quote and quote in canonical(u["text"])]
        eid = identity("graph:claim", triple)
        payload = {**triple, "record_id": eid, "branch": "graph", "kind": "graph", "subject_id": nodes[0],
                   "object_id": nodes[1], "document_id": document.get("id"), "ontology_version": VERSION,
                   "source_verified": bool(matches), "semantic_support": "unknown", "review_status": "pending",
                   "polarity": triple.get("polarity", "unknown"), "context": triple.get("context", {}),
                   "evidence_ids": [u["record_id"] for u in matches], "text": matches[0]["text"] if matches else "",
                   "page": matches[0]["page"] if matches else None}
        db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?)", (eid, "graph", nodes[0], triple["predicate"], nodes[1], json.dumps(payload, ensure_ascii=False)))
    db.commit()


def build_bm25(db, snapshot):
    from fastembed import SparseTextEmbedding
    from qdrant_client import QdrantClient, models
    model = SparseTextEmbedding(model_name="Qdrant/bm25", language="english", cache_dir=str(DATA / "model-cache"))
    directory = DATA / "bm25" / snapshot
    directory.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(location=":memory:")
    try:
        client.create_collection("evidence", vectors_config={}, sparse_vectors_config={
            "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)})
        cursor = db.execute("SELECT id,text FROM units ORDER BY id")
        number = 0
        with (directory / "evidence.jsonl").open("w", encoding="utf-8") as artifact:
            while rows := cursor.fetchmany(128):
                vectors = model.embed([row["text"] for row in rows])
                points = [models.PointStruct(id=number+i, vector={"bm25": models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())},
                           payload={"record_id": row["id"]}) for i, (row, v) in enumerate(zip(rows, vectors))]
                if len(points) != len(rows):
                    raise ValueError("BM25 embedding count mismatch")
                client.upsert("evidence", points)
                for point in points:
                    artifact.write(point.model_dump_json() + "\n")
                number += len(rows)
                if number % 1024 == 0:
                    LOG.info("BM25 indexed %s source units", number)
    finally:
        client.close()
    return number


def fingerprint():
    graph = Path(os.getenv("KNOWLEDGE_GRAPH_PATH", "knowledge/dataset-run/dataset_graph.json"))
    graph = graph if graph.is_absolute() else ROOT / graph
    paths = [ROOT / "knowledge/MeSH/MESH.ttl", ROOT / "knowledge/VietHerbs/VHO.owl", graph,
             *sorted((ROOT / "Dataset").glob("*.pdf")), *sorted((DATA / "uploads").glob("*.pdf"))]
    return identity("snapshot", VERSION, "qdrant-memory-jsonl-v1", os.getenv("KNOWLEDGE_BM25", "1"),
                    [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths if p.exists()])


def build_store(force=False):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        signature = fingerprint()
        current = DATA / "current.json"
        if not force and current.exists() and json.loads(current.read_text()).get("fingerprint") == signature:
            return json.loads(current.read_text())
        snapshot = signature.split(":")[1] + "-" + str(time.time_ns())
        path = DATA / (snapshot + ".sqlite")
        previous = json.loads(current.read_text()) if current.exists() else {}
        cached = bool(previous) and all(
            previous.get("sources", {}).get(branch, {}).get("size") == ontology.stat().st_size
            and previous.get("sources", {}).get(branch, {}).get("mtime_ns") == ontology.stat().st_mtime_ns
            for branch, ontology in [("mesh", ROOT / "knowledge/MeSH/MESH.ttl"), ("vietherbs", ROOT / "knowledge/VietHerbs/VHO.owl")]
            if ontology.exists()) and previous.get("ontology_version") == VERSION
        if cached:
            shutil.copyfile(DATA / (previous["snapshot"] + ".sqlite"), path)
        db = connect(path)
        db.executescript("PRAGMA synchronous=NORMAL; PRAGMA journal_mode=MEMORY; PRAGMA cache_size=-65536;")
        try:
            if cached:
                db.executescript("DELETE FROM labels WHERE concept_id IN (SELECT id FROM concepts WHERE branch='graph'); DELETE FROM label_search WHERE branch='graph'; DELETE FROM concepts WHERE branch='graph'; DELETE FROM edges WHERE branch='graph'; DELETE FROM documents; DELETE FROM units; DELETE FROM unit_search; DELETE FROM metadata WHERE key='manifest';")
                sources = previous["sources"]
                for source in sources.values():
                    if not source.get("sha256"):
                        with (ROOT / source["file"]).open("rb") as stream:
                            source["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            else:
                schema(db)
                sources = {}
                for branch, ontology in [("mesh", ROOT / "knowledge/MeSH/MESH.ttl"), ("vietherbs", ROOT / "knowledge/VietHerbs/VHO.owl")]:
                    if ontology.exists():
                        sources[branch] = import_ontology(db, ontology, branch)
            cache_db = connect(DATA / (previous["snapshot"] + ".sqlite"), readonly=True) if cached else None
            try:
                import_corpus(db, cache_db)
            finally:
                if cache_db:
                    cache_db.close()
            count = build_bm25(db, snapshot) if os.getenv("KNOWLEDGE_BM25", "1") == "1" else 0
            manifest = {"snapshot": snapshot, "fingerprint": signature, "ontology_version": VERSION, "sources": sources,
                        "bm25_model": "Qdrant/bm25" if count else None,
                        "bm25_backend": "qdrant-memory-jsonl-v1",
                        "counts": {table: db.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("concepts", "edges", "documents", "units")}}
            db.execute("INSERT INTO metadata VALUES (?,?)", ("manifest", json.dumps(manifest, ensure_ascii=False)))
            db.commit()
            # Both text/graph and BM25 are complete before switching the shared pointer.
            tmp = DATA / "current.json.tmp"
            tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            tmp.replace(current)
            LOG.info("Published snapshot %s: %s", snapshot, manifest["counts"])
            return manifest
        finally:
            db.close()


def publish_staging(path):
    """Recover an explicitly selected, fully parsed staging DB after index failure."""
    path = path.resolve()
    if path.parent != DATA or path.suffix != ".sqlite":
        raise ValueError("Staging database must be a .sqlite file in knowledge/shared")
    with (DATA / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db = connect(path)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Incomplete or damaged staging database")
            for pdf in (ROOT / "Dataset").glob("*.pdf"):
                digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
                if not db.execute("SELECT 1 FROM documents WHERE sha256=?", (digest,)).fetchone():
                    raise ValueError("Staging database does not contain the complete PDF corpus")
            sources = {}
            for branch, source in [("mesh", ROOT / "knowledge/MeSH/MESH.ttl"), ("vietherbs", ROOT / "knowledge/VietHerbs/VHO.owl")]:
                if not source.exists():
                    continue
                if not db.execute("SELECT 1 FROM concepts WHERE branch=? LIMIT 1", (branch,)).fetchone():
                    raise ValueError("Staging database lacks ontology: " + branch)
                with source.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                versions = [r[0] for r in db.execute("SELECT value FROM metadata WHERE key LIKE ?", (branch + ":%:" + OWL + "versionInfo",))]
                sources[branch] = {"file": str(source.relative_to(ROOT)), "size": source.stat().st_size,
                                   "mtime_ns": source.stat().st_mtime_ns, "sha256": digest, "source_versions": versions,
                                   "parser": "pyoxigraph-stream", "recovered_staging": True}
            count = build_bm25(db, path.stem)
            manifest = {"snapshot": path.stem, "fingerprint": fingerprint(), "ontology_version": VERSION,
                        "sources": sources, "bm25_model": "Qdrant/bm25", "bm25_backend": "qdrant-memory-jsonl-v1",
                        "counts": {table: db.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("concepts", "edges", "documents", "units")}}
            if count != manifest["counts"]["units"]:
                raise ValueError("BM25 snapshot lacks source units")
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", ("manifest", json.dumps(manifest, ensure_ascii=False)))
            db.commit()
            temporary = DATA / "current.json.tmp"
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            temporary.replace(DATA / "current.json")
            return manifest
        finally:
            db.close()


class KnowledgeStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.manifest = {}
        self.client = None
        self.model = None
        self.refresh()

    def refresh(self):
        with self.lock:
            current = DATA / "current.json"
            manifest = json.loads(current.read_text()) if current.exists() else {}
            if manifest.get("snapshot") != self.manifest.get("snapshot"):
                if self.client:
                    self.client.close()
                self.client = None
                self.manifest = manifest

    def close(self):
        with self.lock:
            if self.client:
                self.client.close()
                self.client = None

    def db(self):
        return connect(DATA / (self.manifest["snapshot"] + ".sqlite"), readonly=True)

    def documents(self):
        with self.lock:
            self.refresh()
            if not self.manifest:
                return []
            db = self.db()
            try:
                return [json.loads(r[0]) for r in db.execute("SELECT payload FROM documents ORDER BY name")]
            finally:
                db.close()

    @staticmethod
    def match(query):
        terms = list(dict.fromkeys(search_terms(query)))[:24]
        return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)

    @staticmethod
    def source_context(unit, document_units):
        """Keep neighboring source lines together, with original page provenance."""
        if not isinstance(unit.get("offset_start"), int) or unit.get("page") is None:
            return {k: v for k, v in unit.items() if k not in {"raw_text", "normalized_text", "cells"}}
        anchor = unit["offset_start"] // 1200 * 1200
        neighbors = sorted((u for u in document_units
                            if u.get("page") == unit["page"]
                            and isinstance(u.get("offset_start"), int)
                            and u["offset_start"] < anchor + 1450
                            and u.get("offset_end", u["offset_start"]) > max(0, anchor - 250)),
                           key=lambda u: u["offset_start"])
        if not neighbors:
            neighbors = [unit]
        text = "".join(u["text"] for u in neighbors)
        return {**{k: v for k, v in unit.items() if k not in {"raw_text", "normalized_text", "cells", "bbox", "block_id", "block_offset"}},
                "record_id": identity("context", unit["document_id"], unit["page"], [u["record_id"] for u in neighbors]),
                "text": text, "unit_type": "source_context",
                "evidence_ids": [u["record_id"] for u in neighbors],
                "offset_start": neighbors[0]["offset_start"], "offset_end": neighbors[-1]["offset_end"]}

    def retrieve(self, queries, branches=None, documents=None):
        with self.lock:
            self.refresh()
            if not self.manifest:
                return []
            db = self.db()
            try:
                lists = []
                document_units = {}
                def context(unit):
                    doc = unit.get("document_id")
                    if doc and doc not in document_units:
                        document_units[doc] = [json.loads(r[0]) for r in db.execute(
                            "SELECT payload FROM units WHERE document_id=?", (doc,))]
                    return self.source_context(unit, document_units.get(doc, [unit]))
                for query in list(dict.fromkeys(queries))[:7]:
                    match = self.match(query)
                    if not match:
                        continue
                    # Rank before limiting: common query words must not hide an exact
                    # entity that happens to occur later in the ontology tables.
                    hits = db.execute("SELECT concept_id FROM label_search WHERE label_search MATCH ? ORDER BY rank LIMIT 320", (match,)).fetchall()
                    labels = list({row[0]: row for row in hits}.values())
                    labels = sorted(labels, key=lambda r: max(
                        (int(canonical(l[0]) in canonical(query)), len(set(search_terms(l[0])) & set(search_terms(query))))
                        for l in db.execute("SELECT label FROM labels WHERE concept_id=?", (r[0],))), reverse=True)[:24]
                    facts = []
                    expanded = []
                    for row in labels:
                        concept = db.execute("SELECT * FROM concepts WHERE id=?", (row[0],)).fetchone()
                        if branches and concept["branch"] not in branches:
                            continue
                        if concept["branch"] != "graph":
                            aliases = [dict(r) for r in db.execute("SELECT label,language,role FROM labels WHERE concept_id=?", (row[0],))]
                            if any(canonical(alias["label"]) in canonical(query) for alias in aliases):
                                # Query expansion proposes additional source candidates;
                                # an alias never merges concept IDs or proves equivalence.
                                expanded.extend(alias["label"] for alias in aliases if alias["role"] == "preferred" and alias["language"] in {"en", "la", "vi"})
                            definitions = [r[0] for predicate in (SKOS + "definition", RDFS + "comment") for r in db.execute("SELECT value FROM metadata WHERE key=?", (concept["branch"] + ":" + concept["uri"] + ":" + predicate,))]
                            facts.append({"record_id": row[0], "kind": "ontology", "branch": concept["branch"], "subject_id": row[0],
                                          "subject": concept["label"], "title": concept["label"], "uri": concept["uri"],
                                          "text": json.dumps({"labels": aliases, "definitions": definitions}, ensure_ascii=False), "aliases": aliases,
                                          "source": concept["uri"], "ontology_version": VERSION})
                        adjacent = db.execute("SELECT payload FROM edges WHERE subject_id=? OR object_id=? LIMIT 24", (row[0], row[0])).fetchall()
                        if concept["branch"] == "graph":
                            # Even an unverified edge can locate its original document;
                            # only independently retrieved source text becomes evidence.
                            if f" {canonical(concept['label'])} " in f" {canonical(query)} ":
                                linked_docs = list(dict.fromkeys(json.loads(edge[0]).get("document_id") for edge in adjacent))
                                phrase = '"' + " ".join(search_terms(concept["label"])) + '"'
                                linked = []
                                for doc in [d for d in linked_docs if d][:4]:
                                    rows = db.execute("SELECT u.payload FROM unit_search JOIN units u ON u.id=unit_search.unit_id "
                                                      "WHERE unit_search MATCH ? AND u.document_id=? LIMIT 8", (phrase, doc)).fetchall()
                                    for source in rows:
                                        linked.append({**context(json.loads(source[0])), "retrieved_by": "graph_document"})
                                    if rows and document_units.get(doc):
                                        first = min(document_units[doc], key=lambda u: (u.get("page", 0), u.get("offset_start", 0)))
                                        linked.append({**context(first), "retrieved_by": "graph_document"})
                                lists.append(linked)
                            frontier = {node for edge in adjacent for node in (json.loads(edge[0])["subject_id"], json.loads(edge[0])["object_id"])}
                            for node in list(frontier)[:16]:
                                adjacent.extend(db.execute("SELECT payload FROM edges WHERE branch='graph' AND (subject_id=? OR object_id=?) LIMIT 8", (node, node)).fetchall())
                        for edge in adjacent[:100]:
                            payload = json.loads(edge[0])
                            if payload["kind"] == "graph":
                                facts.append(payload)
                            else:
                                subject = db.execute("SELECT label FROM concepts WHERE id=?", (payload["subject_id"],)).fetchone()
                                target = db.execute("SELECT label FROM concepts WHERE id=?", (payload["object_id"],)).fetchone()
                                facts.append({**payload, "subject": subject[0] if subject else payload["subject_id"],
                                              "object": target[0] if target else payload["object_id"],
                                              "text": f"Ontology source assertion: {subject[0] if subject else payload['subject_id']} → {payload['predicate']} → {target[0] if target else payload['object_id']}"})
                    lists.append(facts)
                    # FTS is a deterministic candidate fallback, never labelled BM25.
                    if self.manifest.get("bm25_model"):
                        text_queries = [query] + [q for q in dict.fromkeys(expanded) if canonical(q) != canonical(query)][:2]
                        ids = list(dict.fromkeys(uid for text_query in text_queries for uid in self.bm25(text_query)))
                    else:
                        ids = [r[0] for r in db.execute("SELECT unit_id FROM unit_search WHERE unit_search MATCH ? LIMIT 32", (match,))]
                    text_facts = []
                    for uid in ids:
                        row = db.execute("SELECT payload FROM units WHERE id=?", (uid,)).fetchone()
                        if row:
                            payload = json.loads(row[0])
                            # Raw text and cell records remain in the immutable source
                            # store; do not pay context budget for repeated copies.
                            text_facts.append(context(payload))
                    lists.append(text_facts)
                # Reciprocal rank fusion; repeat hits strengthen ranking but not identity.
                scores, records = {}, {}
                for values in lists:
                    for rank, fact in enumerate(values, 1):
                        key = fact["record_id"]
                        scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                        records[key] = fact
                ranked = [{**records[k], "retrieval_score": scores[k]} for k in sorted(scores, key=scores.get, reverse=True)]
                return [{**fact, "id": i, "snapshot": self.manifest["snapshot"]} for i, fact in enumerate(mask_evidence(ranked, branches, documents)[:120], 1)]
            finally:
                db.close()

    def warmup(self):
        """Load the current sparse index and exercise the query embedding path."""
        with self.lock:
            self.refresh()
            if not self.manifest.get("bm25_model"):
                return
            self.bm25("startup warmup")

    def bm25(self, query):
        if self.client is None:
            from fastembed import SparseTextEmbedding
            from qdrant_client import QdrantClient, models
            if self.model is None:
                self.model = SparseTextEmbedding(model_name="Qdrant/bm25", language="english", cache_dir=str(DATA / "model-cache"))
            self.client = QdrantClient(location=":memory:")
            self.client.create_collection("evidence", vectors_config={}, sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)})
            points = []
            with (DATA / "bm25" / self.manifest["snapshot"] / "evidence.jsonl").open(encoding="utf-8") as artifact:
                for line in artifact:
                    points.append(models.PointStruct.model_validate_json(line))
                    if len(points) == 256:
                        self.client.upsert("evidence", points); points = []
            if points:
                self.client.upsert("evidence", points)
        from qdrant_client import models
        vector = next(self.model.query_embed(query))
        result = self.client.query_points("evidence", query=models.SparseVector(indices=vector.indices.tolist(), values=vector.values.tolist()), using="bm25", limit=32)
        return [p.payload["record_id"] for p in result.points if p.score > 0]

    def graph(self, branch="graph", query="", limit=None, after_node=0, after_edge=0, snapshot=None):
        """Return the complete scope, optionally in keyset pages from one snapshot.

        Node and edge cursors advance independently so isolated concepts are also
        included. Search returns every matching concept and its one-hop neighbors.
        """
        with self.lock:
            self.refresh()
            if not self.manifest:
                return {"nodes": [], "edges": [], "status": "indexing"}
            if snapshot and snapshot != self.manifest["snapshot"]:
                raise ValueError("graph_snapshot_changed")
            if limit is not None and limit < 1:
                raise ValueError("graph_page_size")
            db = self.db()
            try:
                params = {"branch": branch, "match": self.match(query)}
                if query.strip():
                    scope = """WITH seed AS (
                        SELECT DISTINCT concept_id FROM label_search
                        WHERE label_search MATCH :match AND branch=:branch
                    ), scoped_edges AS (
                        SELECT rowid AS cursor, * FROM edges WHERE branch=:branch AND
                        (subject_id IN (SELECT concept_id FROM seed) OR object_id IN (SELECT concept_id FROM seed))
                    ), scoped_nodes AS (
                        SELECT rowid AS cursor, * FROM concepts WHERE branch=:branch AND
                        (id IN (SELECT concept_id FROM seed) OR id IN (SELECT subject_id FROM scoped_edges)
                         OR id IN (SELECT object_id FROM scoped_edges))
                    ) """ if params["match"] else """WITH scoped_edges AS (
                        SELECT rowid AS cursor, * FROM edges WHERE 0
                    ), scoped_nodes AS (SELECT rowid AS cursor, * FROM concepts WHERE 0) """
                else:
                    scope = """WITH scoped_edges AS (
                        SELECT rowid AS cursor, * FROM edges WHERE branch=:branch
                    ), scoped_nodes AS (SELECT rowid AS cursor, * FROM concepts WHERE branch=:branch) """
                params.update(after_node=after_node, after_edge=after_edge, take=limit + 1 if limit else -1)
                node_rows = db.execute(scope + "SELECT * FROM scoped_nodes WHERE cursor>:after_node ORDER BY cursor LIMIT :take", params).fetchall()
                edge_rows = db.execute(scope + "SELECT * FROM scoped_edges WHERE cursor>:after_edge ORDER BY cursor LIMIT :take", params).fetchall()
                more = limit is not None and (len(node_rows) > limit or len(edge_rows) > limit)
                if limit:
                    node_rows, edge_rows = node_rows[:limit], edge_rows[:limit]
                nodes = [{k: r[k] for k in r.keys() if k != "cursor"} for r in node_rows]
                edges = [{**json.loads(r["payload"]), "id": r["id"], "from": r["subject_id"], "to": r["object_id"], "label": r["predicate"].rsplit('#', 1)[-1]} for r in edge_rows]
                result = {"nodes": nodes, "edges": edges, "status": "ready", "snapshot": self.manifest["snapshot"], "limited": more,
                          "next": {"after_node": node_rows[-1]["cursor"] if node_rows else after_node,
                                   "after_edge": edge_rows[-1]["cursor"] if edge_rows else after_edge} if more else None}
                if not after_node and not after_edge:
                    result["total_nodes"] = db.execute(scope + "SELECT count(*) FROM scoped_nodes", params).fetchone()[0]
                    result["total_edges"] = db.execute(scope + "SELECT count(*) FROM scoped_edges", params).fetchone()[0]
                return result
            finally:
                db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--resume-staging", type=Path)
    args = parser.parse_args()
    print(json.dumps(publish_staging(args.resume_staging) if args.resume_staging else build_store(args.force), ensure_ascii=False, indent=2))
