"""Performance measurement script for D7 report generation.
Measures real hardware environment, model latencies, DB latency, API latency, and queue throughput.
"""
import os
import platform
import sys
import time
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.core.jobs.job import Job, JobType
from app.core.jobs.queue import JobQueue
from app.core.jobs.worker import JobWorker
from app.database.connection import engine
from app.stages.stage3_identity.matcher_factory import create_face_matcher
from app.stages.stage3_identity.identity_service import IdentityService
from fastapi.testclient import TestClient
from app.main import app
from sqlalchemy import text


def get_hardware_info():
    cpu_count = os.cpu_count() or 1
    py_ver = platform.python_version()
    os_name = f"{platform.system()} {platform.release()}"
    machine = platform.machine()
    processor = platform.processor()
    return {
        "cpu_cores": cpu_count,
        "python": py_ver,
        "os": os_name,
        "machine": machine,
        "processor": processor,
    }



def measure_identity():
    id_service = IdentityService()
    identity_samples = backend_dir.parent / "data/raw/identity_validation/genuine"
    ref_img = str(identity_samples / "pair01_reference.jpg")
    live_img = str(identity_samples / "pair01_live.jpg")

    if not Path(ref_img).exists():
        return {"cold_ms": 0, "warm_avg_ms": 0}

    # Warmup / cold start
    t0 = time.perf_counter()
    id_service.verify("C001", "MEASURE_S0", ref_img, live_img)
    cold_ms = round((time.perf_counter() - t0) * 1000, 2)

    # Warm runs
    warm_times = []
    for i in range(5):
        t = time.perf_counter()
        id_service.verify("C001", f"MEASURE_S{i+1}", ref_img, live_img)
        warm_times.append((time.perf_counter() - t) * 1000)

    return {
        "cold_ms": cold_ms,
        "warm_avg_ms": round(sum(warm_times) / len(warm_times), 2),
        "warm_min_ms": round(min(warm_times), 2),
        "warm_max_ms": round(max(warm_times), 2),
    }


def measure_database():
    latencies = []
    with engine.connect() as conn:
        for _ in range(50):
            t = time.perf_counter()
            conn.execute(text("SELECT 1"))
            latencies.append((time.perf_counter() - t) * 1000)

    return {
        "avg_ms": round(sum(latencies) / len(latencies), 3),
        "p50_ms": round(sorted(latencies)[len(latencies)//2], 3),
        "p95_ms": round(sorted(latencies)[int(len(latencies)*0.95)], 3),
    }


def measure_api():
    client = TestClient(app)
    endpoints = ["/health", "/ready"]
    results = {}
    for ep in endpoints:
        times = []
        for _ in range(30):
            t = time.perf_counter()
            client.get(ep)
            times.append((time.perf_counter() - t) * 1000)
        results[ep] = {
            "avg_ms": round(sum(times) / len(times), 2),
            "p50_ms": round(sorted(times)[len(times)//2], 2),
            "p95_ms": round(sorted(times)[int(len(times)*0.95)], 2),
        }
    return results


def measure_queue():
    queue_dir = backend_dir / "data/outputs/measure_jobs"
    queue = JobQueue(storage_dir=str(queue_dir))
    enqueue_times = []
    for i in range(50):
        t = time.perf_counter()
        queue.enqueue(
            job_type=JobType.INTERVIEW_AUDIO.value,
            session_id=f"SESS_M_{i}",
            candidate_id=f"CAND_M_{i}",
        )
        enqueue_times.append((time.perf_counter() - t) * 1000)

    # Cleanup
    import shutil
    shutil.rmtree(queue_dir, ignore_errors=True)

    return {
        "enqueue_avg_ms": round(sum(enqueue_times) / len(enqueue_times), 3),
        "enqueue_p95_ms": round(sorted(enqueue_times)[int(len(enqueue_times)*0.95)], 3),
    }


def measure_memory():
    import tracemalloc
    current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0)
    return {"current_mb": round(current / (1024 * 1024), 2), "peak_mb": round(peak / (1024 * 1024), 2)}



if __name__ == "__main__":
    print("Gathering hardware and performance metrics...")
    hw = get_hardware_info()
    print("Hardware:", hw)
    ident = measure_identity()
    print("Identity:", ident)
    db = measure_database()
    print("Database:", db)
    api = measure_api()
    print("API:", api)
    q = measure_queue()
    print("Queue:", q)
    mem = measure_memory()
    print("Memory RSS:", mem)
