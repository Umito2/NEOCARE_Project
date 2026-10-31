# NEOCARE

A Python web application and Android app for viewing children's sensor readings,
managing clinic alerts, and generating PDF reports. The interface supports
English, Arabic, light/dark mode, and a custom theme color picker.

- [Open the website](https://neocare-system.web.app)
- [Download the Android APK](https://github.com/Umito2/NEOCARE_Project/releases/latest)
- [Read the latest test report](docs/TEST_REPORT.md)

## Important files

| Files | Purpose |
| --- | --- |
| `api.py`, `main.py`, `assessment.py`, `auth_store.py` | API, Firebase access, assessment rules, accounts and alert storage |
| `index.html`, `neocare-i18n.js`, `hosting-config.js`, `hosted_ui.py` | Interface, translations and secure hosted sessions |
| `firebase.json`, `.firebaserc`, `database.rules.json`, `build_firebase.py` | Firebase Hosting and private database rules |
| `pythonanywhere_*.py`, `cloud_start.py`, `requirements*.txt` | Backend startup, shared credential helpers and dependencies |
| `android/`, `.github/workflows/` | Android source, signed APK build and automated checks |
| `assets/`, `backup_neocare.py` | Licensed PDF fonts and backup/recovery utility |
| `tests/`, `run_tests.py`, `docs/` | Regression tests, setup guides and verification results |

## Setup and deployment

- [Local setup, optional local AI, features and backups](docs/PROJECT_GUIDE.md)
- [Firebase Hosting setup](docs/FIREBASE_HOSTING.md)
- [PythonAnywhere backend setup](docs/PYTHONANYWHERE_DEPLOY.md)
- [Android installation and build instructions](android/README.md)

Firebase Hosting serves the interface. PythonAnywhere runs the backend, and
Firebase Realtime Database is accessed through that authenticated backend.
The cloud deployment uses rule-based recommendations. The local launcher scripts
support optional Ollama; downloaded AI models are excluded from this repository.

## Tests

From the repository root:

```sh
python -m pip install -r requirements-dev.txt
python run_tests.py
node --test --test-timeout=60000 tests/frontend/*.test.mjs
```

Browser tests require Chrome. The manual **Build Android APK** GitHub workflow
runs Linux backend checks, Android tests, lint and the signed release build.
See the [test report](docs/TEST_REPORT.md) for coverage and remaining limitations.

Credentials, patient databases, generated reports, backups and signing keys remain
private. Passing software tests does not establish clinical safety for patient use.
