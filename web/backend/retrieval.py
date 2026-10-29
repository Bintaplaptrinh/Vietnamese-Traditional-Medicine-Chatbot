"""Local lexical selection and source excerpts; no generation or network calls."""
import math
import re
import json
from collections import Counter
from bisect import bisect_right

from evidence import canonical, pack_evidence, search_terms
from graph_chat import STOPWORDS, normalize


def terms(text):
    return [word for word in search_terms(text) if normalize(word) not in STOPWORDS]


def source_candidates(facts):
    """Use the original passage once when several graph edges point into it."""
    facts = [dict(fact) for fact in facts]
    passages = [fact for fact in facts if fact.get("kind") == "text"]
    kept = []
    for fact in facts:
        linked = []
        if fact.get("kind") == "graph" and fact.get("source_verified") and fact.get("evidence_ids"):
            ids = set(fact["evidence_ids"])
            linked = [source for source in passages
                      if source.get("document_id") == fact.get("document_id")
                      and ids.intersection(source.get("evidence_ids", [source.get("record_id")]))
                      and canonical(fact.get("text") or fact.get("source", "")) in canonical(source.get("text", ""))
                      and (not source.get("context") or source.get("context") == fact.get("context", {}))
                      and source.get("conflict_group") in (None, fact.get("conflict_group"))]
        if linked:
            for source in linked:
                source.setdefault("graph_record_ids", []).append(fact.get("record_id"))
                if fact.get("context"):
                    source["context"] = fact["context"]
                if fact.get("conflict_group"):
                    source["conflict_group"] = fact["conflict_group"]
            continue
        kept.append(fact)
    return kept


def excerpt(text, question, limit):
    """Choose a contiguous window of complete source sentences without rewriting."""
    if len(text) <= limit:
        return text, 0
    # Include the complete sentence before/after a hit when it fits; negation,
    # population and study qualifiers must remain part of the source wording.
    boundaries = [0] + [match.end() for match in re.finditer(r"(?<=[.!?])\s+|\n[ \t]*\n", text)] + [len(text)]
    wanted = set(terms(question))
    windows = []
    for start in boundaries[:-1]:
        end = boundaries[bisect_right(boundaries, start + limit) - 1]
        if end > start:
            words = set(terms(text[start:end]))
            windows.append((len(words & wanted), end - start, -start, start, end))
    # Never cut an overlong sentence or line in half. Such a record is omitted
    # rather than turning a partial statement into evidence.
    if not windows:
        return "", 0
    _, _, _, start, end = max(windows)
    return text[start:end], start


def lexical_shortlist(facts, question, limit=24, snippet_chars=1200):
    """BM25 over the bounded retrieval pool, then compact local reranker inputs."""
    facts = source_candidates(facts)
    texts = [" ".join(str(fact.get(key) or "") for key in
                       ("subject", "predicate", "object", "text", "source")) for fact in facts]
    tokens = [Counter(terms(text)) for text in texts]
    query = set(terms(question))
    total = len(tokens)
    average = sum(sum(counts.values()) for counts in tokens) / max(1, total)
    frequency = {term: sum(term in counts for counts in tokens) for term in query}

    def score(index):
        counts = tokens[index]
        length = sum(counts.values())
        value = 0.0
        for term in query:
            tf = counts[term]
            idf = math.log1p((total - frequency[term] + .5) / (frequency[term] + .5))
            value += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / max(1, average)))
        return value, facts[index].get("retrieval_score", 0)

    ranked, omitted_groups = [], set()
    for index in sorted(range(total), key=score, reverse=True):
        fact = dict(facts[index])
        if fact.get("kind") in {"text", "web"} and fact.get("text"):
            original = fact["text"]
            text, start = excerpt(original, question, snippet_chars)
            if not text:
                if fact.get("conflict_group"):
                    omitted_groups.add(fact["conflict_group"])
                continue
            fact.update(text=text)
            if text != original:
                fact["excerpt"] = {"start": start, "end": start + len(text), "original_chars": len(original)}
        ranked.append(fact)
    ranked = [fact for fact in ranked if fact.get("conflict_group") not in omitted_groups]
    # Several graph edges can cite the same paragraph. Rerank the paragraph
    # once, preserving all record IDs locally instead of spending top-k slots
    # on repeated source text. Never collapse a flagged conflict.
    distinct, seen = [], {}
    for fact in ranked:
        text = fact.get("text") or fact.get("source", "")
        key = (fact.get("document_id", fact.get("document", fact.get("url"))), fact.get("page"),
               canonical(text), json.dumps(fact.get("context", {}), sort_keys=True), fact.get("polarity", "unknown"))
        if text and not fact.get("conflict_group") and key in seen:
            seen[key].setdefault("merged_record_ids", []).append(fact.get("record_id"))
            continue
        distinct.append(fact)
        if text and not fact.get("conflict_group"):
            seen[key] = fact
    # Conflict companions must either fit together or be omitted together.
    return pack_evidence(distinct, [], max_chars=80000, max_items=limit, compact=True, per_step=0)
