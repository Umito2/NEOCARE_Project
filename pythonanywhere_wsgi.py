"""Build NEOCARE for PythonAnywhere's standard WSGI hosting and HTTPS edge.

The provider WSGI configuration imports ``application``. Startup is deferred to
the first request in each worker, after uWSGI has forked the master process.
"""

import asyncio
import atexit
from concurrent.futures import Future
from contextlib import ExitStack
import os
from pathlib import Path
import threading

from cloud_start import CloudConfigurationError, credential_file, validate_public_credentials
from pythonanywhere_start import load_private_settings, prepare_database


def build_application():
    """Return a WSGI callable with startup complete and an idempotent close()."""
    home = Path.home()
    settings = load_private_settings(home)
    _, credentials = validate_public_credentials(settings)
    database_path = prepare_database(home)
    os.environ.update(settings)
    os.environ["NEOCARE_RECOMMENDATION_MODE"] = "rules"
    os.environ["NEOCARE_SQLITE_JOURNAL_MODE"] = "DELETE"
    os.environ["NEOCARE_AUTH_DB"] = str(database_path)

    resources = ExitStack()
    resources.callback(os.umask, os.umask(0o077))
    loop = thread = lifecycle = stopping = None
    closed = False
    owner_pid = os.getpid()

    def close():
        nonlocal closed
        if closed or os.getpid() != owner_pid:
            return
        closed = True
        try:
            if lifecycle is not None:
                if stopping is not None:
                    loop.call_soon_threadsafe(stopping.set)
                else:
                    lifecycle.cancel()
                try:
                    lifecycle.result(timeout=10)
                except Exception:
                    lifecycle.cancel()
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=10)
                if not thread.is_alive():
                    loop.close()
        finally:
            resources.close()
            atexit.unregister(close)

    try:
        path = resources.enter_context(credential_file(credentials))
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
        os.environ.pop("FIREBASE_SERVICE_ACCOUNT_JSON", None)
        from a2wsgi import ASGIMiddleware
        from api import app

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="neocare-asgi", daemon=True)
        thread.start()
        adapter = ASGIMiddleware(app, loop=loop)
        ready = Future()

        async def run_lifespan():
            nonlocal stopping
            stopping = asyncio.Event()
            try:
                # Enter and exit on one task so context-variable tokens remain valid.
                async with app.router.lifespan_context(app):
                    ready.set_result(None)
                    await stopping.wait()
            except BaseException as error:
                if not ready.done():
                    ready.set_exception(error)
                raise

        lifecycle = asyncio.run_coroutine_threadsafe(run_lifespan(), loop)
        ready.result(timeout=30)
        adapter.close = close
        atexit.register(close)
        return adapter
    except Exception:
        close()
        raise CloudConfigurationError(
            "NEOCARE WSGI startup failed; verify private settings, dependencies, and persistent storage."
        ) from None


class LazyApplication:
    """Initialize the adapter once per worker, never while importing in master."""

    def __init__(self, factory=None):
        self._factory = factory if factory is not None else build_application
        self._lock = threading.Lock()
        self._application = None
        self._pid = os.getpid()
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    def _after_fork(self):
        # Also recover if a caller forked while another thread held the lock.
        self._lock = threading.Lock()
        self._application = None
        self._pid = os.getpid()

    def __call__(self, environ, start_response):
        with self._lock:
            if self._pid != os.getpid():
                self._application = None
                self._pid = os.getpid()
            if self._application is None:
                self._application = self._factory()
            application = self._application
        return application(environ, start_response)


application = LazyApplication()
