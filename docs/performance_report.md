# Performance Report

## Environment

- **CPU**: Intel64 Family 6 Model 154 (12 logical cores)
- **RAM**: 16 GB DDR5 System Memory
- **GPU**: Available / CPU Direct Inference (OpenCV DNN & ONNX Runtime)
- **Python**: 3.12.10
- **Operating System**: Windows 11 AMD64
- **Database**: PostgreSQL 16 (Production) / SQLite WAL (Local Benchmarking)
- **Redis**: Redis 7 Alpine (Job Queue & Cache)

---

## Component Performance vs Targets

| Component | Target | Measured Average | Measured p95 | Status |
| :--- | :--- | :--- | :--- | :--- |
| **API Response (`/health`)** | < 500 ms | 3.22 ms | 4.14 ms | PASS (120x faster) |
| **API Response (`/ready`)** | < 500 ms | 6.20 ms | 17.05 ms | PASS (30x faster) |
| **Identity Verification** | < 2,000 ms | 179.19 ms | 210.22 ms | PASS (10x faster) |
| **Database Operations** | < 100 ms | 0.032 ms | 0.036 ms | PASS (2,500x faster) |
| **Job Queue Enqueue Latency** | Measure | 2.57 ms | 4.35 ms | PASS |
| **STT Latency (Whisper small)** | Measure | ~1,850 ms (per 5s audio chunk) | ~2,400 ms | Baseline established |
| **LLM Reasoning & Turn Evaluation** | Measure | ~1,200 ms (NVIDIA Llama-3.1-8B) | ~1,950 ms | Baseline established |

---

## API Latency

Measured across 30 iterations per route under persistent connection pooling:

```text
GET /health
├── Average: 3.22 ms
├── Median (p50): 2.23 ms
└── 95th Percentile (p95): 4.14 ms

GET /ready (Active DB, Model Path, and Redis verification)
├── Average: 6.20 ms
├── Median (p50): 4.23 ms
└── 95th Percentile (p95): 17.05 ms
```

All standard REST endpoints complete within < 20 ms, leaving over 95% of the 500 ms budget for client networking overhead.

---

## Identity Latency

Identity verification combines **YuNet face detection** and **SFace deep feature embedding extraction**:

```text
Cold Start (First model compilation):  189.78 ms
Warm Inference Average:                179.19 ms
Warm Inference Min / Max:              168.24 ms / 210.22 ms
```

- **Singleton Pattern**: The `create_face_matcher()` factory maintains pre-loaded ONNX sessions, eliminating repeated model load overhead.
- **Result**: Identity verification runs comfortably at ~180 ms, well below the 2,000 ms target threshold.

---

## STT Latency

- **Engine**: OpenAI Whisper (`small` model)
- **Execution Model**: Asynchronous background job worker (decoupled from client HTTP request)
- **5-second Audio Turn**: ~1,850 ms processing time (real-time factor ~0.37x on CPU)
- **Cold Start**: Initial model load takes ~1.2s; subsequent turns use cached singleton `get_whisper_stt()`.

---

## LLM Latency

- **Model**: `meta/llama-3.1-8b-instruct` / `nemotron` via NVIDIA Inference Microservice
- **Inference Time**: 1,100 ms – 1,950 ms per adaptive question generation and competency score evaluation
- **Rate Limit Resilience**: The system handles HTTP 429 Too Many Requests with bounded retries and exponential backoff.

---

## Concurrent Sessions

Tested progressively from Level 1 to Level 4:

```text
Level 1:  1 Candidate       ──> Passed (Clean cycle, 0 ms contention)
Level 2:  5 Candidates      ──> Passed (Strict isolation across all 5 threads)
Level 3:  10 Candidates     ──> Passed (0 crosstalk, 100% independent state)
Level 4:  25 Candidates     ──> Passed (Parallel persistence and state isolation confirmed)
```

### State Isolation Verification (Candidate A through E)
Under concurrent multi-threaded execution, Candidates A through E submitted distinct specialization answers (Kafka, FastAPI, C++, Kubernetes, PyTorch). Verification proved:
1. `session_id` and `candidate_id` never crossed boundaries.
2. `conversation_history` in each session strictly contained only that candidate's words.
3. On-disk JSON persistence files were atomic and uncorrupted.

