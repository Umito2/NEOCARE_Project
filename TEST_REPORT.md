# NEOCARE test report

## Dark mode — 28 October 2026

**All 102 browser checks passed:** the existing 84 interface/workflow regressions and 18 theme checks. Dark mode covers sign-in, profiles, dashboards, controls, alerts, status badges, history, and reports. The theme is selected before body rendering, follows the device preference until explicitly changed, and remembers a saved light/dark choice. The switch supports keyboard interaction and translated English/Arabic action labels. Blocked browser storage falls back gracefully.

Checks cover system preference changes, saved choices on a fresh page, sign-in/sign-out persistence, Arabic labels, visible keyboard focus, 320/390 px mobile layouts, and light print styles without changing the saved theme. Twenty synthetic English/Arabic desktop/mobile screenshots completed without page errors or horizontal page overflow. The dark sign-in, clinic dashboard, Arabic phone dashboard, and light print report were visually reviewed. The live local page and translation asset serve the new switch and styles.

Evidence: `test-results/frontend/theme-results.tap`, `test-results/frontend/all-theme-results.tap`, and `test-results/frontend/screenshots/theme-manifest.json`. Python/backend source was unchanged for this update; the previous 183 passing Python checks were not rerun.

## Monitoring and clinic workflow update — 27 October 2026

**267 automated tests passed, with no failures or skips:** 183 Python checks and 84 real headless Chrome checks. All nine previously outstanding Python failures are resolved. The earlier sections below describe historical results; this section supersedes their remaining-failure lists.

| Current suite | Tests | Passed | Failed / errored |
| --- | ---: | ---: | ---: |
| Offline Python API, storage, assessment, local AI, backup/recovery, and PDF checks | 183 | 183 | 0 |
| Real Chrome interface/workflow checks | 84 | 84 | 0 |
| Total | 267 | 267 | 0 |

The corrected regressions cover new-profile alert creation, failed-email retry, dashboard/report threshold consistency, stale-reading classification, Unicode login rejection, respiratory-rate and active heart-rate evaluation, Arabic PDF names, and long PDF names. Dashboards, alerts, and reports now use a shared evaluator. Existing numerical defaults and activity adjustments were retained; this is not clinical validation of those limits.

New tests cover persisted 24-hour/seven-day history, ownership and deleted-ID isolation, bounded sampling that preserves extrema, named clinician passwords and permissions, private clinician notes, alert status/audit records, concurrent episode deduplication, one-message-at-a-time outbox leases, retry backoff, and missing SMTP without exhausted delivery attempts. SQLite migration tests preserve existing records and verify pre-migration snapshots. Backup tests cover both SQLite and Firebase snapshots, checksums, integrity, empty subtrees, guarded restore, rollback, database URL mismatch, and invalidation of restored sessions.

Browser checks include new history/error/late-response behavior, missing-value plots, server freshness status, clinician-only controls, draft preservation during refresh, Arabic/English switching and RTL, unchanged entered names, mobile overflow, and clearing all previous-session patient/clinic content when the next account fails to load. Existing report-identity, alert-deletion, authentication, keyboard, reduced-motion, and print regressions continue to pass.

PDF checks render and extract real generated PDFs with synthetic Arabic and mixed-script names. Bundled Amiri fonts and HarfBuzz preserve Arabic glyphs; long names remain inside page margins. The conflicting legacy `fpdf` package was removed while retaining tested `fpdf2` 2.8.9; `pip check` passes.

Live update verification: a complete local SQLite/Firebase backup was created and verified before migration. The recorded NEOCARE process was restarted, the database upgraded from schema 0 to 2, and existing parent, alert, setting, and alert-state record counts were preserved. SQLite integrity and foreign-key checks passed. The home page, health route, and fixed translation asset return HTTP 200; the private backup path returns HTTP 404. No real alert email, patient test reading, or restore was performed.

Artifacts: `test-results/features-python-final.log`, `test-results/python-results.json`, `test-results/frontend/all-features-results.tap`, `test-results/live-upgrade-check.json`, and `test-results/arabic-report.pdf`/`.png`. All automated business-data tests use invented records with Firebase, AI, and SMTP mocked; the live backup only reads existing Firebase data.

