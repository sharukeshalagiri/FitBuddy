# FitBuddy – Repository Audit

- **Date:** 2026-10-03
- **Scope:** every tracked file in the repo (commit `41770b5`), all 22 phase PDFs (read with `pdftotext`),
  a fresh clone of `origin/main`, and edge-case probes against the app in demo mode with a throwaway DB.
- **Change made during the audit:** added `.gitattributes` (`reports/** linguist-generated=true`). No code
  was changed.

## Language bar after the `.gitattributes` fix

Before the fix, `reports/perf.html` (956 KB) outweighed all the source code together (about 96 KB), so
GitHub showed the repo as mostly HTML. With `reports/**` marked as generated, GitHub should count only
these files (PDF, PNG, Markdown, CSV, INI and `.env.example` don't count toward the bar):

| Language | Files | Bytes | Share |
|---|---|---:|---:|
| Python | `app/*.py`, `tests/*.py` | 71,326 | **74.3 %** |
| HTML | `app/templates/*.html` (Jinja templates, including inline JS) | 13,906 | 14.5 % |
| CSS | `app/static/css/style.css` | 10,744 | 11.2 % |

GitHub recalculates the language bar in the background, so it can take a few minutes after the push to update.

## Checks run

| Check | Result |
|---|---|
| `pytest -q` (local venv) | ✅ **35 passed** in 1.9 s; 1 Starlette deprecation warning (httpx TestClient) |
| Fresh clone → `python -m venv` → `pip install -r requirements.txt` → `pytest` | ✅ installed in 1 m 22 s (Python 3.13.7, FastAPI 0.142, Starlette 1.7, SQLAlchemy 2.1, google-genai 2.28); 35 passed |
| Fresh clone → `uvicorn app.main:app` with no `.env` | ✅ starts in demo mode; `/` 200, `/api/health` ok, form POST → 303 `/plan/1` |
| Secrets in tracked files and history | ✅ none. `.env`, `*.db` and zips have never been committed. Logs in `reports/` contain only localhost requests and Gemini endpoint URLs, with no keys |
| Unused imports (pyflakes) | 1 found (see L-1) |
| Docs vs code: test count, routes, model IDs | ✅ "35 tests", the route tables and `gemini-3.8-flash` / `gemini-3.5-flash-lite` agree across README, PDFs and code |
| Docs vs load-test results | ❌ the README still has the old run (see H-2) |

---

## 🔴 High: fix before submission

### H-1 · Default `SECRET_KEY` lets anyone forge the admin cookie
- **Where:** `app/config.py:27`, `.env.example:7`, `app/routes.py:30`
- **What's wrong:** if `SECRET_KEY` is unset, as in the advertised zero-config start, the key is the public
  string `change-me`. Anyone who reads the repo can mint a valid cookie with
  `URLSafeTimedSerializer("change-me", salt="fitbuddy-admin").dumps("admin")` and open the admin dashboard
  and delete users without the password. **Verified:** a forged cookie returned 200 with the dashboard.
  The same applies to `ADMIN_PASSWORD=admin123`.
- **Fix:** if `SECRET_KEY` is unset or `change-me`, use `secrets.token_urlsafe(32)` at startup (sessions
  reset on restart, which is fine) and log a warning. Also log a warning when `ADMIN_PASSWORD` is still
  `admin123`. Leave `SECRET_KEY` empty in `.env.example`. Add a test that a cookie signed with
  `change-me` is rejected.

### H-2 · README load-test numbers are from the old run
- **Where:** `README.md:204`
- **What's wrong:** it says "1,433 requests, 0 failures, 5 ms average, 357 ms max". The official run (in
  `reports/perf_summary.md`, the Performance Testing PDF and the Project Documentation PDF) is **1,457
  requests, 0 failures, 5.4 ms average, 77 ms max, 24.5 req/s**, plus CPU about 4 % of one core and
  memory about 81 MB. An evaluator comparing the README with the PDFs will notice.
- **Fix:** update the line to the new numbers, add one line on CPU and memory, and mention
  `python tests/resource_monitor.py`.

### H-3 · README phase table leaves out the main documentation PDF
- **Where:** `README.md:17`
- **What's wrong:** the Phase 7 row lists only "Project Executable Files", not "FitBuddy Project
  Documentation" (the 25-page report).
- **Fix:** add it to the row.

