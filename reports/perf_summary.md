# FitBuddy – Load Test Summary (Phase 6)

- **Date:** 2026-10-03
- **Tool:** Locust 2.46 (`tests/locustfile.py`), headless
- **Command:** `locust -f tests/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000 --csv reports/perf --html reports/perf.html`
- **Server:** `uvicorn app.main:app` (single worker), **demo mode** (no Gemini calls), SQLite (WAL)
- **Machine:** Windows 11 laptop, Python 3.13

| Endpoint | Requests | Failures | Median (ms) | Avg (ms) | Max (ms) |
|---|---:|---:|---:|---:|---:|
| GET / | 552 | 0 | 3 | 3.7 | 58 |
| GET /api/health | 376 | 0 | 3 | 4.0 | 59 |
| GET /nutrition-tip | 337 | 0 | 2 | 3.1 | 23 |
| POST /generate-plan | 168 | 0 | 11 | 16.6 | 357 |
| **Aggregated** | **1433** | **0 (0%)** | **3** | **5.2** | **357** |

Throughput ≈ 24.5 req/s at 50 concurrent users (with 1–3 s think time).

## Against targets

| Target | Result | Status |
|---|---|---|
| Average response < 2 s | 5.2 ms | ✅ |
| Max response < 5 s | 357 ms | ✅ |
| Error rate < 1 % | 0 % | ✅ |

## Notes

- Demo mode measures the application stack itself (FastAPI, Jinja2, SQLAlchemy and SQLite writes).
  Real Gemini generation adds model latency on top; typically several seconds per plan.
- Locust printed a `ValueError: I/O operation on closed file` traceback at shutdown. This is a known
  race in Locust's CSV writer on Windows; the CSV/HTML reports were written completely.

---

# Real-Gemini Timing Run

- **Date:** 2026-10-03, 17:47–17:54 IST
- **Models:** `gemini-3.8-flash` (workout), `gemini-3.5-flash-lite` (tips, and fallback for workouts)
- **Setup:** single uvicorn worker on a Windows 11 laptop over a home connection. Timings are end-to-end
  HTTP times from `curl` or the browser. Model-call times come from the server log
  (`reports/server-live-run1.log`, `reports/server-live.log`).

## Run 1: primary model only (before the fallback existed)

| Request | Result | End-to-end | Model call |
|---|---|---:|---:|
| `GET /nutrition-tip` (muscle gain, first call) | ✅ 200 | 7.74 s | 7.19 s (flash-lite, includes client warm-up) |
| `POST /generate-plan` attempt 1 | ❌ 502 | 16.95 s | 503 ×2 (initial + retry) |
| `POST /generate-plan` attempt 2 | ❌ 502 | 40.18 s | 503 ×2 |
| `POST /generate-plan` attempt 3 | ✅ 200 | 15.28 s | **14.28 s plan** (3.8-flash) + 0.97 s tip |
| `POST /update-plan/1` attempts 1–2 | ❌ 502 | 10.9 s / 13.3 s | 503 ×2 each |
| `POST /update-plan/1` attempt 3 | ✅ 200 | 12.77 s | **12.76 s revision** (3.8-flash) |

**Finding:** Google returned `503 UNAVAILABLE – "This model is currently experiencing high demand"` for
`gemini-3.8-flash` on most calls. With one retry, about half of user requests failed (friendly 502 error,
nothing saved, so error handling worked as designed). **Fix:** `GEMINI_WORKOUT_FALLBACK_MODEL` (default
`gemini-3.5-flash-lite`). After the primary model and its one retry fail with 503/429, or the model is
not found, the request is retried once on the fallback model. A live test with a nonexistent primary model
confirmed the 404 is logged clearly and the fallback returns a valid 7-day plan (6.63 s total).

## Run 2: with fallback (the primary was still overloaded for every call)

| Request | Result | End-to-end | Breakdown |
|---|---|---:|---|
| Browser: submit form → plan page (`POST /generate-workout`) | ✅ | 19.95 s | 503 ×2 on 3.8-flash (~14 s), fallback plan 5.42 s, tip 1.19 s |
| Browser: submit feedback → updated plan (`POST /submit-feedback`) | ✅ | 17.31 s | 503 ×2 (~12 s), fallback revision 5.48 s |
| `POST /generate-plan` | ✅ 200 | 18.18 s | 503 ×2, fallback plan 4.30 s, tip 0.93 s |
| `POST /update-plan/2` | ✅ 200 | 18.00 s | 503 ×2, fallback revision 3.83 s |
| `GET /nutrition-tip` (endurance, warm) | ✅ 200 | 1.13 s | flash-lite 1.13 s |

## Summary

| Operation | Primary model (3.8-flash) | Fallback model (3.5-flash-lite) | Overloaded primary → fallback (end-to-end) |
|---|---:|---:|---:|
| Plan generation | 14.3 s | 4.3–5.4 s | 18–20 s |
| Feedback revision | 12.8 s | 3.8–5.5 s | 17–18 s |
| Nutrition tip | – | 0.9–1.2 s warm (7.2 s cold) | – |

- With the fallback, **5 of 5 requests in run 2 succeeded**, compared with 2 of 6 plan/revision requests in run 1.
- Real-AI latency is far above the demo-mode load-test numbers, which is expected and is why the UI shows a
  "Generating your plan…" loading state. The 2 s target applies to the app stack (demo mode), not to LLM generation.
- All real plans had exactly 7 days, at least one rest day and no markdown, and they passed Pydantic validation
  with no `invalid_output` retries. Revisions applied the feedback (cardio finishers and ≤45-minute sessions;
  bodyweight-only work plus an extra rest day) and kept the rest of the plan's structure.
- Screenshots `01`–`07` and `09` were retaken with these real plans. Because of the outage they show **fallback-model**
  (`gemini-3.5-flash-lite`) output.
