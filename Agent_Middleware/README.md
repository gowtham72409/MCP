# TalkBuddy — Multi-Agent AI Backend

A FastAPI-based multi-agent system with a chat frontend, semantic caching, PDF Q&A, audio/video transcription, file system automation, Human-in-the-Loop review, and HubSpot CRM integration via MCP.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Backend](#backend)
- [Agents](#agents)
- [Core Modules](#core-modules)
- [MCP Integration](#mcp-integration)
- [Admin Dashboard](#admin-dashboard)
- [WebSocket Protocol](#websocket-protocol)
- [API Endpoints](#api-endpoints)
- [Frontend](#frontend)
- [Environment Variables](#environment-variables)
- [Setup & Running](#setup--running)
- [Data Flow](#data-flow)
- [Caching Strategy](#caching-strategy)
- [Token Optimization](#token-optimization)

---

## Project Overview

TalkBuddy is a **multi-agent AI chatbot platform** that routes user input through a pipeline of specialized AI agents. Each agent handles a distinct aspect of the task (research, code generation, PDF Q&A, file system automation, CRM operations, etc.), and a final Chat agent synthesizes all outputs into a clean, conversational response.

**Key capabilities:**

- Text chat via WebSocket with real-time streaming
- Voice input via browser microphone (Whisper transcription)
- Audio and video file upload + transcription
- PDF upload, indexing, and semantic Q&A across multiple documents
- File system automation via natural language (create, search, move, organize, delete)
- HubSpot CRM operations via MCP (Model Context Protocol)
- Semantic caching in Redis to save LLM token costs
- Cache performance dashboard with cost savings metrics
- Human-in-the-Loop (HITL) review for sensitive or destructive tasks
- Admin dashboard for approving, editing, or rejecting flagged actions

---

## Architecture Overview

```
User Input (text / audio / video / PDF)
        |
        v
  Semantic Cache ----> Cache HIT -> return instantly
        | MISS
        v
  HITL Sensitivity Check (Gemini YES/NO)
        |
        +-- Sensitive --> HITL Pipeline (admin review via /admin/ws)
        |                       |
        |                  Admin: approve / edit / reject
        |                       |
        |                  WebSocket -> hitl_answer
        |
        +-- Safe --> MCP Tool Resolver + Planner Agent (parallel)
                          |
                          +-- Research Agent  -+
                          +-- Code Agent      -+-- asyncio.gather
                          +-- FS Agent        -+
                          |
                          v
                    Chat Agent  (synthesizes all results)
                          |
                          v
                    Evaluation Agent  (skipped for chat-only)
                          |
                          v
                    Save to PostgreSQL + Cache in Redis
                          |
                          v
                       Response
```

---

## Project Structure

```
backend/
├── main.py               # FastAPI app entry point
├── config.py             # Environment variables
├── db.py                 # SQLAlchemy async engine + session
├── models.py             # SQLAlchemy ORM model (AiTaskMemory)
├── router.py             # All HTTP + WebSocket routes
├── process_task.py       # Central task orchestrator
├── redis_client.py       # Async Redis client + pub/sub
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
│   ├── fs_agent.py       # File system automation agent (API-facing)
│   ├── fs_chatbot.py     # File system automation standalone CLI
│   ├── pdf_agent.py      # PDF Q&A with caching
│   └── pdf_store.py      # PDF index + embedding store
│
├── core/
│   ├── gemini_client.py  # Gemini LLM wrapper with retry + token tracking
│   ├── redis_client.py   # Async Redis (redis.asyncio)
│   ├── semantic_cache.py # Vector similarity cache
│   ├── hitl_manager.py   # HITL review state + asyncio.Event bus
│   └── middleware.py     # Agent middleware pipeline
│
└── mcp/
    ├── mcp_client.py     # MCP tool resolver + caller
    └── mcp_server.py     # MCP server (HubSpot bridge + OAuth)

frontend/
├── index.html            # Main SPA
├── style.css             # App styles
├── script.js             # Frontend logic
├── admin.html            # Admin HITL dashboard
├── admin.css             # Admin dashboard styles
└── admin.js              # Admin dashboard logic
```

---

## Backend

### Entry Point — `main.py`

Creates the FastAPI application, applies CORS middleware, and mounts the API router.

```python
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
app.include_router(router)
```

> **Note:** Replace `allow_origins=["*"]` with your specific frontend domain in production.

---

### Configuration — `config.py`

Loads all settings from a `.env` file co-located with `config.py` via `python-dotenv`. See [Environment Variables](#environment-variables) for the full list.

---

### Database — `db.py`

Uses **SQLAlchemy async** with `create_async_engine` and `async_sessionmaker`.

```python
engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with AsyncSessionLocal() as session:
        yield session
```

`get_session()` is a FastAPI dependency / async context manager that yields an `AsyncSession`. `expire_on_commit=False` keeps ORM objects accessible after commit.

---

### ORM Models — `models.py`

Defines the `AiTaskMemory` SQLAlchemy model backed by the `ai_task_memory` table.

| Column | Type | Description |
|--------|------|-------------|
| `task_id` | `String` (PK) | UUID for the task |
| `user_input` | `Text` | Original user message |
| `planner_output` | `Text` | JSON list of selected agents |
| `research_result` | `Text` | Research agent output |
| `code_result` | `Text` | Code agent output |
| `audio_result` | `Text` | Audio transcription |
| `video_result` | `Text` | Video transcription |
| `evaluation_result` | `Text` | QA evaluation report |
| `chat_response` | `Text` | Final synthesized response |
| `created_at` | `DateTime` | Row creation time |
| `updated_at` | `DateTime` | Last update time |
| `pdf_file` | `LargeBinary` | Raw PDF bytes |
| `audio_file` | `LargeBinary` | Raw audio bytes |
| `video_file` | `LargeBinary` | Raw video bytes |

Apply schema with `Base.metadata.create_all()` or Alembic.

---

### Redis Client — `redis_client.py`

Uses `redis.asyncio` (the async interface bundled with the `redis` package).

```python
redis = aioredis.from_url(REDIS_URL)

async def publish(channel, message): ...
async def subscribe(channel):        # async generator
    async for msg in pubsub.listen(): yield msg['data']
```

Used by the semantic cache, PDF Q&A cache, and available for agent-to-agent pub/sub messaging.

---

### Router — `router.py`

All HTTP routes and WebSocket endpoints. Instantiates a shared `AgentRunner` without `HITLMiddleware` — HITL is handled inline in the unified WebSocket via `_run_hitl()`.

```python
agent_runner = AgentRunner([LoggingMiddleware(), RetryMiddleware(retries=3), ValidationMiddleware()])
```

See [WebSocket Protocol](#websocket-protocol) and [API Endpoints](#api-endpoints) for full details.

---

### Task Orchestrator — `process_task.py`

Central async function called by all non-HITL routes.

```python
async def process_task(
    user_input: str,
    session: AsyncSession,
    pdf_context: str = "",
    media_type: str = None,
    file_bytes: bytes = None,
    skip_cache: bool = False,
) -> dict
```

**Pipeline steps:**

1. **Cache check** — skipped if `pdf_context` is set or `skip_cache=True`
2. **MCP resolve** — `resolve_tool()` + `call_mcp_tool()` if a CRM keyword detected
3. **Full middleware stack** — builds `AgentRunner` with `Logging`, `Retry`, `Validation`, `HITL` middleware
4. **Planner** — determines which agents to invoke
5. **Parallel execution** — `asyncio.gather(research_agent, code_agent, fs_agent)` for whichever selected
6. **Evaluation** — QA review of combined outputs
7. **Chat** — final synthesis for the user
8. **Persist** — `save_task_memory()` writes to PostgreSQL via `AsyncSession`
9. **Cache store** — stores result in Redis (skipped if `pdf_context` is set)

Returns a dict with `task_id`, `results`, `evaluation`, `chat`, `mcp`, and `usage`.

---

## Agents

### Planner — `planner.py`

Analyzes user input and returns a JSON list of agents to invoke. Falls back to `["chat"]` on parse failure.

```python
agents = await planner_agent("explain quicksort and create a folder for it")
# -> ["research", "fs", "chat"]
```

**Available agent keys:**

| Agent | When selected |
|-------|--------------|
| `research` | Factual questions, deep analysis, explanations |
| `code` | Code generation, debugging, review |
| `audio` | Audio transcription tasks |
| `video` | Video analysis tasks |
| `pdf` | Questions about loaded PDF documents |
| `fs` | File system operations (create, move, delete, organize, search) |
| `mcp` | External tool integrations (HubSpot, Slack, Notion, GitHub) |
| `chat` | General conversation, greetings, result synthesis |

---

### Research — `research.py`

Provides comprehensive, factual, deeply analytical responses. Instructs the LLM to break down complex concepts and avoid superficial answers.

---

### Code — `code.py`

Generates, reviews, or debugs code. Instructs the LLM to use modern standards, appropriate design patterns, and proper markdown code block formatting.

---

### Chat — `chat.py`

Final synthesizer — consumes all agent outputs and MCP data, produces a clean, markdown-formatted, conversational response.

Context keys consumed from the `memory` dict:

| Key | Injected as |
|-----|------------|
| `mcp` | MCP Tool Result (JSON formatted) |
| `research` | Research section |
| `code` | Code section |
| `pdf` | PDF Content (indexed) |
| `fs` | File System Actions |

---

### Evaluation — `evaluation.py`

Lightweight QA review of combined agent outputs. Reports on quality, coherence, completeness, and gaps. Skipped entirely for chat-only requests.

---

### File System Agent — `fs_agent.py` + `fs_chatbot.py`

Natural language to file system operations, powered by Gemini.

#### `fs_agent.py` (API-facing)

Used by `process_task.py` when the planner selects `fs`. Resolves all relative paths against `BASE_DIR` (set via `FS_AGENT_BASE_DIR` env var, defaults to `os.getcwd()`).

**Supported operations:**

| Action | Required Fields | Behavior |
|--------|----------------|----------|
| `create` | `path`, `type` (`folder` or `file`) | Creates a directory tree or empty file |
| `search` | `query` | Recursively globs under `directory` |
| `move` | `source`, `destination` | `shutil.move` with auto-mkdir on destination |
| `organize` | `directory` | Groups files into `Ext/` subfolders by extension |
| `delete` | `target` | `shutil.rmtree` for folders, `unlink` for files |
| `clarify` | `message` | Returns a question asking for missing info (e.g. no move destination) |

`validate_operation()` checks all required fields before execution. Missing fields return a descriptive error string without raising an exception. `resolve_path()` prefixes relative paths with `BASE_DIR`; absolute paths are used as-is. Returns a joined string of execution logs.

#### `fs_chatbot.py` (Standalone CLI)

Interactive REPL running the same Gemini-powered operation parser in a terminal loop — useful for testing without the full backend.

```bash
python backend/agents/fs_chatbot.py
# You: create a folder called reports and move all .csv files into it
# Bot: [Executing] CREATE: ...  [Executing] MOVE: ...
# Bot: Done! What's next?
```

---

### PDF Agent — `pdf_agent.py`

Handles multi-document PDF question answering with Redis Q&A caching.

**`pdf_agent(file_path, question, original_filename)`** — indexes the PDF and optionally answers a question immediately. Used by `POST /upload-pdf`.

**`answer_question(question, pdf_ids)`** — main Q&A pipeline:

1. Resolve active PDF IDs (all stored PDFs if none specified)
2. Check Redis Q&A cache (keyed by sorted PDF IDs + question hash)
3. `query_pdfs()` returns top-4 most relevant pages per PDF by cosine similarity
4. Gemini relevance check: `RELEVANT` or `NOT_RELEVANT`
5. If relevant, generate answer with source citations (filename + page number)
6. Write result to Q&A cache + per-PDF reverse-index keys

**Cache invalidation:** `delete_pdf()` evicts all `pdf_cache:<pdf_id>:*` keys so stale answers are never served after a PDF is removed.

---

### PDF Store — `pdf_store.py`

Manages a folder-based persistent PDF store with embedding-based retrieval.

**Directory layout:**
```
/tmp/pdf_store/
  <pdf_id>/
    original.pdf
    meta.json            # {pdf_id, filename, page_count, uploaded_at}
    pages/1.txt, 2.txt   # per-page extracted text (pypdf)
    embeddings.npy       # float32 matrix (page_count x embedding_dim)
```

**Key functions:**

| Function | Description |
|----------|-------------|
| `store_pdf(bytes, filename)` | Extract pages, batch-embed non-blank pages, save `.npy`, register in Redis index |
| `query_pdfs(question, pdf_ids, top_k_per_pdf, score_threshold)` | Cosine search across PDF matrices; returns hits sorted by score |
| `delete_pdf(pdf_id)` | Remove folder, update Redis index, evict Q&A cache keys |
| `list_pdfs()` | Return all active PDF meta objects |
| `get_pdf_meta(pdf_id)` | Return meta for a single PDF |

`embedd(text)` accepts a single string (1-D vector) or a list of strings (2-D matrix). Blank pages are skipped; their rows are zeroed. `cosine(matrix, q_vec)` computes similarity against all page rows simultaneously via NumPy matrix ops.

---

### Audio — `audio.py`

Uses `faster-whisper` (base model, `int8`) to transcribe audio files asynchronously via `asyncio.to_thread`.

---

### Video — `video.py`

Extracts audio from video using `ffmpeg` (16kHz mono WAV), passes the `.wav` to `audio_agent`, then cleans up the temp file.

---

### Memory — `memory.py`

Persists every task to PostgreSQL using SQLAlchemy `AsyncSession`. Creates an `AiTaskMemory` ORM record with all agent outputs, file blobs, and timestamps, then commits.

---

## Core Modules

### Gemini Client

**File:** `core/gemini_client.py`

```python
await ask_gemini(prompt, max_retries=5)
```

- **Model:** `gemini-2.5-flash`
- **Retry:** exponential backoff — waits `2^(attempt+1)` seconds between retries (2s, 4s, 8s, 16s, 32s)
- **Global tracking:** `call_counter = {"count": N, "total_tokens": N}` — printed after every call
- **Per-task tracking:** `task_usage` (`ContextVar`) — thread-safe `{input_tokens, output_tokens}` per concurrent task

Recommended `max_tokens` by agent:

| Agent | `max_tokens` |
|-------|-------------|
| Planner | 60 |
| Evaluation | 150 |
| Chat | 600 |
| Research | 800 |
| Code | 900 |
| PDF Q&A | 500 |

---

### Semantic Cache

**File:** `core/semantic_cache.py`

Vector similarity cache backed by Redis. Checked before every non-media LLM call.

- **Embedding model:** `EMBEDDING_MODEL` env var (SentenceTransformer)
- **Similarity threshold:** cosine >= `0.85` -> cache hit
- **TTL:** 24 hours per entry; 7-day index TTL; 1,000-entry cap (FIFO)

```python
result = await get_cache(query)
await set_cached(query, result)
await record_cache_hit(usage_dict)
await record_cache_miss(usage_dict)
stats = await get_cost_savings()
```

**Redis keys:**

| Key | Contents |
|-----|----------|
| `sem_cache:index` | JSON array of `{key, query, vector}` |
| `sem_cache:<sha3_hash>` | JSON-serialized response |
| `sem_cache:metrics_json` | Hit/miss counts, token and cost savings |

**Cost rates:** Input `$0.00005/1K`, Output `$0.00008/1K`.

---

### HITL Manager

**File:** `core/hitl_manager.py`

Manages in-memory review state using `asyncio.Event` — zero CPU polling while awaiting admin.

```python
create_review(review_id, question, draft_answer, sources)
feedback = await await_feedback(review_id, timeout=3600.0)
success  = submit_feedback(review_id, {"action": "approve"})
reviews  = get_all_pending()
```

| Function | Description |
|----------|-------------|
| `create_review()` | Registers a new `_Review` slot with an unset `asyncio.Event` |
| `await_feedback()` | Suspends on event (1h default); returns feedback dict or `None` on timeout |
| `submit_feedback()` | Sets the event and attaches the admin's decision dict |
| `get_all_pending()` | Returns all unresolved reviews sorted oldest-first |

---

### Middleware Pipeline

**File:** `core/middleware.py`

Composable async middleware chained by `AgentRunner`.

```python
runner = AgentRunner([
    LoggingMiddleware(),
    RetryMiddleware(retries=3, delay=1.0),
    ValidationMiddleware(),
    HITLMiddleware(),
])
result = await runner.run(research_agent, task)
```

| Middleware | Behavior |
|-----------|----------|
| `LoggingMiddleware` | Logs agent start, success, and failure |
| `RetryMiddleware(retries, delay)` | Retries failed agents N times with a fixed delay |
| `ValidationMiddleware` | Raises `ValueError` if task string is empty |
| `HITLMiddleware` | Intercepts sensitive tasks; suspends until admin reviews |

`HITLMiddleware` is bypassed for `audio_agent`, `video_agent`, `answer_question`, file-path inputs, and empty task strings. The router's shared `agent_runner` omits it since HITL is handled inline in `_run_hitl()`.

---

## MCP Integration

### MCP Server — `mcp/mcp_server.py`

FastAPI app on port `8001` bridging TalkBuddy to HubSpot CRM. `auto_refresh_loop` refreshes the OAuth token every 25 minutes in the background.

**Registered tools:**

| Tool | Description |
|------|-------------|
| `hubspot_get/create/update/delete_contact` | Contact CRUD |
| `hubspot_get/create/update/delete_deal` | Deal CRUD |
| `hubspot_get/create/update/delete_company` | Company CRUD |
| `hubspot_get/create/update/delete_ticket` | Ticket CRUD |
| `hubspot_mcp_call` | Route any call to HubSpot's official beta remote MCP |
| `hubspot_mcp_list_tools` | List all tools on HubSpot's beta MCP server |
| `web_search_mcp` | Web search |

**Endpoints:** `GET /mcp/tools`, `POST /mcp/call`, `GET /oauth/authorize`, `GET /oauth/callback` (PKCE).

---

### MCP Client — `mcp/mcp_client.py`

Keyword-based dispatcher mapping natural language to MCP tool calls.

| Keyword pattern | Resolved tool |
|----------------|---------------|
| `hubspot/crm/...` + `create/add` | `hubspot_create_*` or `crm_create_object` |
| `hubspot/crm/...` + `update/edit/change` | `hubspot_update_*` or `crm_update_object` |
| `hubspot/crm/...` + `delete/remove` | `hubspot_delete_*` |
| `hubspot/crm/deal/company/ticket/quote` | `hubspot_get_*` or `crm_search_objects` |
| `search` | `web_search_mcp` |
| `list mcp tools` / `available tools` | `hubspot_mcp_list_tools` |

Two modes via `HUBSPOT_MCP_MODE`: `beta` (unified `hubspot_mcp_call`) or default (dedicated per-object tools).

Helper extractors: `extract_email()`, `extract_id()` (6+ digit IDs), `extract_value(field)` (word after field keyword).

---

## Admin Dashboard

Served at `admin.html`. Provides a live review queue for HITL-flagged tasks.

| File | Purpose |
|------|---------|
| `admin.html` | Layout — header, queue list, empty state |
| `admin.css` | Dark theme with `--bg`, `--primary`, `--danger`, `--warning` CSS vars |
| `admin.js` | WebSocket connection, queue rendering, review submission |

Connects to `ws://localhost:8000/admin/ws` — server pushes the full pending list every 3 seconds. Auto-reconnects every 3 seconds on disconnect.

**Admin actions:**

| Button | `action` value | Result |
|--------|---------------|--------|
| Approve Default | `approve` | Sends draft answer to user |
| Edit & Send | `edit` | Sends admin's edited textarea content |
| Reject | `reject` | Sends rejection message; agent does not run |

---

## WebSocket Protocol

### `WS /ws` — Unified Chat + HITL

**Client -> Server:**

| `type` | Fields | Description |
|--------|--------|-------------|
| `query` (default) | `text`, `has_pdfs?`, `pdf_ids?` | Standard chat message |
| `hitl_feedback` | `review_id`, `action`, `edited_answer?` | Admin submits review decision |

**Server -> Client:**

| `type` | Fields | Description |
|--------|--------|-------------|
| *(standard)* | `task_id`, `results`, `evaluation`, `chat`, `mcp`, `usage`, `from_cache` | Normal agent pipeline result |
| `hitl_wait` | `message` | Admin review is pending |
| `hitl_answer` | `answer`, `chat`, `sources`, `usage` | Final answer post-review |
| `hitl_timeout` | `answer`, `chat`, `sources` | Admin timed out (1h) |

**Routing logic inside `/ws`:**
```
receive "query"
  +-- cache hit? -> send cached result
  +-- Gemini sensitive check
        YES -> _run_hitl() -> send hitl_wait -> await admin -> send hitl_answer
        NO  -> has_pdfs?
                 YES -> answer_question() -> fallback to process_task if not_in_pdf
                 NO  -> process_task()
```

`_run_hitl()` retrieves candidate sources from PDF store (threshold 0.40) or research agent as fallback, generates a draft answer, suspends on admin feedback, then sends `hitl_answer`. Approved/edited answers are stored in semantic cache.

### `WS /ws/mic`

Receives raw audio bytes, transcribes via `audio_agent`, runs `process_task`. Returns `{"type": "transcript"}` then `{"type": "agent_result"}`.

### `WS /admin/ws`

Pushes `{"reviews": [...]}` every 3 seconds for the Admin Dashboard.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload-audio` | Upload audio -> transcribe -> agent pipeline |
| POST | `/upload-video` | Upload video -> extract audio -> pipeline |
| POST | `/upload-pdf` | Upload single PDF; optionally answer a question |
| POST | `/upload-pdfs` | Upload multiple PDFs at once |
| GET | `/pdfs` | List all indexed PDFs with meta |
| DELETE | `/pdfs/{pdf_id}` | Delete PDF + evict its Q&A cache entries |
| POST | `/ask-pdfs` | Answer a question across stored PDFs |
| POST | `/ask-pdf` | Legacy: answer from raw PDF text |
| GET | `/admin/reviews` | List all pending HITL reviews |
| POST | `/admin/reviews/{review_id}` | Submit approve/edit/reject for a review |
| GET | `/stats/cost-savings` | Return semantic cache stats |
| DELETE | `/cache/clear` | Clear cache entries (keep stats) |
| POST | `/cache/clear-all` | Clear cache entries + reset stats |

**`POST /ask-pdfs` response:**
```json
{
  "type": "pdf_answer | not_in_pdf",
  "answer": "...",
  "sources": [{"pdf_id": "...", "filename": "doc.pdf", "page": 3, "score": 0.91}],
  "from_cache": true
}
```

**Standard WebSocket response:**
```json
{
  "task_id": "uuid",
  "results": {"research": "...", "code": "...", "fs": "..."},
  "evaluation": "QA report",
  "chat": "Final user-facing response",
  "mcp": {"..."},
  "usage": {"input_tokens": 450, "output_tokens": 120},
  "from_cache": false
}
```

---

## Frontend

Single-page app (`index.html` + `style.css` + `script.js`).

| View | Description |
|------|-------------|
| **Chatbot** | WebSocket text chat with sidebar session history |
| **PDF Library** | Upload, browse, select, and delete PDFs |
| **Cache Stats** | Live hit/miss counters, tokens saved, cost saved |

If PDFs are stored, messages route to `/ask-pdfs` first; falls back to agent pipeline on `not_in_pdf`. Mic button streams audio via `/ws/mic` with canvas waveform. `marked.js` renders markdown in bot responses.

| Element | Purpose |
|---------|---------|
| `.sidebar` | Navigation tabs, chat history, connection status |
| `.topbar` | App title, active agent pills, WS connect/disconnect |
| `.mcp-panel` | Slide-in panel listing registered MCP tools |
| `#viewChat` | Main chat + input dock |
| `#viewPdf` | PDF Library |
| `#viewCache` | Cache performance dashboard |

Fonts: **Syne** (UI) + **JetBrains Mono** (numbers/code). Markdown: **marked.js** v9.1.6.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Async PostgreSQL URL (`postgresql+asyncpg://user:pass@host/db`) |
| `REDIS_URL` | Redis URL (`redis://localhost:6379`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `EMBEDDING_MODEL` | SentenceTransformer model name  |
| `MCP_BASE_URL` | MCP server base URL (default `http://localhost:8001`) |
| `HUBSPOT_ACCESS_TOKEN` | HubSpot private app token |
| `HUBSPOT_BASE_URL` | HubSpot API base URL |
| `HUBSPOT_MCP_MODE` | `beta` (unified) or default (direct REST) |
| `HUBSPOT_MCP_BASE_URL` | HubSpot beta MCP server URL |
| `HUBSPOT_CLIENT_ID` | OAuth client ID |
| `HUBSPOT_CLIENT_SECRET` | OAuth client secret |
| `HUBSPOT_REDIRECT_URI` | OAuth redirect URI |
| `HUBSPOT_MCP_ACCESS_TOKEN` | MCP access token |
| `HUBSPOT_MCP_REFRESH_TOKEN` | MCP refresh token |
| `PDF_STORE_DIR` | PDF storage path (default `/tmp/pdf_store`) |
| `FS_AGENT_BASE_DIR` | Base directory for the FS agent (default `os.getcwd()`) |

---

## Setup & Running

```bash
# 1. Install dependencies
pip install fastapi uvicorn "sqlalchemy[asyncio]" asyncpg redis \
            google-genai faster-whisper sentence-transformers pypdf \
            numpy python-dotenv httpx pydantic python-multipart websockets

# 2. Create backend/.env (see Environment Variables above)

# 3. Apply the database schema (add to startup or use Alembic)
#    async with engine.begin() as conn:
#        await conn.run_sync(Base.metadata.create_all)

# 4. Start the MCP server (port 8001)
python backend/mcp/mcp_server.py

# 5. Start the main app (port 8000)
uvicorn backend.main:app --reload --port 8000

# 6. Open the chat UI
open frontend/index.html

# 7. Open the Admin Dashboard (separate tab)
open frontend/admin.html

# 8. (Optional) Run the standalone FS chatbot CLI
python backend/agents/fs_chatbot.py
```

**Manual SQL table** (if not using `Base.metadata.create_all`):

```sql
CREATE TABLE ai_task_memory (
    task_id           TEXT PRIMARY KEY,
    user_input        TEXT,
    planner_output    TEXT,
    research_result   TEXT,
    code_result       TEXT,
    audio_result      TEXT,
    video_result      TEXT,
    evaluation_result TEXT,
    chat_response     TEXT,
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP,
    pdf_file          BYTEA,
    audio_file        BYTEA,
    video_file        BYTEA
);
```

---

## Data Flow

### Standard Text Query

```
User -> WS /ws
  1. Semantic cache lookup
  2. Gemini sensitivity check
  3. Safe -> process_task()
       a. resolve_tool() for MCP dispatch
       b. planner_agent() -> agent list
       c. asyncio.gather(research, code, fs)
       d. evaluation_agent()
       e. chat_agent()
       f. save_task_memory() -> PostgreSQL (SQLAlchemy AsyncSession)
       g. set_cached() -> Redis
-> ws.send_json(result)
```

### HITL Flow (Sensitive Query)

```
User -> WS /ws -> Gemini: sensitive = YES
  1. query_pdfs() (threshold 0.40) -> fallback research_agent
  2. Gemini: draft_answer from sources
  3. create_review() + ws.send_json({type: "hitl_wait"})
  4. await_feedback() -- coroutine suspends (up to 1h)
  5. Admin Dashboard polls /admin/ws (every 3s)
  6. Admin clicks Approve / Edit / Reject
  7. POST /admin/reviews/{id} -> submit_feedback()
  8. Coroutine resumes:
       approve -> draft_answer
       edit    -> admin's edited text
       reject  -> rejection message
  9. Approved/edited -> set_cached()
-> ws.send_json({type: "hitl_answer"})
```

### PDF Q&A

```
User -> POST /ask-pdfs -> answer_question()
  1. Redis Q&A cache check (sorted pdf_ids + question hash)
  2. query_pdfs() -> cosine similarity across page embedding matrices
  3. Gemini relevance check (RELEVANT / NOT_RELEVANT)
  4. Gemini answer + source citations
  5. set_qa_cache() + per-pdf_id reverse-index keys
-> return result
```

### File System Query

```
User -> "create a folder called reports" -> WS /ws
  1. planner: ["fs", "chat"]
  2. fs_agent():
       a. Gemini -> JSON operations list
       b. validate_operation() per op
       c. execute: mkdir / touch / shutil.move / rmtree / rglob
       d. return execution log
  3. chat_agent() wraps log in conversational response
-> ws.send_json(result)
```

---

## Caching Strategy

| Cache | Key pattern | TTL |
|-------|-------------|-----|
| Semantic result | `sem_cache:<sha3_hash>` | 24 h |
| Semantic index | `sem_cache:index` | 7 days |
| PDF Q&A answer | `pdf_qa:<hash>` | 12 h |
| PDF Q&A reverse index | `pdf_cache:<pdf_id>:<hash>` | 12 h |
| Cache metrics | `sem_cache:metrics_json` | No TTL |

Semantic cache is checked before every non-media LLM call. A cosine score >= 0.85 returns the cached result with zero tokens consumed. PDF Q&A reverse-index keys enable instant per-PDF cache invalidation on delete without scanning all cache entries.

---

## Token Optimization

| File | Change | Saving |
|------|--------|--------|
| `gemini_client.py` | Exponential backoff; `task_usage` ContextVar for concurrent tracking | Avoids wasted calls on transient errors |
| `planner.py` | Compact prompt; JSON-only output; falls back gracefully | ~85% on planner overhead |
| `research.py` | Concise system prompt with focused guidelines | ~80% on prompt overhead |
| `code.py` | Concise system prompt with focused guidelines | ~80% on prompt overhead |
| `evaluation.py` | Skipped entirely for chat-only requests | ~70% reduction |
| `chat.py` | Agent outputs truncated to 600 chars before assembly | ~50% on long inputs |
| `pdf_agent.py` | Focused relevance + answer calls; Redis Q&A cache | 1 full call saved per cache hit |
| `process_task.py` | `resolve_tool` + `planner_agent` run in parallel; `skip_cache` flag | Latency + token reduction |
| `fs_agent.py` | `clarify` action prevents execution on ambiguous input | Avoids retries from failed ops |
| `hitl_manager.py` | `asyncio.Event` suspension — zero CPU polling during admin review | Zero overhead during review wait |