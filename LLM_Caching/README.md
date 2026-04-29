# TalkBuddy — Multi-Agent AI Backend

A FastAPI-based multi-agent system with a chat frontend, semantic caching, PDF Q&A, audio/video transcription, and HubSpot CRM integration via MCP.

---

## Table of Contents

- [Project Overview](#1-project-overview)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Backend](#backend)
- [Agents](#agents)
- [Core Modules](#core-modules)
- [API Endpoints](#api-endpoints)
- [MCP Integration](#mcp-integration)
- [Semantic Cache](#semantic-cache)
- [PDF Store](#pdf-store)
- [Frontend](#frontend)
- [Configuration](#configuration)
- [Setup & Running](#setup--running)
- [Token Optimization](#token-optimization)

---

# Project Overview

TalkBuddy is a **multi-agent AI chatbot platform** that routes user input through a pipeline of specialized AI agents. Each agent handles a distinct aspect of the task (research, code generation, PDF Q&A, CRM operations, etc.), and a final Chat agent synthesizes all outputs into a clean, conversational response.

**Key capabilities:**

- Text chat via WebSocket with real-time streaming
- Voice input via browser microphone (Whisper transcription)
- Audio and video file upload + transcription
- PDF upload, indexing, and semantic Q&A across multiple documents
- HubSpot CRM operations via MCP (Model Context Protocol)
- Semantic caching in Redis to save LLM token costs
- Cache performance dashboard with cost savings metrics

---

## Architecture Overview

```
User Input (text / audio / video / PDF)
        │
        ▼
  Semantic Cache ──► Cache HIT → return instantly
        │ MISS
        ▼
  MCP Tool Resolver + Planner Agent  (run in parallel)
        │
        ├── Research Agent  ┐
        ├── Code Agent      ├── run in parallel
        └── MCP Tool Call   ┘
        │
        ▼
  Chat Agent  (synthesizes all results)
        │
        ▼
  Evaluation Agent  (skipped for chat-only requests)
        │
        ▼
  Save to PostgreSQL + Cache in Redis
        │
        ▼
     Response
```

---

## Project Structure

```
backend/
├── main.py               # FastAPI app entry point
├── config.py             # Environment variables
├── db.py                 # asyncpg connection pool
├── router.py             # All HTTP + WebSocket routes
├── process_task.py       # Central task orchestrator
├── redis_pubsub.py       # Agent-to-agent pub/sub
│
├── agents/
│   ├── planner.py        # Decides which agents to run
│   ├── research.py       # Factual research agent
│   ├── code.py           # Code generation/debug agent
│   ├── chat.py           # Final response synthesizer
│   ├── evaluation.py     # QA evaluator (optional)
│   ├── audio.py          # Whisper transcription
│   ├── video.py          # ffmpeg + audio agent
│   ├── memory.py         # Persist task to PostgreSQL
│   ├── pdf_agent.py      # PDF Q&A with caching
│   └── pdf_store.py      # PDF index + embedding store
│
├── core/
│   ├── groq_client.py    # Groq LLM wrapper
│   ├── redis_client.py   # Async Redis client
│   └── semantic_cache.py # Vector similarity cache
│
└── mcp/
    ├── mcp_client.py     # MCP tool resolver + caller
    └── mcp_server.py     # MCP server

frontend/
├── index.html
├── style.css
└── script.js
```

---

## Backend

### Entry Point — `main.py`

Creates the FastAPI application, applies CORS middleware (open to all origins for development), and mounts the API router.

```python
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
app.include_router(router)
```

> **Note:** For production, replace `allow_origins=["*"]` with your specific frontend domain.

---
### Database — `db.py`

Returns an `asyncpg` connection pool. Called once at startup and stored globally in the router.

```python
async def get_db_pool():
    return await asyncpg.create_pool(DATABASE_URL)
```

---
### Redis Client (`redis_client.py`)

```python
from backend.redis_client import redis
# async aioredis instance, connect via REDIS_URL
```
**File:** 

Provides agent-to-agent messaging over Redis channels. Not currently used in the main pipeline but available for future multi-agent communication patterns.

```python
await publish(channel, message)
async for msg in subscribe(channel): ...
```

---

## Agents

### Planner (`planner.py`)
Analyzes user input and returns a JSON list of agents to invoke.

```python
agents = await planner_agent("explain quicksort")
# → ["research", "chat"]
```

Available agent keys: `research`, `code`, `audio`, `video`, `pdf`, `mcp`, `chat`

---

### Research (`research.py`)
Provides factual, structured answers to knowledge queries. `max_tokens=800`.

---

### Code (`code.py`)
Generates, reviews, or debugs code. Returns markdown code blocks. `max_tokens=900`.

---

### Chat (`chat.py`)
Final synthesizer — receives all agent outputs (truncated to 600 chars each) and produces the user-facing response. `max_tokens=600`.

---

### Evaluation (`evaluation.py`)
Lightweight QA review of agent outputs. **Skipped entirely** when no sub-agents ran (chat-only requests). Each agent output is truncated to 300 chars before the prompt. `max_tokens=150`.

---
### PDF Agent

**File:** `agents/pdf_agent.py`

Handles multi-document PDF question answering.

**`pdf_agent(file_path, question, original_filename)`** — legacy entry point used by `/upload-pdf`. Stores the PDF and optionally answers a question immediately.

**`answer_question(question, pdf_ids)`** — the main Q&A pipeline:

1. Resolve active PDF IDs (all stored PDFs if none specified).
2. Check the Redis Q&A cache (keyed by sorted PDF IDs + question hash).
3. Call `query_pdfs()` to find the top-k most relevant pages by cosine similarity.
4. Ask the LLM if the retrieved pages are `RELEVANT` or `NOT_RELEVANT`.
5. If relevant, generate an answer with source citations.
6. Write the result to the Q&A cache with per-PDF reverse-index keys (for cache invalidation on delete).

**Cache invalidation:** When a PDF is deleted, all `pdf_cache:<pdf_id>:*` keys are deleted from Redis, ensuring stale answers are never served.

---

### Audio (`audio.py`)
Uses `faster-whisper` (base model, int8) to transcribe audio files asynchronously via `asyncio.to_thread`.

---

### Video (`video.py`)
Extracts audio from video using `ffmpeg`, then passes the `.wav` file to the audio agent.

---

### Memory (`memory.py`)
Persists every task to the `ai_task_memory` PostgreSQL table including agent outputs, file blobs, and timestamps.

---

## Core Modules

### Gemini Client (`core/gemini_client.py`)

```python
await ask_gemini(prompt, max_tokens=512)
```

- Model: `gemini-2.5-flash`
- `max_tokens` is required — defaults to `512` (prevents runaway output)
- Tracks per-call and cumulative token usage via `contextvars`

| Agent       | Recommended `max_tokens` |
|-------------|--------------------------|
| Planner     | 60                       |
| Evaluation  | 150                      |
| Chat        | 600                      |
| Research    | 800                      |
| Code        | 900                      |
| PDF Q&A     | 500                      |

---

### Semantic Cache (`core/semantic_cache.py`)

Vector similarity cache using sentence-transformers embeddings stored in Redis.

- **Threshold:** cosine similarity ≥ `0.85` → cache hit
- **TTL:** 24 hours per entry; index TTL 7 days
- **Index cap:** 1000 entries (FIFO eviction)
- Tracks hits, misses, tokens saved, and cost saved in `sem_cache:metrics_json`

```python
result = await get_cache(query)       # returns cached dict or None
await set_cached(query, result)       # stores + updates index
await record_cache_hit(usage_dict)
await record_cache_miss(usage_dict)
stats = await get_cost_savings()
```
**How it works:**

1. **`get_cache(query)`** — encodes the query with SentenceTransformer, loads the index from Redis, and computes cosine similarity against all stored vectors. Returns the cached result if the best score ≥ `SIMILARITY_THRESHOLD` (0.85).

2. **`set_cached(query, result)`** — encodes and stores the new query vector in the Redis index (`sem_cache:index`) alongside the result (TTL: 24 hours; index TTL: 7 days).

**Key Redis keys:**

| Key | Contents |
|---|---|
| `sem_cache:index` | JSON array of `{key, query, vector}` entries |
| `sem_cache:<sha3_hash>` | JSON-serialized response |
| `sem_cache:metrics_json` | Hit/miss stats and cost savings |

**Stats tracking:**

- `record_cache_hit(usage)` — increments hits and saved tokens/cost.
- `record_cache_miss(usage)` — increments misses and used tokens/cost.
- `get_cost_savings()` — returns the full metrics dict for the dashboard.

**Cost rates:**
```
Input:  $0.05 / 1M tokens  ($0.00005 / 1K)
Output: $0.08 / 1M tokens  ($0.00008 / 1K)
```

---


## API Endpoints

### WebSocket

| Endpoint    | Description                              |
|-------------|------------------------------------------|
| `WS /ws`    | Text chat — send string, receive JSON    |
| `WS /ws/mic`| Stream audio bytes, receive transcript + agent result |

### HTTP

| Method | Endpoint              | Description                                      |
|--------|-----------------------|--------------------------------------------------|
| POST   | `/upload-audio`       | Upload audio file → transcribe → agent pipeline  |
| POST   | `/upload-video`       | Upload video file → extract audio → pipeline     |
| POST   | `/upload-pdf`         | Upload single PDF, optionally answer a question  |
| POST   | `/upload-pdfs`        | Upload multiple PDFs at once                     |
| GET    | `/pdfs`               | List all indexed PDFs                            |
| DELETE | `/pdfs/{pdf_id}`      | Delete PDF + evict its cache entries             |
| POST   | `/ask-pdfs`           | Answer a question across stored PDFs             |
| POST   | `/ask-pdf`            | Legacy: answer question from raw PDF text        |
| GET    | `/stats/cost-savings` | Return semantic cache stats                      |
| DELETE | `/cache/clear`        | Clear semantic cache entries                     |
| POST   | `/cache/clear-all`    | Clear cache entries + reset stats metrics        |

---

## MCP Integration

`mcp/mcp_client.py` resolves natural-language user input into MCP tool calls.

Implements a client for a local **Model Context Protocol** server that exposes HubSpot CRM tools and a web search tool.

**`resolve_tool(user_input)`** — maps natural language to the correct MCP tool call using keyword detection:

**Supported objects:** `contacts`, `deals`, `companies`, `tickets`, `quotes`

**Supported actions:** `get`, `create`, `update`, `delete`, `search`

Two modes controlled by `HUBSPOT_MCP_MODE` env var:

| Mode     | Tool prefix              |
|----------|--------------------------|
| `beta`   | `hubspot_mcp_call` (unified) |
| default  | `hubspot_create_contact`, `hubspot_get_deals`, etc. |


| Keyword pattern | Resolved tool |
|---|---|
| `hubspot/crm/contact/deal/…` + `create/add` | `hubspot_create_*` / `crm_create_object` |
| `hubspot/crm/…` + `update/edit/change` | `hubspot_update_*` / `crm_update_object` |
| `hubspot/crm/…` + `delete/remove` | `hubspot_delete_*` |
| `hubspot/crm/deal/company/ticket/quote` | `hubspot_get_*` / `crm_search_objects` |
| `search` | `web_search_mcp` |
| `list mcp tools` / `available tools` | `hubspot_mcp_list_tools` |

When `HUBSPOT_MCP_MODE=beta`, all HubSpot operations route through the unified `hubspot_mcp_call` tool using `crm_create_object`, `crm_update_object`, and `crm_search_objects` sub-operations.

**Helper extractors:**

- `extract_email(text)` — regex for `user@domain.tld`
- `extract_id(text)` — regex for 6+ digit numeric IDs
- `extract_value(text, field)` — extracts the word following a field keyword (e.g., `dealname: SummerPromo`)

---

## PDF Store

`agents/pdf_store.py` manages a folder-based persistent PDF store.

**Layout:**
```
/tmp/pdf_store/
  <pdf_id>/
    original.pdf
    meta.json           # {pdf_id, filename, page_count, uploaded_at}
    pages/1.txt, 2.txt… # per-page extracted text
    embeddings.npy      # float32 (page_count × 768)
```

**Redis index key:** `pdf_store:index` — JSON list of active `pdf_id`s

**`store_pdf(file_bytes, filename)`**

1. Assigns a UUID as `pdf_id`.
2. Extracts per-page text with **pypdf**.
3. Embeds all non-blank pages in batch with SentenceTransformer.
4. Saves the embedding matrix as a NumPy `.npy` file.
5. Writes `meta.json`.
6. Appends the `pdf_id` to the Redis index (`pdf_store:index`).

**`query_pdfs(question, pdf_ids, top_k_per_pdf, score_threshold)`**

1. Embeds the question.
2. For each PDF, loads its `embeddings.npy` and computes cosine similarity for all pages.
3. Returns the top-k pages per PDF with score ≥ `score_threshold` (default 0.50), sorted by score descending.

**`delete_pdf(pdf_id)`**

Removes the folder, updates the Redis index, and evicts all `pdf_cache:<pdf_id>:*` cache entries.

---

## API Reference

### WebSocket: `/ws`

Send a plain text message. Receive a JSON response:

```json
{
  "task_id":    "uuid",
  "results":    { "research": "...", "code": "..." },
  "evaluation": "QA report string",
  "chat":       "Final response for user",
  "mcp":        { ... } | null,
  "usage":      { "input_tokens": 450, "output_tokens": 120 },
  "from_cache": true | false
}
```

### POST `/ask-pdfs`

Request:
```json
{ "question": "What is the refund policy?", "pdf_ids": ["uuid1", "uuid2"] }
```

Response:
```json
{
  "type":       "pdf_answer" | "not_in_pdf",
  "answer":     "The refund policy states…",
  "sources":    [{ "pdf_id": "...", "filename": "doc.pdf", "page": 3, "score": 0.91 }],
  "from_cache": true
}
```

### GET `/stats/cost-savings`

```json
{
  "total_queries":      42,
  "cache_hits":         18,
  "cache_misses":       24,
  "saved_input_tokens": 9000,
  "saved_output_tokens":2400,
  "cost_saved_usd":     0.0006,
  "used_input_tokens":  12000,
  "used_output_tokens": 3200,
  "used_cost_usd":      0.0009
}
```

---


## Frontend

Single-page app (`index.html` + `style.css` + `script.js`).

**Views:**
- **Chatbot** — WebSocket text chat with session history
- **PDF Library** — Upload, browse, select, delete PDFs
- **Cache Stats** — Live hit/miss counters, tokens saved, cost saved

**Key behaviors:**
- If any PDFs are stored → all messages route to `/ask-pdfs` first; falls back to agent pipeline on `not_in_pdf`
- Mic button streams audio via `ws/mic` WebSocket
- Attachment menu supports PDF, audio, video upload
- `marked.js` renders markdown in bot responses

A single-page application built with vanilla HTML. Key structural regions:

| Element | Purpose |
|---|---|
| `.sidebar` | Navigation (Chatbot / PDF Library / Cache Stats), history list, connection status |
| `.topbar` | App title, active agent pills, connection badge |
| `.mcp-panel` | Slide-in panel showing registered MCP tools |
| `#viewChat` | Main chat interface with message window and input dock |
| `#viewPdf` | PDF Library — upload and manage stored PDFs |
| `#viewCache` | Cache performance dashboard |

Fonts: **Syne** (UI) + **JetBrains Mono** (code/numbers).
Markdown rendering: **marked.js** v9.1.6 from cdnjs.

---

### JavaScript (`script.js`)

**Connection management**

Maintains a persistent WebSocket to `/ws` with auto-reconnect (2.5 s backoff). A second WebSocket to `/ws/mic` is created on demand for microphone recording.

**Message routing**

`sendMessage()` checks whether any PDFs are stored. If yes, it routes to `sendPdfStoreQuestion()`; otherwise it sends the text over the main WebSocket.

**Session history**

Chat sessions are stored in memory (`sessions[]`). Each session tracks its message array and title (derived from the first user message). Sessions are rendered in the sidebar grouped by Today / Earlier.

**PDF library**

`fetchStoredPdfs()` loads the PDF list from `/pdfs` on startup. Users can select individual PDFs for scoped Q&A via `togglePdfSelection()`. Deselecting all reverts to searching all PDFs.

**Voice recording**

`startMic()` opens the microphone, visualizes audio on a canvas waveform, records via `MediaRecorder`, sends the blob over the mic WebSocket, and streams back the transcript and agent result.

**Cache dashboard**

`fetchCostSavings()` polls `/stats/cost-savings` and populates the Cache Stats view after every response. `clearAllCache()` calls `/cache/clear-all` and resets the display.

**MCP panel**

`loadMcpTools()` fetches the tool list from the MCP server (port 8001) and renders tool cards with name, description, and provider.

---

## Configuration

All settings loaded from `.env` via `python-dotenv`.

| Variable                  | Description                          |
|---------------------------|--------------------------------------|
| `DATABASE_URL`            | PostgreSQL connection string         |
| `REDIS_URL`               | Redis connection URL                 |
| `GEMINI_API_KEY`          | GEMINI API key                       |
| `EMBEDDING_MODEL`         | Sentence-transformer model name      |
| `MCP_BASE_URL`            | MCP server base URL                  |
| `HUBSPOT_MCP_MODE`        | `beta` or default                    |
| `HUBSPOT_ACCESS_TOKEN`    | HubSpot private app token            |
| `HUBSPOT_CLIENT_ID`       | OAuth client ID                      |
| `HUBSPOT_CLIENT_SECRET`   | OAuth client secret                  |
| `HUBSPOT_REDIRECT_URI`    | OAuth redirect URI                   |
| `HUBSPOT_MCP_BASE_URL`    | HubSpot MCP server URL               |
| `HUBSPOT_MCP_ACCESS_TOKEN`| MCP access token                     |
| `HUBSPOT_MCP_REFRESH_TOKEN`| MCP refresh token                   |
| `PDF_STORE_DIR`           | PDF storage path (default `/tmp/pdf_store`) |

---
## Data Flow

### Text Query
```
User → sendMessage() → WS → process_task()
  1. Cache lookup
  2. resolve_tool() → MCP call
  3. planner_agent()
  4. asyncio.gather(research, code)
  5. evaluation_agent()
  6. chat_agent()
  7. save_task_memory()
  8. set_cached()
→ ws.send_json() → renderBotResponse()
```

### PDF Q&A
```
User → sendPdfStoreQuestion() → POST /ask-pdfs → answer_question()
  1. Redis Q&A cache check
  2. query_pdfs() (embedding similarity)
  3. LLM relevance check
  4. LLM answer + citations
  5. Write cache + reverse-index keys
→ renderMultiPdfAnswer()
```

---

## Caching Strategy

**Semantic cache** — all non-media queries checked before any LLM call. Score ≥ 0.85 = hit (zero tokens used).

**PDF Q&A cache** — keyed by sorted PDF IDs + normalized question. Invalidated per-PDF on delete via reverse-index keys.

| Cache | TTL |
|---|---|
| Semantic result | 24 h |
| Semantic index | 7 days |
| PDF Q&A answer | 12 h |
| PDF Q&A reverse index | 12 h |
| Metrics | No TTL |

---

## Setup & Running

```bash
# 1. Install dependencies
pip install fastapi uvicorn asyncpg redis groq faster-whisper \
            sentence-transformers pypdf numpy python-dotenv httpx pydantic python-multipart

# 2. Create .env (see Configuration table above)

# 3.MCP server
python mcp_server.py --port 8001

# 4. Run
uvicorn backend.main:app --reload --port 8000
```

PostgreSQL table required:

```sql
CREATE TABLE ai_task_memory (
    task_id          TEXT PRIMARY KEY,
    user_input       TEXT,
    planner_output   JSONB,
    research_result  TEXT,
    code_result      TEXT,
    audio_result     TEXT,
    video_result     TEXT,
    evaluation_result TEXT,
    chat_response    TEXT,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP,
    pdf_file         BYTEA,
    audio_file       BYTEA,
    video_file       BYTEA
);
```

---

## Token Optimization

Changes made to reduce LLM token consumption:

| File              | Change                                                               | Saving          |
|-------------------|----------------------------------------------------------------------|-----------------|
| `groq_client.py`  | Added `max_tokens` cap (default 512, was unlimited)                  | ~40–60% output  |
| `planner.py`      | Prompt 200 → 40 tokens; `max_tokens=60`                              | ~85% on planner |
| `research.py`     | Prompt 100 → 20 tokens; `max_tokens=800`                             | ~80% on prompt  |
| `code.py`         | Prompt 100 → 20 tokens; `max_tokens=900`                             | ~80% on prompt  |
| `evaluation.py`   | Inputs truncated to 300 chars; `max_tokens=150`; skipped if no sub-agents ran | ~70%  |
| `chat.py`         | Agent outputs truncated to 600 chars before prompt assembly          | ~50% on long inputs |
| `pdf_agent.py`    | Merged 2 LLM calls (relevance + answer) into 1                       | 1 full call saved per PDF query |
| `process_task.py` | `resolve_tool` + `planner_agent` parallelized; evaluation skipped for chat-only | latency + tokens |