Operational limits: history starts with new ingested readings; earlier overwritten readings cannot be recovered. SMTP configuration is still needed for email, and uncertain SMTP delivery cannot guarantee exactly once. Large history windows show a marked subset of actual samples, not an exhaustive event timeline. Pause application writes for a coordinated SQLite/Firebase recovery point; local backup creation is on demand. Real hardware accuracy, clinical suitability, public deployment, and real email delivery have not been validated. Qualified clinical review is still required before patient use.

## Interface redesign — 27 October 2026

**All 71 browser tests passed** after the interface redesign: 42 existing workflow regressions and 29 responsive, accessibility, password-state, refresh, and print checks. The tests ran in real isolated Chrome with synthetic profiles and intercepted API responses; they did not change patient records or send email.

Coverage includes parent and clinic sign-in, registration, profile editing, alert deletion, report identity and download actions, local-AI display, keyboard navigation and focus, reduced-motion behavior, password cleanup after authentication, and table scroll preservation during polling. Desktop (1440 px), phone (390 px), and narrow phone (320 px) layouts passed overflow checks. Eighteen desktop/mobile screenshots cover sign-in, signup, both dashboards, monitoring, alerts, settings, reports, and print styles; captures reported no uncaught browser errors. The local server returned HTTP 200 and served the redesigned page.

The four previously failing browser cases now pass: parent editing opens the form, manual refresh errors are visible, overview status refreshes during polling, and old readings receive a visible recency notice. That notice is a presentation change; backend freshness classification and report risk rules are unchanged.

| Latest available results | Tests | Passed | Failed / errored |
| --- | ---: | ---: | ---: |
| Browser suites, rerun for this update | 71 | 71 | 0 |
| Python, previous local-AI run; not rerun for this UI-only update | 124 | 115 | 9 |

Artifacts: `test-results/frontend/redesign-regression.tap`, `test-results/frontend/redesign-final.tap`, and `test-results/frontend/screenshots/manifest.json`. The nine previously documented Python failures remain outside this interface update.

## Local AI update — 27 October 2026

The application now uses local Ollama instead of OpenAI. At the time of this update, automated results were **166 tests, 153 passed, 13 existing failures/errors**. The interface update above supersedes these browser results. All 38 focused backend/PDF checks and all 11 new local-AI/report-identity browser cases passed. These checks verify software behavior, not clinical accuracy.

| Current suite | Tests | Passed | Failed / errored |
| --- | ---: | ---: | ---: |
| Python | 124 | 115 | 9 |
| Real headless Chrome | 42 | 38 | 4 |

The local adapter checks loopback configuration, disabled proxy/redirect use, downloaded model metadata before sending measurements, strict response structure, failure fallback, and omission of names/contact details. Reports marked Critical by the report evaluator return deterministic guidance without waiting for a model. Report requests and PDF/send actions now remain tied to the selected child and login session; stale completions are discarded. Common model-generated Unicode punctuation can be exported to PDF.

Remaining Python failures cover the existing new-child alert crash, failed-email retry, dashboard/report threshold mismatch, stale reading classification, non-ASCII doctor-login handling, ignored respiratory/activity limits, Arabic PDF names, and overflowing long PDF names. Remaining browser failures cover parent profile editing, stale-reading labels, clinic overview polling, and manual profile-refresh error visibility. In particular, clinic-configured Critical status can still differ from the report evaluator; this update does not resolve that clinical rules mismatch.

Artifacts: `test-results/python-results.json`, `test-results/ollama-python-output.log`, and `test-results/frontend/local-ai-all.tap`. PowerShell scripts parse successfully; `pip check` passed. Live checks confirmed app health HTTP 200, Ollama 0.40.11, and HTTP 404 for private local AI/key paths.

Live local generation also passed with invented readings and mocked Firebase access: a normal report after unloading/reloading the model took 7.71 seconds, a subsequent warning report took 1.58 seconds, and a Critical report bypassed AI in 0.01 seconds. All three generated valid PDFs. The model occupied about 2.92 GiB on the GPU. Results and PDFs are in `test-results/local-ai-smoke.json` and `test-results/local-ai-*.pdf`. The first-ever GPU initialization exceeded the 120-second request timeout and correctly fell back to rules; retrying after initialization and a separate fresh-load check succeeded. Both large model blobs passed SHA-256 verification. These are software/integration checks, not clinical validation.