### H-4 · No demo video link
- **Where:** `README.md` (none); `7.Project Documentation/Project Executable Files.pdf` (items 10 and
  "Demo Video Link": "To be added by the team (link in repository README)")
- **What's wrong:** the PDF promises a video link in the README, but there isn't one. Phase 8
  (Demonstration) is graded, and evaluators usually look for the video first.
- **Fix:** record the walkthrough, upload it (YouTube unlisted or Google Drive with link sharing on) and
  add a "Demo video" link near the top of the README. Then update the PDF row or leave it if it says
  "see README".

---

## 🟠 Medium: worth fixing

### M-1 · Any visitor can read or revise any user's plan (IDOR)
- **Where:** `app/routes.py:142-166` (`/plan/{user_id}`, `/submit-feedback` hidden `user_id`),
  `app/routes.py:253-272` (`/update-plan/{user_id}`, `/api/users/{user_id}/plans`)
- **What's wrong:** user IDs are sequential, and these routes don't check who is asking. **Verified:**
  `GET /api/users/{id}/plans` returns another user's name, age and weight without authentication, and
  `POST /update-plan/{id}` revises their plan. The README discloses this (line 249), but the admin
  password then only protects the dashboard view, not the data behind it.
- **Fix (fits the spec):** add a random `public_id` (`secrets.token_urlsafe(8)`) column and use it in
  user-facing URLs and the hidden form field, or at least require the admin cookie for
  `/api/users/{id}/plans`. Keep the integer `id` internally.

### M-2 · An empty `ADMIN_PASSWORD` accepts an empty password
- **Where:** `app/config.py:26`, `app/routes.py:181`
- **What's wrong:** if `.env` has `ADMIN_PASSWORD=` (empty), the login form accepts an empty password
  (the browser's `required` check is bypassed by any client). **Verified:** returned 303 and a session cookie.
- **Fix:** treat an empty password as "admin disabled" (always 401), or fall back to a generated one and
  log it.

### M-3 · Plan schema doesn't enforce the documented rules
- **Where:** `app/schemas.py:13-41`
- **What's wrong:** CLAUDE.md and the system prompt require days 1–7 and at least one rest day, and
  sensible sets and reps. The validator only checks `len(days) == 7`. **Verified:** a plan with seven
  "day 1" entries, no rest day, `sets: -5`, `rest_seconds: -1`, empty `reps` and no safety notes passes
  validation and would be saved and rendered.
- **Fix:** `sets: Optional[int] = Field(None, ge=1, le=10)`,
  `rest_seconds: Optional[int] = Field(None, ge=0, le=600)`, `reps: str = Field(min_length=1)`,
  `safety_notes: list[str] = Field(min_length=1)`, plus a model validator that sets
  `[d.day for d in days] == [1..7]` (or renumbers them) and requires at least one `is_rest_day`.
  An invalid plan then triggers the existing retry, so this fixes it with no other code changes.

### M-4 · Demo-mode revisions ignore the user's experience and age
- **Where:** `app/demo_data.py:266`
- **What's wrong:** "More cardio" always inserts
  `_session("cardio", ..., "medium", "intermediate", False)`. **Verified:** a 15-year-old beginner gets
  Jogging, Rowing Machine and Side Plank. That breaks the "beginner → bodyweight/machines" and teen
  rules, and it's the path shown in demos and screenshots.
- **Fix:** pass `user` (or experience, intensity and age) into `demo_revise_plan` from
  `updated_plan.py:23`, as the Gemini path already does, and use them in `_session(...)`.

### M-5 · Worst-case request time is several minutes
- **Where:** `app/gemini_client.py:48-125`, `app/routes.py:46-54`
- **What's wrong:** the retries multiply. `_call` retries once, `_structured_once` repeats `_call` on
  invalid JSON, `generate_structured` then tries the fallback model, and the tip call runs afterwards.
  With 45 s timeouts, one form submit can wait about 4–5 minutes (for example, primary and fallback both
  timing out with a retry each is 4 × 45 s, plus the tip at 2 × 45 s). The browser shows a spinner the
  whole time. CLAUDE.md asks for "timeout ~45 s; 1 retry".
- **Fix:** set an overall deadline (for example 60 s) in `generate_structured` and skip further attempts
  once it has passed. Lower the tip timeout to about 10 s, since the curated tip already serves as a
  fallback.

### M-6 · Free-text goal goes into the prompt without delimiters
- **Where:** `app/gemini_generator.py:31`, `app/updated_plan.py:28`, `app/gemini_flash_generator.py:18`
- **What's wrong:** feedback is fenced in `<feedback>` tags (README line 48), but the "Other" goal (up to
  200 characters of user text) is put straight into all three prompts. The README's "prompt-injection
  hardening" claim only covers feedback.
