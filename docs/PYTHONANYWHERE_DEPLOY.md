# NEOCARE on PythonAnywhere, without local AI

The free Beginner account currently offers one website at
`https://USERNAME.pythonanywhere.com`, HTTPS, and 512 MiB of persistent storage.
FastAPI runs through the `a2wsgi` adapter on standard WSGI hosting, with the
provider's Force HTTPS setting enabled. Free websites require periodic renewal. This is a demo
deployment, not an availability guarantee for patient monitoring.

References: [pricing](https://www.pythonanywhere.com/pricing/),
[free account limits](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/),
[Force HTTPS](https://help.pythonanywhere.com/pages/ForcingHTTPS/).

## Package and storage

For a Firebase-hosted interface using this same backend, follow
[FIREBASE_HOSTING.md](FIREBASE_HOSTING.md). Keep `hosted_ui.py` and the default
`hosting-config.js` in the backend package, and configure the two allowed browser
origins in the provider WSGI file before application initialization.

Upload the clean `deployment-artifacts/NEOCARE_PythonAnywhere.zip` package.
It contains application source, report fonts, and the cloud launcher files.
It excludes Ollama, downloaded AI models, laptop databases, backups, credentials,
API tokens, and development/test files. No GitHub repository is needed.

Extract into a new directory such as `/home/USERNAME/neocare`. The launcher stores
the fresh SQLite database separately at
`/home/USERNAME/neocare-data/neocare_auth.sqlite3`. Updates to application source
must preserve that directory and the private settings directory.

`pythonanywhere_wsgi.py` forces rule-based recommendations and SQLite's `DELETE`
journal mode. Local launches still default to Ollama and SQLite `WAL`.
PythonAnywhere's network filesystem does not support WAL; SQLite there is
appropriate only for limited demonstration traffic with one web worker.
[Provider guidance](https://www.pythonanywhere.com/forums/topic/36213/).

## Private settings

Create `/home/USERNAME/.config/neocare/settings.json`, owned by the account, with
mode `600`; the `neocare` configuration directory must have mode `700`.
The file contains exactly these five keys:

```json
{
  "DOCTOR_USERNAME": "NEOCARE",
  "DOCTOR_PASSWORD": "REPLACE_WITH_A_UNIQUE_PASSWORD",
  "ESP32_API_KEY": "REPLACE_WITH_A_RANDOM_DEVICE_SECRET",
  "FIREBASE_DATABASE_URL": "https://neocare-system-default-rtdb.firebaseio.com/",
  "FIREBASE_SERVICE_ACCOUNT_JSON": {}
}
```

Replace the placeholders with a unique clinic password (12–128 characters), a
random device secret (at least 24 characters), and the complete Firebase
service-account JSON object. The old local default password is not accepted by
either cloud launcher. Replace any previously exposed Firebase credential before
publishing. Actual secrets belong only in this private settings file, never in
the ZIP or source repository.

The existing Firebase database can contain profiles linked to parent IDs from
the laptop. A fresh cloud database does not automatically transfer those parent
accounts, sessions, clinician accounts, alert PDFs, notes or reading histories.
Do not assume registering the same email on the website reconnects those records.
Existing private data needs a separate, coordinated migration.

## Install and publish

Use a supported Python version of at least 3.10 in a PythonAnywhere Bash console.
For example, after confirming Python 3.13 is available:

```bash
python3.13 -m venv /home/USERNAME/.virtualenvs/neocare
/home/USERNAME/.virtualenvs/neocare/bin/python -m pip install --no-cache-dir -r /home/USERNAME/neocare/requirements-pythonanywhere.txt
```

Create a standard manually configured Python 3.13 web app, set its virtualenv to
`/home/USERNAME/.virtualenvs/neocare`, and use this WSGI configuration:

```python
import sys
sys.path.insert(0, "/home/USERNAME/neocare")
from pythonanywhere_wsgi import LazyApplication
application = LazyApplication()
```

Enable **Force HTTPS** and reload the web app. The adapter runs the application's
startup/shutdown lifecycle and uses WSGI's scheme for secure login cookies.
Initialization happens on the worker's first request, after uWSGI forks; do not
call `build_application()` directly in the provider configuration.
Use one worker. The private-settings and storage helpers remain in
`pythonanywhere_start.py`.

Do not use the experimental ASGI entry point for this deployment: live testing
found that both HTTP and HTTPS requests arrived with `X-Forwarded-Proto: http`,
preventing reliable redirects and scheme-based secure cookies.

For automation, generate an API token under Account → API token. The local
`.pythonanywhere_api_token` file is excluded from source and deployment packages.
The token can upload files and configure the WSGI website through PythonAnywhere's
API. Do not print it or put it in shell arguments. A console created through the
API must be opened once in the browser before it can execute commands.
[API documentation](https://help.pythonanywhere.com/pages/API/).

Before creating a website, check for an existing website on the same domain;
do not overwrite an unrelated app. Keep the account on Beginner and do not add
paid resources. API upload and site creation are separate from local packaging.

## Verify after deployment

Check HTTPS, `/health`, login and logout, `Secure` session cookies, authenticated
Firebase access, and a PDF generated from synthetic readings. Verify that a
synthetic record survives a controlled restart before relying on persistence.
`/health` alone does not establish Firebase connectivity.

Firebase and Google authentication domains are on the provider's HTTPS
[allowlist](https://www.pythonanywhere.com/whitelist/). Preserve PythonAnywhere's
proxy environment settings and verify connectivity from the deployed app.

Email is not configured by this package; saved alert PDFs remain available in
the portal. Keep protected backups and monitor disk usage and renewal dates.
No real email is sent by the offline tests.

## Local verification

```text
python -B -m unittest tests.test_cloud_start tests.test_pythonanywhere_start tests.test_pythonanywhere_wsgi tests.test_storage_features
```

These checks use synthetic credentials and temporary files. Linux file permission
checks must also run on the host; Windows skips the Unix-specific permission test.