## Original baseline

Baseline date: 27 October 2026. Application source was not changed during that initial test-only pass. The following results describe that historical state; the update above supersedes its totals and resolved defects.

## Result and scope

The completed suites ran **113 tests: 95 passed and 18 failed**, comprising 16 failed assertions and 2 PDF-generation errors. No tests were skipped, cancelled, or marked as expected failures. Multiple failing tests cover different manifestations of the same defect; 18 failures does not mean 18 distinct bugs.

| Area | Tests | Passed | Failed / errored |
| --- | ---: | ---: | ---: |
| HTTP API, authentication, permissions, profiles, readings, alerts, reports | 36 | 31 | 5 |
| SQLite accounts, password hashing, sessions, settings, alerts, migrations | 17 | 17 | 0 |
| Firebase configuration and SMTP transport adapters | 12 | 12 | 0 |
| Assessment rules, PDF output, mocked AI response handling | 25 | 20 | 5 |
| Python total | 90 | 80 | 10 |
| Real headless Chrome dashboard scenarios | 23 | 15 | 8 |
| Combined total | 113 | 95 | 18 |

The API tests execute the real FastAPI handlers and startup lifespan with a temporary SQLite database. Firebase is replaced by a small in-memory reference implementation. AI responses and SMTP connections are mocked; the actual adapter logic is exercised. External connections are blocked. Only the loopback connections needed by Windows asyncio are permitted in the API test fixture.

The tests use invented accounts, children, and readings. They neither initialize the real Firebase connection nor read the service-account key or existing patient database. The temporary databases are removed after each test. Existing application modules and index.html were left unchanged.

The browser suite loads the original `index.html` in real headless Chrome and intercepts API calls with synthetic responses. It verifies rendering, visibility, events, and outgoing request identity; it is not a browser-to-live-backend integration test. Timer callbacks are invoked deterministically. Page HTTP/HTTPS/WebSocket traffic is blocked, and a separate temporary browser profile is used and removed. No user's browser profile is opened.

## Reproduced Python failures

These are observable software defects or missing behavior, not an assessment of clinical accuracy. Numeric values below exercise existing code and configured thresholds; they are not proposed medical limits.

| Priority | Reproduction and observed result | Relevant code | Regression test |
| --- | --- | --- | --- |
| High | Register a parent normally, configure thresholds, submit SpO2 90. The reading is written, but the endpoint returns HTTP 500 before storing the alert. The alert formatter reads `profile['child_id']`, which the normal signup profile does not contain. | `api.py:407`, `api.py:451`, `api.py:913` | `test_new_child_threshold_crossing_stores_alert_without_crashing` |
| High | Submit SpO2 94 and configure the clinic minimum as 95. Dashboard status is Critical while the report says Normal. Reports use a different evaluator and ignore saved clinic settings. | `api.py:199`, `api.py:650` | `test_report_and_dashboard_use_same_clinic_thresholds` |
| High | Simulate a failed alert email, then submit another reading at the same severity. The mail adapter is called only once; the failure is treated as an already-notified episode. A legacy-shaped profile with `child_id` isolates this defect from the separate signup-profile crash. | `api.py:914`, `api.py:929` | `test_failed_alert_delivery_is_retried_on_next_reading` |
| High | Change a normal reading's timestamp to 2000-01-01. Its dashboard status remains Normal, with no freshness classification. | `api.py:190` | `test_stale_reading_is_not_presented_as_current_normal` |
| High | Call the rule analyzer for age 4, otherwise baseline readings, respiratory rate 100. It returns Normal even though it calculates a respiratory limit of 26. | `main.py:71`, `main.py:125` | `test_respiratory_rate_over_defined_limit_is_not_normal` |
| High | Call the analyzer for age 4, activity Active, heart rate 240. It returns Normal despite computing an adjusted limit of 140. The heart-rate branch runs only for Resting/Sleeping. | `main.py:74`, `main.py:109` | `test_active_heart_rate_over_adjusted_limit_is_not_normal` |
| Medium | Generate a PDF with an Arabic child name accepted by the profile schema. FPDF raises `FPDFUnicodeEncodingException`. | `main.py:195`, `main.py:199` | `test_arabic_child_name_accepted_by_api_can_be_exported` |
| Medium | Generate a PDF with otherwise valid AI suggestions containing a curly apostrophe/em dash. FPDF raises `FPDFUnicodeEncodingException`. | `main.py:250` | `test_ai_recommendations_with_unicode_punctuation_can_be_exported` |
| Medium | Export a name of 80 `W` characters, accepted by the API. Measured patient-header text exceeds the available page width. | `main.py:199` | `test_maximum_accepted_child_name_stays_inside_page` |
| Medium | Submit non-ASCII doctor login credentials with ASCII configured credentials. The API returns HTTP 500 instead of rejecting the credentials; `hmac.compare_digest` cannot compare non-ASCII strings. | `api.py:503` | `test_unicode_wrong_doctor_credentials_do_not_crash` |