- **Fix:** wrap the goal the same way (`<goal>…</goal>` with `<`/`>` replaced) and add one sentence to
  each system prompt saying to treat it as data.

### M-7 · Version numbers can collide under concurrent feedback
- **Where:** `app/database.py:109-122`, model at `app/database.py:58-63`
- **What's wrong:** `_next_version` reads `max(version)+1` and then inserts, and nothing makes
  `(user_id, version)` unique. Two simultaneous revisions (double-click, two tabs) can both become, for
  example, v3. The history then shows duplicates, and `get_plan_version` is ambiguous.
- **Fix:** add `UniqueConstraint("user_id", "version")` to `Plan.__table_args__` and retry once on
  `IntegrityError`. The submit button is already disabled on click, which helps for the browser.

### M-8 · Dependencies aren't pinned
- **Where:** `requirements.txt:1-11`
- **What's wrong:** all entries are `>=`. A fresh install today resolves to Starlette 1.7, which already
  warns that `httpx` TestClient support is deprecated. A future major release could break the evaluator's
  install or the tests.
- **Fix:** pin the versions that were tested (from `pip freeze` in the venv, for example
  `fastapi==0.142.2`, `starlette==1.7.0`, `sqlalchemy==2.1.3`, `google-genai==2.28.0`, `pydantic==2.13.5`)
  or use `~=`. Optionally move pytest, httpx and locust to `requirements-dev.txt`. `psutil` (used by
  `tests/resource_monitor.py`) currently comes in only through Locust, so list it explicitly.

---

## 🟢 Low: nice to have

### L-1 · Unused import
- `app/main.py:8` – `HTMLResponse` is imported but never used. Remove it.

### L-2 · Dead or unused code
- `app/database.py:137` `get_original_plan` and `app/database.py:143` `get_plan_version` are never
  called. `get_original_plan` is a name from the brief, so keep it, but use it in `get_all_users`.
  `_render_plan` (`app/routes.py:92-101`) loads the whole history instead of calling `get_plan_version`.
- `app/demo_data.py:156` – `_recovery_day(day, experience)` never uses `experience`.

### L-3 · Missing docstrings and return type hints
- `app/routes.py` has 13 public route functions with no docstring (`index`, `view_plan`,
  `api_nutrition_tip`, `api_plan_history`, `api_health`, …). For the API routes the docstring is the
  description in `/docs`, so `/nutrition-tip`, `/api/users/{id}/plans` and `/api/health` appear there
  without descriptions.
- `app/database.py:104-186` CRUD helpers and `app/schemas.py` validators have no docstrings.
- Route functions and `get_client` / `make_engine` have no return annotations.
- **Fix:** add one-line docstrings, especially on the JSON API routes. This also helps the
  "Code-Layout, Readability and Reusability" mark.

### L-4 · Long function
- `app/demo_data.py:251` `demo_revise_plan` is 50 lines handling four rule blocks. Split it into
  `_add_cardio`, `_add_rest`, `_shorten`, `_bodyweight` helpers driven by a list of rules.

### L-5 · Imports inside functions
- `app/main.py:43`, `app/routes.py:63`, `app/routes.py:180` import inside functions (`http_exception_handler`,
  `demo_nutrition_tip`, `hmac`). The lazy `google.genai` imports in `gemini_client.py` are deliberate
  (faster start in demo mode); the others aren't. Move them to the top of the file.

### L-6 · Invalid path parameters return JSON to browsers
- `app/main.py:40` handles `HTTPException` but not `RequestValidationError`. **Verified:** `/plan/abc` in
  a browser returns a raw JSON 422.
- **Fix:** register the same handler for `RequestValidationError`, rendering `error.html` for
  `Accept: text/html`.

### L-7 · Health endpoint always reports `"status": "ok"`
- `app/routes.py:278` – it returns `ok` even when `db` is `error`. Return `"degraded"` and HTTP 503 when
  the DB check fails.

### L-8 · Admin dashboard query count
- `app/database.py:154-167` loads every user's full plan list (all `plan_json`) one user at a time (N+1).
  That's fine at demo scale. Use `selectinload(User.plans)` or fetch only v1 and the latest version.