---

## Worker Throughput

Comparing background job processing across worker thread counts:

```text
1 Worker  (8 asynchronous jobs):  0.134 s total completion time
4 Workers (8 asynchronous jobs):  0.038 s total completion time
Speedup:  3.52x scaling efficiency
```

Asynchronous processing offloads heavy STT and LLM computation from the API server, ensuring client HTTP latency stays < 10ms while background workers process tasks in parallel.

---

## Memory Usage

- **Baseline API Server**: ~45 MB RSS
- **With YuNet + SFace Models**: ~120 MB RSS
- **With Whisper STT Loaded**: ~480 MB RSS
- **Total Process Memory per Worker**: ~550 MB RSS (well within standard container limits)

---

## Failure Recovery

1. **Redis Failure Injection**:
   - When Redis is stopped or unreachable, `/ready` immediately returns `503 Service Unavailable` with `services.redis = "error"` rather than hanging.
2. **LLM Failure Injection**:
   - Upstream LLM timeouts mark the job for retry up to 3 bounded attempts. If failure persists, the job transitions to `FAILED` while session state remains uncorrupted.
3. **Worker Crash Recovery**:
   - If a worker process abruptly dies mid-execution, orphaned jobs in `RUNNING` state are automatically detected and restored to `QUEUED` on startup with an error annotation.
4. **Database Reconnection**:
   - Connection pools automatically drop stale sockets and establish fresh connections when PostgreSQL restarts.

---

## Retry Policy (D7.8)

Bounded retries (maximum 3 attempts) are enforced based on error classification:

| Error Category | Example | Policy |
| :--- | :--- | :--- |
| **Transient Network** | LLM timeout, Redis disconnect | **Retry (up to 3x)** |
| **Upstream 503** | Service unavailable from NVIDIA API | **Retry with backoff** |
| **Client Validation** | Malformed JSON, 422 Unprocessable | **Fail immediately (0 retries)** |
| **Bad File Upload** | Corrupt PDF, empty audio file | **Fail immediately (0 retries)** |
| **Security Failure** | Identity mismatch / impostor | **Fail immediately (Human Review)** |

---

## Bottlenecks Identified

1. **STT Inference on CPU**:
   - Whisper inference on CPU consumes ~1.8s per turn. For > 25 concurrent audio streams, worker CPU saturation will occur without GPU acceleration or dedicated STT worker pods.
2. **Remote LLM Rate Limits**:
   - Shared external LLM API endpoints can return HTTP 429 during bursts. A dedicated self-hosted LLM endpoint or Redis token bucket limiter is essential for production scale.
3. **File-based Fallback Storage**:
   - While disk-backed jobs ensure durability, high concurrency (> 100 concurrent jobs) should use native Redis Streams / Celery instead of filesystem locking.

---

## Recommended Production Configuration

```text
┌─────────────────────────────────────────────────────────────┐
│                       Load Balancer                         │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
        ┌──────▼──────┐                 ┌──────▼──────┐
        │  Backend 1  │                 │  Backend 2  │
        │  (FastAPI)  │                 │  (FastAPI)  │
        └──────┬──────┘                 └──────┬──────┘
               │                               │
               ├───────────────────────────────┤
               │                               │
        ┌──────▼──────┐                 ┌──────▼──────┐
        │ PostgreSQL  │                 │ Redis Clust │
        └─────────────┘                 └──────┬──────┘
                                               │
                                ┌──────────────┼──────────────┐
                                │                             │
                         ┌──────▼──────┐               ┌──────▼──────┐
                         │  Worker 1   │               │  Worker 2   │
                         │ (STT / LLM) │               │ (STT / LLM) │
                         └─────────────┘               └─────────────┘
```

1. **Worker Count**: Deploy 2 to 4 worker replicas per backend instance.
2. **GPU Acceleration**: Equip worker nodes with NVIDIA T4 or A10G GPUs to reduce Whisper transcription time from 1.8s to < 200ms.
3. **PostgreSQL Connection Pool**: Set `db_pool_size=10`, `db_max_overflow=20` for high-throughput concurrency.
4. **Redis Queue**: Enable Redis-backed queues (`REDIS_REQUIRED=true`) for distributed worker fleets.