## Reproduced browser failures

Real browser: **Chrome 155.0.8059.86**, driven through Chrome DevTools by **Node 24.22.1** without downloaded browser-test packages. The final run took approximately 8 seconds.

| Priority | Reproduction and observed result | Relevant code | Browser test |
| --- | --- | --- | --- |
| High | Generate a report as parent A, sign out, and sign in with another parent whose fixture list contains a different child. The old report remains visible in the new dashboard. This is retained page content, separate from the backend ownership checks that passed. | `index.html:826`, `index.html:905`, `index.html:1025` | `a report from the previous account is not exposed after the next login` |
| High | Generate a report for child A, then select child B. Child A's report remains visible under child B's sensor readings. | `index.html:684` | `changing child clears a previously generated report` |
| High | With that old report still visible, click Send PDF to parent. The request targets child B instead of displayed child A. | `index.html:712` | `send report remains bound to the report shown after child selection changes` |
| High | Change the clinic overview fixture's status from Normal to Critical and trigger the regular refresh callback. Selected sensor values refresh, but the overview status stays Normal. | `index.html:479`, `index.html:1085` | `periodic refresh updates clinic overview risk statuses` |
| High | Supply a reading timestamp from 2000. The UI prints the timestamp but provides no stale/offline warning. | `index.html:618` | `old readings are explicitly identified as stale or offline` |
| Medium | Click Edit in the parent dashboard. Form values are populated but the form remains hidden. Clinic editing passes. | `index.html:547`, `index.html:921` | `parent Edit exposes the populated form` |
| Medium | Simulate a failed report request in the parent dashboard. The error is placed in the hidden profile form, so no visible error appears. | `index.html:803` | `report generation failures appear in visible page content` |
| Medium | Simulate a failed manual profile refresh. Its error is also placed in the hidden form. | `index.html:679` | `manual profile refresh failures appear in visible page content` |

The 15 passing browser scenarios cover sign-in/out visibility, role switching, both login flows, visible login errors, signup, adding a child, clinic editing and saving, missing/incomplete readings, visible sensor errors, report rendering, and refresh of the selected child's values. No uncaught page errors were observed in the completed scenarios.

Raw results: `test-results/frontend/browser-results.tap`.

## What passed

- Signup, email normalization, login/logout, secure/HttpOnly cookie attributes, wrong-password rejection, session expiry, and duplicate-email rollback.
- Parent isolation for child lists, readings, reports, profile updates, alerts, and stored PDFs; clinic-only deletion, report sharing, and threshold changes.
- Child creation/update, blank-name rejection, invalid child IDs, and the existing 99-ID capacity response.
- Device-key checks, invalid reading rejection, missing sensor fields, waiting states, valid reading storage/retrieval, and threshold ordering validation.
- Alert deduplication and recovery when a complete legacy-shaped profile and successful mail adapter are supplied.
- Report fallback when AI is unavailable, retained safety text, ASCII PDF exports, saved PDF access, and preservation of report PDFs after simulated email failure.
- Password salts/hashes, hashed session tokens, session cleanup, SQL parameter binding, database rollback, alert/PDF ownership, settings persistence, repeat initialization, and legacy-table migration.
- Credential-file resolution using temporary dummy files; mocked Firebase initialization; missing SMTP settings, STARTTLS/SSL adapter calls, and transport errors.
- AI response validation, malformed/empty/error responses, payload-field checks, report notices, and PDF pagination.