### L-9 · Goal keyword matching is loose
- `app/demo_data.py:138` – substring checks map "lean muscle" and "reduce fatigue" to *weight loss*
  (verified), and "brunch" would match *endurance* ("run"). Check "muscle" before "lean", and match
  whole words with `re.search(r"\b…\b")`.

### L-10 · Cookie and CSRF hardening
- `app/routes.py:185` – the cookie has `httponly` and `samesite=lax` (good) but not `secure` (needed over
  HTTPS). `GET /admin/logout` (`app/routes.py:190`) and the delete POST have no CSRF token, and the login
  has no rate limiting. These are already listed in README "Known limitations". Optional: set
  `secure=request.url.scheme == "https"`.

### L-11 · Config robustness
- `app/config.py:21` – a non-numeric `GEMINI_TIMEOUT_SECONDS` crashes on import. Parse it with a fallback.
- `app/config.py:28` – the default `sqlite:///./fitbuddy.db` depends on the working directory. Starting
  from another folder creates a second, empty DB. Base it on `BASE_DIR`.
- `.env.example` doesn't list `GEMINI_TIMEOUT_SECONDS`, which the README documents (line 154).

### L-12 · Repo hygiene
- **No `LICENSE`.** Add MIT (or whatever the track allows). GitHub shows "No license" on the repo page.
- **Filename with a trailing space:** `1. Brainstorming & Ideation/Define Problem Statements .pdf`. This
  causes problems in scripts, ZIP extraction on some tools and URLs. Rename it to
  `Define Problem Statements.pdf`.
- **Phase 5 folder has no pointer to the code.** The template expects the app in
  `5. Project Development Phase/`. The README says the source is at the root, but a reviewer browsing that
  folder sees only PDFs. Add a short `5. Project Development Phase/README.md` that links to `../app`.
- **README file tree is incomplete** (`README.md:237`): `tests/` doesn't list `resource_monitor.py`, and
  `.gitattributes` / LICENSE should appear once added.
- **Duplicate sub-title** at `README.md:5` and `README.md:29`.
- **Screenshots are about 6.6 MB of PNG.** Optional: convert them to compressed PNG or WebP for a faster
  README.

### L-13 · Test gaps
The suite is solid (35 tests, including mocked-Gemini cases). Tests to add along with the fixes above:
forged cookie with the default key (H-1), empty admin password (M-2), schema rejecting bad plans (M-3),
demo revision respecting experience and age (M-4), duplicate versions (M-7), and an HTML 422 page (L-6).

---

## Things that are fine (checked, no action)
- `.env`, `fitbuddy.db*`, `venv/` and `CLAUDE.md` are git-ignored and were never committed.
- Jinja autoescape is on, and user input is escaped (there's a test for it). The confirm dialog on the admin
  page reads the name from `data-name`, so it can't run injected script.
- AI failures never save error text. Plan v1 is saved only after both generations succeed.
- Gemini calls run in the threadpool (plain `def` routes), so they don't block the event loop.
- `reports/` logs contain only localhost traffic and model endpoint URLs, with no keys or personal data
  beyond test names.
- README links: all 8 phase-folder links and all 8 screenshot images resolve. `02_home_filled.png` is
  committed but not shown in the README, so either add it to the gallery or drop it.
- Phase PDFs agree with each other and the code on test count (35), model IDs, routes and the new
  load-test and resource numbers.

---

## Summary

The app is in good shape. The tests pass (35/35), a fresh clone installs and runs with zero config, no
secrets were ever committed, and the phase documents agree with the code.
**Four items should be fixed before submission:**
1. **H-1:** the default `SECRET_KEY` makes the admin login bypassable. Generate a random key when it's unset.
2. **H-2:** the README still shows the old load-test numbers (1,433 / 357 ms instead of 1,457 / 77 ms).
3. **H-3:** the README phase table leaves out "FitBuddy Project Documentation".
4. **H-4:** there's no demo video link, though the Executable Files PDF promises one.

Of the medium items, the most valuable before submission are **M-3** (enforce the 7-day and rest-day
rules in the schema) and **M-4** (demo revisions ignore beginner and teen rules). Both are visible in a
live demo. The low items are polish: docstrings, a LICENSE, renaming the file with a trailing space, and a
pointer from the Phase 5 folder to the code. The `.gitattributes` fix in this commit should make GitHub
show the repo as about **74 % Python, 15 % HTML, 11 % CSS**.
