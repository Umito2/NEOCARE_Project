# NEOCARE on Railway, without local AI

The Docker deployment runs the existing FastAPI interface, assessment rules,
Firebase connection, PDF reports and SQLite workflows. It does not install or
upload Ollama, model weights, `.local-ai`, local accounts, patient records,
backups, `.env` or service-account files. The cloud entry point forces
`NEOCARE_RECOMMENDATION_MODE=rules`.

## Cost and address

Railway supplies an HTTPS `*.up.railway.app` address, so a purchased domain is
unnecessary. Its Free plan currently includes $1 of monthly usage credit after
the initial trial, not unlimited free compute. Persistent storage and an awake
service consume resources; continuously submitting device readings can keep the
service awake. Verify that the intended workspace is on Free and that no paid
upgrade or chargeable plan is selected before deploying. Do not rely on a paid
plan's spending limit to guarantee a $0 bill.

Sources: [Railway pricing](https://railway.com/pricing),
[Free trial and retention](https://docs.railway.com/pricing/free-trial),
[Serverless sleep](https://docs.railway.com/deployments/serverless).

## Required Railway configuration

1. Create/select the intended NEOCARE service and use this `Dockerfile`.
2. Attach a persistent Railway volume at `/data`. The launcher refuses to use
   an ordinary ephemeral directory for the SQLite database.
3. Add these variables using Railway's secret/environment settings. Never put
   their actual values in a source repository or deployment archive.

| Variable | Value or purpose |
| --- | --- |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Complete JSON for a fresh private Firebase service account. The launcher creates a temporary private file for the Firebase SDK. |
| `FIREBASE_DATABASE_URL` | The intended HTTPS Firebase Realtime Database URL. |
| `DOCTOR_USERNAME` | Explicit clinic username, 3–80 characters. |
| `DOCTOR_PASSWORD` | Unique clinic password, 12–128 characters. The local legacy default is refused. |
| `ESP32_API_KEY` | Random device secret of at least 24 characters; use the same value on the authorized sending device. |
| `NEOCARE_AUTH_DB` | `/data/neocare_auth.sqlite3` (also set by the image). |
| `PORT` | Railway's assigned port, or `8000` when explicitly configuring the service/domain port. |

Use a replacement Firebase credential if the previous project key was exposed,
as already documented in `README.md`. The key is a runtime secret and is never
part of the Docker build context. The private temporary credential file lasts
only for the web process lifetime and is removed on an ordinary shutdown.

No SMTP settings are required to open the website or save report PDFs. Railway
blocks outbound SMTP on Free, Trial and Hobby plans. Consequently, setting
`SMTP_HOST` and related variables cannot enable the existing SMTP sender on
those plans. Leave them unset for this deployment: alerts and shared PDFs can
still be saved and viewed in the authorized portals.

Email delivery on these plans needs a transactional email provider's HTTPS API
and an application adapter; that adapter is not included in the current project.
Do not upgrade the Railway plan or add another paid service to enable email as
part of this free deployment. Background retry work also cannot run while a
sleeping service is suspended. See
[Railway's email-delivery policy](https://docs.railway.com/networking/outbound-networking#email-delivery).

## Deployment settings

- Start command: the image's `python cloud_start.py` command.
- Health path: `/health` (process availability only).
- Replicas/workers: one, attached to the persistent volume.
- Generate a Railway service domain with the correct target port and use HTTPS.
- Optional sleep reduces idle compute usage; test wake-up behavior and understand
  that incoming device traffic can prevent sleep.

The launcher trusts forwarded headers because this package is intended to sit
behind Railway's HTTPS proxy. Do not expose the container's port directly to
the public internet outside that deployment arrangement. After deployment,
verify the HTTPS response, login, `Secure` session-cookie attribute, authorized
Firebase access, report generation, and persistence across a controlled restart.

Both `.railwayignore` and `.dockerignore` are strict allowlists. For a local
CLI upload, inspect the archive's file list before sending it. The Dockerfile
copies only the required runtime files and bundled PDF fonts.

## Data starts separately from the laptop

The first cloud SQLite database is new. Local parent accounts, sessions,
clinician accounts, alert PDFs, notes and reading history are not automatically
transferred. If the cloud is pointed at the existing Firebase database, existing
Firebase profiles may still refer to parent IDs whose accounts exist only on
the laptop. Do not assume creating a new parent account reconnects those records.
Any migration of existing private data requires a deliberate, coordinated
backup/transfer plan; never put the SQLite database into the Docker image.

Free/trial quotas and retention rules can suspend services or affect stored
data. Keep protected backups outside the hosting service and review trial-volume
retention before depending on it. This deployment setup does not establish
clinical suitability, continuous monitoring availability or validated email
delivery.

## Local checks for this entry point

```text
python -B -m unittest tests.test_cloud_start -v
```

These checks use synthetic credentials and temporary directories, mock the web
server, and do not connect to Firebase, Railway, SMTP or local AI.