## Environment checks

- Tested interpreter: Python **3.14.5**, at `C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe`.
- The default Windows `python` / `py` aliases did not execute in this session; the installed interpreter above worked.
- `pip check` passed. The three application Python modules compiled on the installed interpreter.
- AST syntax checks targeting Python 3.10 through 3.14 passed. These are best-effort parser checks, not execution on those separate runtimes.
- `render.yaml` parsed successfully. Hosting and deployment were not exercised.
- Render specifies Python 3.13.4, which differs from the tested interpreter. `requirements.txt` has no pinned versions, so a fresh deployment may resolve different dependencies.
- Both legacy `fpdf` **1.7.2** and `fpdf2` **2.8.9** are installed and share the `fpdf` namespace. Importing the PDF library warns about this conflict even though `pip check` passes. Package installation was not changed.
- Chrome's GPU process crashed with access-denied errors inside the restricted execution environment. The prepared tests subsequently completed with execution approval outside that restriction. The failed startup attempts are infrastructure failures and are excluded from the 113-test result above.
- Package details and check evidence: `test-results/environment-checks.json`.

## Running the Python suite

From the project directory, on the machine used for this test:

```powershell
& 'C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe' .\run_tests.py
```

With a working Python installation containing the project dependencies and `httpx`:

```text
python run_tests.py
```

The suite uses the standard-library `unittest` runner, without pytest. The test helpers use `TestCase.enterContext`, so running this suite requires Python 3.11 or later even though the application's documented minimum is 3.10. The tested runtime was 3.14.5.

The command exits nonzero while the reported defects remain. Full Python test identities and tracebacks are saved in `test-results/python-results.json`. The captured session output is in `test-results/python-output.log`. Test artifacts are ignored by Git.

## Running the browser suite

Use Node 24 or later and an installed Chrome/Edge browser:

```powershell
node --test --test-timeout=60000 .\tests\frontend\frontend.test.mjs
```

The harness searches the standard Windows Chrome/Edge install locations. For another location, set `NEOCARE_TEST_BROWSER` to the browser executable. Chrome must be able to start its renderer/GPU processes in the execution environment. The test runner returns a nonzero exit code while the browser regressions remain.

To save TAP output directly:

```powershell
node --test --test-timeout=60000 --test-reporter=tap --test-reporter-destination=.\test-results\frontend\browser-results.tap .\tests\frontend\frontend.test.mjs
```

## Recommended repair order

1. Clear patient/report data at account changes and bind every report action to the displayed child and reading.
2. Repair automatic alert creation, failed-delivery retry handling, and dashboard/report rule consistency.
3. Add stale-reading handling and refresh the clinic overview correctly.
4. Resolve unused assessment limits with the responsible clinician, then add agreed regression expectations.
5. Support Unicode/wrapping in PDFs and repair parent editing and visible errors.

The failing tests deliberately remain visible so repairs can be checked against the reproduced problems. No product repairs were included in this testing task.

## Coverage limits

This is a broad local software test pass, not a claim that every possible behavior has been tested. It does not validate:

- ESP32 firmware, physical sensors, calibration, accuracy, device pairing, or intermittent hardware connectivity.
- Real Firebase credentials, permissions/security rules, network behavior, concurrency, or cloud persistence.
- Live AI service compatibility or medical quality of generated recommendations.
- Actual SMTP delivery, retries against a real mail service, or email receipt.
- Render deployment, restart recovery, backups, load/capacity, or a full penetration/security assessment.
- Clinical thresholds, clinical effectiveness, clinical safety, or authorization for real patient deployment.

The in-memory Firebase substitute does not reproduce all Firebase SDK behavior. A controlled staging environment and hardware tests remain necessary after the software defects are fixed.
