---
name: paper-to-claim-verifier
description: Keep each draft claim within the scope of its supplied cited evidence.
license: MIT
---

# Paper-to-claim discipline for Bloop

Before writing, separate the requested claim into its subject, setting,
population/model, intervention, outcome, polarity and implied strength. Verify
all parts against the supplied original text, not just the shared topic.

Distinguish directly supported, partial/overstated, contradicted and unverified
claims internally. Write only statements fully supported by their selected
citation IDs. When an essential part is missing, use the host's unsupported
result and targeted next_queries rather than completing it from memory.

Preserve disease stage, preparation/formula version, dose, timing, units,
experimental model and attribution. Do not transfer an ingredient's or formula's
finding to another preparation, or an animal/cell finding to human efficacy.
Separate association, prediction, mechanism, intervention effect and clinical
utility. A review's second-hand statement is not evidence that the cited primary
study was inspected. Never fabricate a primary citation, DOI, PMID or finding.

Each output section remains an atomic factual statement with source IDs. The
host's independent JEV gate makes the final support decision.
