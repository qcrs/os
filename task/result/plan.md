# Experiment Plan: Protocol A vs Protocol B Comparison

## Goal
Compare two communication protocols on 10 data-analysis tasks (titanic.csv):
- **Protocol A**: Plain text mode (`mode="text"`) — agents pass full natural language
- **Protocol B**: Structured mode with compressed text only (`mode="structured"`, `ENABLE_CONTEXT_PACKETS=1`, `ENABLE_EMBEDDING_TRANSFER=0`, `ENABLE_HIDDEN_STATE_TRANSFER=0`)

## Approach
Create a single experiment script `run_group1_comparison.py` that:

1. **Loads** titanic.csv data and 10 task questions from `group1_tasks.json`
2. **Injects CSV data** into the query context so the multi-agent system can reason about actual data
3. **Runs Protocol A**: all 10 tasks in text mode, collecting per-task results and metrics
4. **Runs Protocol B**: all 10 tasks in structured mode (context_packets only), collecting per-task results and metrics
5. **Extracts answers** from system output using regex parsing against the expected `@field[value]` format
6. **Compares** extracted answers with gold answers from `group1_gold.json`
7. **Saves** results JSON to `/data/mingwei/SynapseX/task/result/group1_comparison.json`

## Key Design Decisions

### CSV Data Injection
The multi-agent system is research-oriented (retriever generates text). For data analysis tasks, we prepend the CSV data (first 50 rows as a table) to each query so the LLM agents have actual data to reason about. This is necessary because the retriever doesn't load external files.

### Environment Configuration
Run inside `SynapseX-wmw` container with:
- `CHAT_BACKEND=transformers` (local Qwen3-8B, no API key needed)
- `LOCAL_MODEL_PATH=/data/models/Qwen3-8B`
- Protocol A: no special env vars (default text mode)
- Protocol B: `ENABLE_EMBEDDING_TRANSFER=0`, `ENABLE_HIDDEN_STATE_TRANSFER=0`, `ENABLE_CONTEXT_PACKETS=1`

### Answer Extraction
Parse the system's final summary output for patterns like `@mean_fare[32.20]` using regex. Compare extracted values with gold (with tolerance for floating-point).

### Metrics Collected Per Protocol
- Total input/output tokens
- LLM call count
- Task duration per round
- Context compression ratio (Protocol B only)
- Accuracy: exact match count vs gold answers

## Files
- `/data/mingwei/SynapseX/task/run_group1_comparison.py` — experiment script
- `/data/mingwei/SynapseX/task/result/group1_comparison.json` — output results
