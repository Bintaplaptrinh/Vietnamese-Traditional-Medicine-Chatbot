---
name: biomedical-search-strategy-builder
description: Plan source-bounded Vietnamese and English retrieval queries for the current question.
license: MIT
---

# Biomedical search strategy for Bloop

Preserve the user's actual question, named entities, Vietnamese accents and
requested scope. Resolve pronouns only from relevant conversation history.
Split only the information the user needs into evidence needs; a definition
usually needs one step, not an unsolicited systematic review.

For a research question, identify population, intervention/exposure, comparison
and outcome only when supplied or necessary. Missing optional PICO fields do not
justify blocking an otherwise answerable question.

Propose short Vietnamese/English free-text queries suitable for the host's local
BM25/graph and general web search. Expand terminology conservatively; a proposed
MeSH heading or alias is a retrieval candidate, not verified equivalence. Preserve
the original terms when a mapping is uncertain. Do not invent a heading or ID.

Database-specific Boolean syntax and filters belong only in an explicitly
requested search strategy for that database. Do not send PubMed field tags to
local retrieval. Respect allowed_sources; this skill never opens a source or
changes the route, documents, branches, budget or provider.
