# NEOCARE on Firebase Hosting with the PythonAnywhere API

Firebase Hosting serves the public interface at
`https://neocare-system.web.app` and
`https://neocare-system.firebaseapp.com`. Both addresses include HTTPS and need
no purchased domain. The Python application continues to run at
`https://umito.pythonanywhere.com`; Firebase Hosting does not execute Python.
The interface calls that API for login, records, alerts, recommendations and
PDF reports. The PythonAnywhere address also remains a complete interface and
is the fallback if a browser cannot retain the hosted interface's login cookie.

This configuration uses static Hosting features available on Firebase's Spark
plan and PythonAnywhere's free Beginner account. Deployment does not enable
Cloud Run, Cloud Functions, a billing account, or
paid resources. Cloud Run integration would require billing even when usage fits
its free allowance. See [Hosting overview](https://firebase.google.com/docs/hosting)
and [Cloud Run requirements](https://firebase.google.com/docs/hosting/cloud-run).

## What is published

Run the builder from the project directory with Python 3.10 or newer:

```bash
python build_firebase.py
```

The public directory is always `deployment-artifacts/firebase-public` and contains
exactly these files:

```text
index.html
assets/neocare-i18n.js
assets/hosting-config.js
```

The first two are copied from their source files. The generated configuration
contains only the public API address `https://umito.pythonanywhere.com`.
The builder rejects source/output links, reparse points and unexpected output
files or directories. It never recursively deletes a directory. If it finds an
unexpected entry, investigate and move that entry out of the public directory
before building again. Do not change Hosting's public directory to the project
root or upload the entire project folder.

Python source, credentials, tokens, SQLite databases, parent records, backups,
PDF files, fonts used by the server, Ollama and downloaded AI models are excluded.
Firebase project and site names are public identifiers, not credentials. Service
account keys remain private on PythonAnywhere. Database access continues through
the authenticated API; the public interface receives no Firebase Admin key and
does not require opening Realtime Database rules to public reads or writes.

The backend keeps rule-based recommendations, as configured by
`pythonanywhere_wsgi.py`. No local AI model is uploaded or required. Follow
[the PythonAnywhere deployment guide](PYTHONANYWHERE_DEPLOY.md) to update the
backend while preserving its separate private settings and persistent database.

## Allow the two Firebase interface addresses

Set the exact origins in PythonAnywhere's provider WSGI configuration **before**
importing or initializing the app:

```python
import os
import sys

os.environ["NEOCARE_WEB_ORIGINS"] = (
    "https://neocare-system.web.app,"
    "https://neocare-system.firebaseapp.com"
)
sys.path.insert(0, "/home/UMITO/neocare")
from pythonanywhere_wsgi import LazyApplication
application = LazyApplication()
```

Do not include trailing slashes, paths, wildcards or localhost in this list.
Do not add this key to the private settings JSON, which accepts its documented
five keys only. Keep PythonAnywhere's **Force HTTPS** enabled and reload the web
app after updating its code and WSGI configuration.

The API allows credentialed browser requests from those explicit origins. Its
hosted session uses a separate `HttpOnly`, `Secure`, `SameSite=None`, `Partitioned`
cookie. Sessions are scoped to each top-level site; signing in at the
PythonAnywhere address does not automatically sign in at a Firebase address.
Keep `https://neocare-system.web.app` as the main link to avoid switching between
separate sign-in sessions.

Use a modern browser with partitioned-cookie support. Older browsers or restrictive
privacy settings can prevent the cross-site session from persisting. If sign-in
cannot persist, open `https://umito.pythonanywhere.com` and sign in there; its
same-origin interface does not depend on this cross-site cookie. See
[partitioned cookies](https://developer.mozilla.org/en-US/docs/Web/Privacy/Guides/Third-party_cookies/Partitioned_cookies)
and [credentialed cross-origin requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS).

## Deploy and verify

With the Firebase CLI installed and signed into an authorized account, build and
deploy Hosting only:

```bash
python build_firebase.py
firebase deploy --only hosting --project neocare-system
```

`firebase.json` fixes the Hosting site to `neocare-system` and runs the builder
again as a predeploy check. Python must be available as `python` on PATH when
using this CLI hook. An automated Hosting REST deployment must run the builder
and validate the three-file allowlist immediately before creating its version;
REST deployments do not execute CLI hooks. Neither deployment path should deploy
database rules, Functions or Cloud Run. See the
[Hosting quickstart](https://firebase.google.com/docs/hosting/quickstart).

Check the Firebase HTTPS homepage and both assets, then verify login, logout,
authenticated account access and a PDF generated from synthetic readings.
Confirm the API's responses to the two allowed origins include the corresponding
origin and credentials headers, while an unrelated origin is refused.
`https://umito.pythonanywhere.com/health` is a liveness check; it does not by itself
prove that Firebase, email or every application workflow works. Do not create or
copy real patient records for deployment tests.

All three public files use `Cache-Control: no-store` to avoid stale configuration
or UI after a release. Hosting adds MIME-sniffing, framing and referrer protection;
the API remains responsible for protecting authenticated response data.

## Free limits and maintenance

As checked on 30 October 2026, Firebase Hosting includes **10 GB stored content**
and **10 GB data transfer per month** at no cost. Stored historical releases count
toward the storage limit. On Spark, exceeding storage can block new deployments;
exceeding transfer can disable the site after a grace period until the next month.
Keep the project on Spark and review usage rather than enabling billing to bypass
the limit. See [current Hosting quotas](https://firebase.google.com/docs/hosting/usage-quotas-pricing).

PythonAnywhere's free account has one web worker, 512 MiB of disk space and a
one-month web-app expiry that must be renewed. Renew the web app in its dashboard
before its displayed expiry date and monitor disk usage, including report storage
and the SQLite database. See [free account limits](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/).

The API must remain online for the Firebase interface to work. Moving the public
interface does not migrate backend accounts, alert PDFs or stored readings, and
it does not remove PythonAnywhere's capacity and renewal limits. This free
deployment is for demonstrations and evaluation; deployment and passing software
tests do not establish clinical safety or an availability guarantee for patient
monitoring.
