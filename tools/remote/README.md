# V100 translation stage

Parse the PDF locally, then send only the parsed workspace and the English-to-Korean model to a configured SSH GPU host:

```bash
tools/remote/v100_translate_workspace.sh topabaem /absolute/path/to/workspace/job-id
```

The worker uses `OPENPDF2ZH_CTRANSLATE2_DEVICE=cuda` and `float16`, then copies `structured.json`, `translation_units.jsonl`, and `result.md` back into the local workspace. Rendering remains local so the configured fonts and Pretext browser helper stay consistent.

On a shared GPU with little free memory, select the smaller runtime conversion:

```bash
OPENPDF2ZH_REMOTE_COMPUTE_TYPE=int8_float16 tools/remote/v100_translate_workspace.sh topabaem /absolute/path/to/workspace/job-id
```

To use an OpenAI-compatible LLM already running on the V100 host:

```bash
OPENPDF2ZH_REMOTE_PROVIDER=openrouter \
OPENPDF2ZH_REMOTE_MODEL=/models/model.gguf \
OPENPDF2ZH_REMOTE_API_BASE_URL=http://127.0.0.1:8081/v1/chat/completions \
OPENPDF2ZH_REMOTE_API_KEY=local \
tools/remote/v100_translate_workspace.sh topabaem /absolute/path/to/workspace/job-id
```

For layout-sensitive papers and books, run the optional BabelDOC backend. The
third argument limits the translated pages:

```bash
OPENPDF2ZH_REMOTE_MODEL=/models/gemma-4-26B_q4_0-it.gguf \
tools/remote/v100_babeldoc_workspace.sh topabaem /absolute/path/to/workspace/job-id 1-15
```

This keeps the OpenAI-compatible model on the V100, forces JSON output, disables
reasoning tokens, and downloads the AGPL-3.0 BabelDOC 0.6.4 worker into an
isolated remote virtual environment. Output is copied to `babeldoc-output/`.
