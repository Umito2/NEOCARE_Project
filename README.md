# NEOCARE — local AI and demo deployment

## PythonAnywhere deployment without local AI

See [PYTHONANYWHERE_DEPLOY.md](PYTHONANYWHERE_DEPLOY.md) for the free-host deployment setup. The clean ZIP excludes local AI, credentials, and laptop data. The standard WSGI host runs FastAPI through a small adapter, with persistent private storage and rule-based recommendations. The provider's Force HTTPS setting redirects insecure requests before they reach the application.

## Railway deployment without local AI

See [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md) for the cloud package and required settings. The Docker image includes only application code, runtime dependencies, and report fonts. It excludes Ollama, downloaded models, local databases, backups, and credential files. Set `NEOCARE_RECOMMENDATION_MODE=rules` to generate reports directly from the existing rules without attempting any AI connection; the local launcher continues to use Ollama by default.

The cloud launcher requires explicit clinic and device credentials, a Firebase credential supplied through the hosting service's secret variables, and persistent database storage. A fresh cloud database does not include existing laptop accounts or histories. A free provider address does not require buying a domain. Railway's Free plan has limited monthly usage credits, so verify the workspace plan before deploying; do not upgrade or enable paid usage for a zero-cost deployment. See [Railway pricing](https://railway.com/pricing).

NEOCARE is a FastAPI/Python web application, not a static Google Sites page. It serves `index.html`, uses Firebase Realtime Database, stores parent accounts, sessions, alerts, and settings in SQLite, and generates PDF reports.

AI recommendations run through Ollama on the same computer as the app, using `qwen3.5:4b` by default. This setup needs no AI API key and has no per-request AI service charge. The model download needs an internet connection; generation uses your computer's CPU/GPU and memory. Firebase data storage still uses the cloud, so the complete application is not offline.

## Security before publishing

- The service-account key previously present in the local project must be treated as exposed. Revoke it in Google Cloud IAM and create a replacement before deploying.
- Never add the old or replacement service-account JSON, `.env`, `.openai_api_key`, or SQLite database to GitHub or a deployment archive.
- `.gitignore` excludes service-account files, `.env` files, SQLite databases, and Python cache files. Verify your repository and archive before uploading.
- Do not use real patient information with this free demonstration. Generated output is not medical advice or a diagnosis.

## Deploy a demo on Render

1. Keep the original local project and its SQLite database private. Create a separate deployment copy that does not contain `serviceAccountKey.json`, `.env`, or any `*.sqlite3` file.
2. Create a **private** GitHub repository and upload the application source, `requirements.txt`, `render.yaml`, `.gitignore`, and this README.
3. In Render, choose **New + → Blueprint** and connect the private repository. Render reads `render.yaml` to create the free web service.
4. In the service's **Environment → Secret Files**, add a file named `serviceAccountKey.json` containing the replacement Firebase service-account JSON. The Blueprint configures `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/serviceAccountKey.json`.
5. Set the Blueprint's `DOCTOR_USERNAME` and `DOCTOR_PASSWORD` prompts to strong, unique values. Render generates `ESP32_API_KEY`; configure the ESP32 with that same value.
6. The supplied Blueprint uses rule-based recommendations when Ollama is unavailable. A Render service cannot reach Ollama on your PC through `127.0.0.1`; that address always refers to the machine running the app. The Blueprint does not install an AI model or Ollama. Run the application locally for the included local AI setup.
7. Deploy, then open the Render URL and confirm `/health` returns `{"status":"ok"}`. Free services can sleep after inactivity and need time to wake up.

The Firebase Realtime Database URL is configured through `FIREBASE_DATABASE_URL` and can be changed in the Render environment if your deployment uses another database.

### Optional parent email delivery

SMTP delivery is optional and requires a clinic-controlled sender mailbox. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USERNAME`, and `SMTP_PASSWORD` as server environment variables/secrets. On Render Free, outbound SMTP ports commonly used for email (25, 465, and 587) are blocked, so email alerts may not work there. A clinic can still store report PDFs in Recent Parent Alerts.

## Free-tier limitations and privacy

Use Render Free only for a demonstration with invented/test data. The local SQLite database is configured at `/tmp/neocare_auth.sqlite3`; Render Free storage is ephemeral, so accounts, sessions, alert history, and settings can be lost when the service sleeps, restarts, or redeploys. Render's free Postgres is also temporary and expires after 30 days.

For persistent use, migrate SQLite to an appropriately managed persistent database and complete a professional clinical, security, and privacy review first. Do not rely on a free demonstration host for urgent alerts or clinical decisions.

This application processes pediatric health measurements. Do not use it with real patients or for emergency monitoring without qualified clinical, security, and privacy review.

## Local run

When `DOCTOR_USERNAME` and `DOCTOR_PASSWORD` are unset, doctor login defaults to username `NEOCARE` and password `123456789`. Environment variables override these defaults. Set unique credentials before exposing the application publicly or using patient data.

1. Install Python 3.10 or later.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Keep the Firebase service-account JSON outside version control and configure the local environment:

   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\secure\path\serviceAccountKey.json'
   $env:FIREBASE_DATABASE_URL = 'https://neocare-system-default-rtdb.firebaseio.com/'
   $env:ESP32_API_KEY = 'use-a-long-random-secret'
   $env:DOCTOR_USERNAME = 'choose-a-clinic-username'
   $env:DOCTOR_PASSWORD = 'choose-a-strong-unique-password'
   ```

4. Set up the local AI runtime and model once, from this project folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup-local-ai.ps1
   ```

   The script downloads the Ollama runtime and the model into `.local-ai`, which is excluded from Git. No administrator access or AI API key is needed. Allow the initial model download to finish.

5. Start Ollama and NEOCARE:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start-neocare.ps1
   ```

   Keep this terminal open while using the app. The launcher starts Ollama in the background and runs the web server in the foreground. If needed, select your Python installation with `-PythonPath 'C:\path\to\python.exe'`.

   To keep NEOCARE running after closing the terminal, use `powershell -ExecutionPolicy Bypass -File .\start-neocare.ps1 -Background`. This verifies the server is listening before returning and saves logs in `.local-ai/logs`. Run the command again after restarting Windows.

6. Open `http://127.0.0.1:8000/` and generate a report. The page shows **Local AI recommendations (Ollama)** when model generation succeeds. Requests allow up to two minutes for the model. The first-ever GPU initialization can exceed this limit; the report then uses rules, and you can retry after initialization finishes. If the local service or model is unavailable, the report clearly identifies rule-based recommendations and explains the fallback.

Reports classified as **Critical** skip model generation and show immediate rule-based safety guidance. They do not wait for Ollama. Risk assessment and safety guidance always come from the existing rules; the local model only rephrases the supplied noncritical recommendation checklist.

### Local AI settings

The defaults are:

```powershell
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
$env:OLLAMA_MODEL = 'qwen3.5:4b'
```

The launcher disables Ollama cloud features with `OLLAMA_NO_CLOUD=1`. De-identified readings are sent to the local Ollama service for generation; names and contact details are not needed by the model. The app no longer reads an OpenAI API key. An existing `.openai_api_key` file is not used and should remain private.

If you already manage Ollama separately, start its local service, download the configured model with `ollama pull qwen3.5:4b`, and run `python -m uvicorn api:app --reload --port 8000`. Only the AI generation runs locally: Firebase, optional email delivery, and any remote hosting keep their existing network requirements.

The SQLite database is created on startup. If Firebase credentials or required server settings are not configured, the related functions will report configuration errors.

## Interface

The interface uses a responsive teal-and-ivory design across sign-in, registration, parent and clinic dashboards, profiles, readings, alerts, settings, and reports. Dashboard navigation moves to the selected section; on phones it becomes a horizontal navigation bar. Summary cards reflect the children and readings returned by the server.

Use the moon/sun button beside the language switch to change between light and dark mode. The initial theme follows the device's color preference; an explicit choice is saved in this browser and shared with other open NEOCARE tabs. Theme controls and labels work in English and Arabic. Printed reports use a light background in either mode.

Subtle entrance, loading, and reading-change animations respect the device's reduced-motion preference. Keyboard users can use skip links and visible focus indicators. Password visibility resets after sign-in and sign-out. The English/العربية switch translates the interface and changes its reading direction; patient names, clinician notes, and other entered text remain unchanged.

## Readings, history, and assessment

The monitoring section provides a 24-hour or seven-day history chart, a measurement selector, and an accessible readings table. History starts with readings received after this update; previously overwritten Firebase readings cannot be reconstructed. Each incoming reading is kept in the local SQLite history while Firebase continues to hold the latest reading. When a requested window contains more than 1,000 readings, the API returns actual sampled measurements across that window, preserving extrema within buckets, and marks the result as sampled. Missing measurements are not estimated.

The dashboard, report, and alert pipeline share `assessment.py`. The existing numerical defaults and activity adjustments are retained; configured clinic thresholds take precedence. Respiratory-rate and active heart-rate comparisons now use the previously defined limits. Descriptions identify measurements crossing thresholds without inferring a diagnosis.

Freshness is checked on the server and shown in the interface. The default maximum age is 300 seconds, configurable with `NEOCARE_READING_MAX_AGE_SECONDS`; this is an operational freshness setting, not a clinical threshold. Missing, invalid, or stale timestamps cannot produce a current Normal assessment or a newly generated recommendation report. Ingestion timestamps indicate server receipt time, not an independent device heartbeat or proof of current hardware connectivity. Reports preserve the reading timestamp.

Arabic PDF names and mixed Arabic/English text use the bundled [Amiri font](https://github.com/google/fonts/tree/main/ofl/amiri), distributed under the license in `assets/fonts/OFL.txt`. `uharfbuzz` provides the [text shaping required by fpdf2](https://py-pdf.github.io/fpdf2/TextShaping.html). Long names wrap within the page margins. Reinstall `requirements.txt` when updating an older environment.

## Clinic alert history

In the clinic dashboard, each entry under **Recent parent alerts** has a **Delete alert** button. Confirming deletes that alert and its saved PDF from both the clinic and parent histories. Parents cannot delete alerts. Previously delivered emails remain in the recipient's mailbox.

Clinicians can mark alerts **New**, **Acknowledged**, or **Resolved** and add notes. Status is visible to the linked parent; clinician notes are restricted to clinic accounts. Deleting an alert also removes its notes and queued delivery. Acknowledging or resolving an alert records a workflow decision and does not change the sensor assessment.

Notification requests are stored in a durable outbox before delivery. Failed sends retry with bounded backoff, up to eight attempts; when SMTP is configured, a background worker also checks the queue every minute. Missing SMTP configuration does not consume delivery attempts. An SMTP acknowledgment does not prove a recipient read the message, and an interrupted connection can make external email delivery uncertain. SMTP sender settings are still required; this update does not configure a mailbox.

## Individual clinician accounts and audit history

Open **Clinic settings**, then the clinician-management section, to create individual doctor accounts and view account/audit information. New clinician passwords require 12–128 characters and are stored using salted password hashes. All clinician accounts currently have the same clinic permissions; parents cannot manage clinicians, thresholds, notes, or audit history.

The existing configured/default clinic login remains available for compatibility. A named account with the same username takes precedence. Set unique server credentials before public deployment; blanking the shared `DOCTOR_USERNAME` or `DOCTOR_PASSWORD` disables that fallback once individual access is established. Never share individual passwords.

Audit entries record actor identity, action, target, and time for clinician login, account creation, threshold changes, alert workflow changes, and deletion. They omit passwords, note content, and measurement payloads. The local audit store is an operational history, not a tamper-proof external ledger.

## Backup and recovery

`backup_neocare.py` backs up **both** the SQLite database (accounts, sessions, settings, history, alerts, notes, and audit entries) and Firebase's `neocare_system` subtree. Backups stay in the ignored `.backups` directory; they contain private data and should be protected like the original database. No service-account key is included. Database schema upgrades also preserve a verified SQLite snapshot before migration.

```powershell
python backup_neocare.py create
python backup_neocare.py verify .backups\BACKUP_FOLDER
```

Creation uses SQLite's backup API, SHA-256 file checksums, and database integrity checks. Firebase and SQLite are independent snapshots: pause application writes before creating a coordinated recovery point. These are local backups; retain a protected copy on separate storage for protection against loss of this computer. Backups are created on demand, not on a daily schedule.

To restore, stop the application and device submissions, verify the intended backup and Firebase database, then explicitly run:

```powershell
python backup_neocare.py restore .backups\BACKUP_FOLDER --confirm-restore --maintenance-confirmed
```

Restore replaces both application stores. It first makes a complete safety backup, verifies restored data, and attempts rollback if recovery fails. Successful restore clears saved login sessions so previously revoked sessions cannot become usable again. The command refuses a snapshot from a different configured Firebase URL. Restart NEOCARE afterward and sign in again. Do not run restore against a live system or an untrusted backup.

## Automated checks

Install `requirements-dev.txt` to include PDF rendering/extraction checks. Run `python run_tests.py` for offline Python tests and `node --test --test-timeout=60000 tests/frontend/*.test.mjs` for browser checks using installed Chrome. Tests use synthetic accounts/readings and mocked Firebase, SMTP, and AI. See `TEST_REPORT.md` for the latest verified results and remaining operational limits.
