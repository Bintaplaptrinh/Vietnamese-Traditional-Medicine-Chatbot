# Dataset knowledge graph

This run uses the local `../ai-knowledge-graph` package with NVIDIA's
`google/diffusiongemma-26b-a4b-it` endpoint. Python runs in conda environment `bqp`.

The cleaned input inventory contains 120 PDFs, 1,009 pages, and 597,624 words. PDF
text is read with PyMuPDF; control characters used as spaces are normalized.
Every input
word is assigned to one of 26 batches; `batches.json` records the original PDF and
word range of every block. Documents longer than a batch span multiple blocks.

To fit the user-provided limit of 30 API calls per day, extraction asks for the
key relationships from each document block, with a maximum of 120 triples per
batch. It is a broad corpus graph, not exhaustive sentence-by-sentence extraction.
LLM inference, entity resolution, community naming, automatic retries, and
thinking are disabled. Local entity standardization and community detection run
through the original ai-knowledge-graph package.

API attempts are counted before each request in `api-ledger.json`. The runner
stops at 30 potentially sent requests in a rolling 24-hour window. Timeouts count
toward the budget; a confirmed DNS failure before sending HTTP does not. All
attempts stay in the ledger. Calls made elsewhere with the same API key are
not observable; subtract them using `--max-calls` before starting. Run only one
copy of this runner at a time.

From the project root:

```bash
source /home/tuanphat/anaconda3/etc/profile.d/conda.sh
conda activate bqp
# Set NVIDIA_API_KEY in your shell or secret manager; never put it in config.
python -u knowledge/dataset-run/run_dataset.py
```

Successful batches are saved in `checkpoints/`, and original model replies in
`responses/`. Rerunning skips completed checkpoints and uses the response cache.
If a request or validation fails, processing stops and exports the completed
batches. `run-report.json` states whether all batches finished and lists document
coverage. A graph from a stopped run is partial.

The outputs are `dataset_graph.html`, `dataset_graph.json`, and CSV, GraphML, and
Cypher exports. Each triple keeps
its original PDF filename and batch. Model-provided source quotations are checked
against the supplied block; `source_verified` indicates the check result.

After the main pass, coverage-repair requests use the remaining API budget to extract a few facts from
bounded excerpts of any documents missing from the graph. Structured repair uses
NVIDIA's `response_format` JSON schema, requiring an output slot for each missing
document. `run-report.json` is complete only when all 26 main batches finished
and all 120 documents have triples. Well-formed objects from malformed replies
are recovered without changing their values; the original replies are preserved.

The completed run covered all 120 PDFs, with 1,170 nodes and 934 relationships.
There were 30 potentially sent NVIDIA requests (including the timed-out request)
and one unsent DNS failure. Inference was disabled, and 403 relationships retained
model-provided source quotations verified against the supplied PDF text.

The first completed batch also generates a preview, marked partial in the run
report. To regenerate exports from checkpoints without any API calls or key:

```bash
conda activate bqp
python knowledge/dataset-run/run_dataset.py --render-only
```

For the context window and request parameters, see the
[NVIDIA model card](https://build.nvidia.com/google/diffusiongemma-26b-a4b-it/modelcard)
and [API reference](https://docs.api.nvidia.com/nim/reference/diffusiongemma-26b-a4b-it-infer).
