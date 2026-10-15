"""Deterministic identity, retrieval masks and conflict-preserving evidence packing."""
import hashlib
import json
import re
import unicodedata

VERSION = "1.0.0"


def canonical(text):
    # Accents carry meaning: tri and trĩ must never become the same identity.
    return " ".join(unicodedata.normalize("NFC", str(text)).casefold().split())


def identity(namespace, *parts):
    value = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return namespace + ":" + hashlib.sha256(value.encode()).hexdigest()[:24]


def search_terms(text):
    return re.findall(r"[^\W_]+", canonical(text), re.UNICODE)


def mask_evidence(facts, branches=None, documents=None):
    """Remove exact duplicates, keeping incompatible source assertions visible.

    A label match is never an equivalence mapping. Conflict groups are flags for
    verification, not automatic declarations that distinct objects are incompatible.
    """
    kept, seen, groups = [], {}, {}
    for original in facts:
        fact = dict(original)
        branch = fact.get("branch", "web" if fact.get("kind") == "web" else "graph")
        if branches and branch not in branches:
            continue
        if documents and fact.get("document_id", fact.get("document")) not in documents:
            continue
        if fact.get("inferred") or fact.get("review_status") in {"rejected", "quarantine"}:
            continue
        if fact.get("kind") == "graph" and not fact.get("source_verified"):
            # Unverified edges remain in the explorer and can locate documents.
            continue
        context = json.dumps(fact.get("context", {}), ensure_ascii=False, sort_keys=True)
        signature = (branch, fact.get("kind"), fact.get("document_id", fact.get("document", fact.get("url"))),
                     fact.get("subject_id", canonical(fact.get("subject", ""))),
                     fact.get("predicate_id", canonical(fact.get("predicate", ""))),
                     fact.get("object_id", canonical(fact.get("object", ""))),
                     fact.get("polarity", "unknown"), context,
                     canonical(fact.get("text", fact.get("source", ""))))
        if signature in seen:
            seen[signature].setdefault("duplicate_ids", []).append(fact.get("record_id"))
            continue
        seen[signature] = fact
        fact["branch"] = branch
        fact["evidence_role"] = "terminology" if fact.get("kind") == "ontology" else "source"
        kept.append(fact)
        if fact.get("kind") == "graph":
            # Group source-specific entities by typed accented label only to FLAG
            # alternatives; this does not merge their IDs or assert equivalence.
            group = (canonical(fact.get("subject", "")), fact.get("subject_type", "Concept"),
                     fact.get("predicate_id", canonical(fact.get("predicate", ""))), context)
            groups.setdefault(group, []).append(fact)
    for group, values in groups.items():
        alternatives = {(canonical(v.get("object", "")), v.get("polarity", "unknown")) for v in values}
        if len(alternatives) > 1:
            conflict = identity("conflict", group)
            for value in values:
                value["conflict_group"] = conflict
    return kept


def pack_evidence(ranked, steps, max_chars=24000, max_items=32):
    """Reserve coverage per need and retain conflict companions before filling budget."""
    ranked = mask_evidence(ranked)
    chosen, seen, size = [], set(), 0

    def add(fact):
        nonlocal size
        key = fact.get("record_id") or identity("evidence", fact)
        cost = len(json.dumps(fact, ensure_ascii=False))
        if key in seen or len(chosen) >= max_items or size + cost > max_chars:
            return False
        chosen.append(fact); seen.add(key); size += cost
        return True

    for step in steps:
        terms = set(search_terms(step))
        candidates = sorted(ranked, key=lambda f: len(terms & set(search_terms(
            f.get("text", "") + " " + f.get("source", "") + " " + f.get("subject", "") + " " + f.get("object", "")))), reverse=True)
        for fact in candidates[:2]:
            add(fact)
    for fact in ranked:
        group = fact.get("conflict_group")
        bundle = [f for f in ranked if group and f.get("conflict_group") == group] or [fact]
        pending = [f for f in bundle if (f.get("record_id") or identity("evidence", f)) not in seen]
        if size + sum(len(json.dumps(f, ensure_ascii=False)) for f in pending) <= max_chars and len(chosen) + len(pending) <= max_items:
            for companion in pending:
                add(companion)
    # If a conflict companion cannot fit, remove the whole group rather than hide it.
    for group in {f.get("conflict_group") for f in chosen} - {None}:
        if sum(f.get("conflict_group") == group for f in chosen) != sum(f.get("conflict_group") == group for f in ranked):
            chosen = [f for f in chosen if f.get("conflict_group") != group]
    return [{**fact, "id": i} for i, fact in enumerate(chosen, 1)]
