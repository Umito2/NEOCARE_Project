import { spawn } from 'node:child_process';
import { existsSync, appendFileSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const sourceHtml = await readFile(resolve(projectRoot, 'index.html'), 'utf8');
const translationScript = await readFile(resolve(projectRoot, 'neocare-i18n.js'), 'utf8');
const hostingConfigScript = await readFile(resolve(projectRoot, 'hosting-config.js'), 'utf8');
// Inline the actual local translation asset because browser network access is blocked.
const html = sourceHtml.replace('<script src="/assets/neocare-i18n.js"></script>', () => `<script>${translationScript}</script>`);

class CDP {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 0;
    this.pending = new Map();
    this.ready = new Promise((resolveReady, reject) => {
      const timer = setTimeout(() => {
        this.socket.close();
        reject(new Error('CDP WebSocket connection timed out'));
      }, 5000);
      this.socket.addEventListener('open', () => { clearTimeout(timer); resolveReady(); }, { once: true });
      this.socket.addEventListener('error', (error) => { clearTimeout(timer); reject(error); }, { once: true });
    });
    this.socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      if (!message.id) return;
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      clearTimeout(waiter.timer);
      if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
      else waiter.resolve(message.result);
    });
  }

  async send(method, params = {}) {
    await this.ready;
    const id = ++this.nextId;
    return new Promise((resolveResult, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, 10000);
      this.pending.set(id, { resolve: resolveResult, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() { this.socket.close(); }
}

// Installs deterministic API fixtures before the original, unmodified page script runs.
// All browser fetch calls are intercepted here; no service credentials are read.
function installFixtures(options) {
  // about:blank has an opaque origin, so opt-in storage fixtures model the
  // browser Storage API without touching a developer's browser profile.
  if (options.localStorage !== undefined || options.storageFailure) {
    const values = new Map(Object.entries(options.localStorage || {}).map(([key, value]) => [key, String(value)]));
    const checkStorage = (operation) => {
      if (options.storageFailure === 'all' || options.storageFailure === operation) {
        throw new DOMException('Synthetic storage access denied', 'SecurityError');
      }
    };
    const storage = {
      get length() { checkStorage('read'); return values.size; },
      key(index) { checkStorage('read'); return [...values.keys()][index] ?? null; },
      getItem(key) { checkStorage('read'); return values.get(String(key)) ?? null; },
      setItem(key, value) { checkStorage('write'); values.set(String(key), String(value)); },
      removeItem(key) { checkStorage('write'); values.delete(String(key)); },
      clear() { checkStorage('write'); values.clear(); },
    };
    Object.defineProperty(window, 'localStorage', { configurable: true, value: storage });
  }
  const now = new Date().toISOString();
  const reading = (childId) => ({
    child_id: childId, status: 'available', timestamp: now,
    heart_rate_bpm: 110, spo2_percent: 98, temperature_c: 36.8,
    respiratory_rate_br_min: 25, activity_state: 'Resting',
  });
  const profile = (childId, name) => ({
    child_id: childId, name, age_years: 4, height_cm: 102, weight_kg: 16.5,
    risk_status: 'Normal', parent_email: 'parent@example.test',
    latest_reading: reading(childId),
  });
  const report = (childId) => ({
    child_id: childId, child_name: childId === 'child_01' ? 'Test Child A' : 'Test Child B',
    age_years: 4, timestamp: now, risk_status: 'Normal', condition: 'Test assessment',
    causes: ['Test cause'], recommendations: ['Test recommendation'],
    recommendation_source: 'Local', recommendation_notice: '',
    safety_recommendations: [], additional_recommendations: [],
    activity_state: 'Resting', heart_rate_bpm: 110, spo2_percent: 98,
    temperature_c: 36.8, respiratory_rate_br_min: 25,
  });
  window.__fixture = {
    user: options.signedOut ? null : {
      role: options.role || 'parent', display_name: 'Test User', child_id: 'child_01',
    },
    profiles: [profile('child_01', 'Test Child A'), profile('child_02', 'Test Child B')],
    readings: { child_01: reading('child_01'), child_02: reading('child_02') },
    reports: { child_01: report('child_01'), child_02: report('child_02') },
    histories: { child_01: [], child_02: [] },
    doctors: [{ doctor_id: 1, username: 'testclinic', display_name: 'Test Clinician', created_at: 1700000000 }],
    auditEvents: [],
    alerts: options.alerts || [], calls: [], failures: {}, intervals: [], errors: [],
    confirmResult: options.confirmResult ?? true, confirmations: [],
    deferredRequests: {},
  };
  window.addEventListener('error', (event) => window.__fixture.errors.push(event.message));
  window.addEventListener('unhandledrejection', (event) => {
    window.__fixture.errors.push(String(event.reason));
    event.preventDefault();
  });
  window.setInterval = (callback, interval) => {
    window.__fixture.intervals.push({ callback, interval });
    return window.__fixture.intervals.length;
  };
  window.confirm = (message) => {
    window.__fixture.confirmations.push(message);
    return window.__fixture.confirmResult;
  };
  window.print = () => {};
  window.fetch = async (url, options = {}) => {
    const state = window.__fixture;
    const requestUrl = String(url);
    const parsedUrl = new URL(requestUrl, 'https://synthetic-neocare.test');
    const path = parsedUrl.pathname + parsedUrl.search;
    const method = options.method || 'GET';
    const body = options.body ? JSON.parse(options.body) : undefined;
    state.calls.push({ path, method, body, url: requestUrl, credentials: options.credentials,
      redirect: options.redirect, headers: Object.fromEntries(new Headers(options.headers || {})) });
    if (state.deferredRequests[path]) await state.deferredRequests[path];
    const reply = (data, status = 200) => new Response(JSON.stringify(data), {
      status, headers: { 'Content-Type': 'application/json' },
    });
    if (state.failures[path]) return reply({ detail: state.failures[path] }, 503);
    if (path === '/health') return reply({ status: 'ok' });
    if (path === '/api/v1/auth/me') return state.user
      ? reply(state.user) : reply({ detail: 'Sign in required' }, 401);
    if (path === '/api/v1/auth/login') {
      state.user = { role: body.role, display_name: 'Test User', child_id: 'child_01' };
      return reply(state.user);
    }
    if (path === '/api/v1/auth/logout') { state.user = null; return reply({ status: 'ok' }); }
    if (path === '/api/v1/auth/signup') {
      state.user = { role: 'parent', display_name: body.parent_name, child_id: 'child_01' };
      return reply(state.user);
    }
    if (path === '/api/v1/alerts') return reply(state.alerts.map((alert) => {
      if (state.user?.role === 'doctor') return alert;
      const { notes, ...visible } = alert;
      return visible;
    }));
    if (path === '/api/v1/doctor/accounts') {
      if (state.user?.role !== 'doctor') return reply({ detail: 'Doctor access required' }, 403);
      if (method === 'POST') {
        const doctor = { doctor_id: state.doctors.length + 1, username: body.username, display_name: body.display_name, created_at: Date.now() / 1000 };
        state.doctors.push(doctor);
        return reply({ status: 'created', doctor_id: doctor.doctor_id }, 201);
      }
      return reply({ doctors: state.doctors });
    }
    if (path === '/api/v1/doctor/audit') {
      if (state.user?.role !== 'doctor') return reply({ detail: 'Doctor access required' }, 403);
      return reply({ events: state.auditEvents });
    }
    const alertPdfRoute = path.match(/^\/api\/v1\/alerts\/([^/]+)\/pdf$/);
    if (alertPdfRoute && method === 'GET') {
      const alert = state.alerts.find((entry) => String(entry.alert_id) === decodeURIComponent(alertPdfRoute[1]));
      if (!alert?.pdf_available) return reply({ detail: 'Alert PDF not found' }, 404);
      return new Response('%PDF-synthetic-alert', { headers: { 'Content-Type': 'application/pdf' } });
    }
    const alertRoute = path.match(/^\/api\/v1\/alerts\/([^/]+)$/);
    if (alertRoute && method === 'PATCH') {
      if (!state.user) return reply({ detail: 'Sign in required' }, 401);
      if (state.user.role !== 'doctor') return reply({ detail: 'Doctor access required' }, 403);
      const alert = state.alerts.find((entry) => String(entry.alert_id) === decodeURIComponent(alertRoute[1]));
      if (!alert) return reply({ detail: 'Alert not found' }, 404);
      if (body.workflow_status) alert.workflow_status = body.workflow_status;
      if (body.note) (alert.notes ||= []).push({ text: body.note, author: state.user.display_name, created_at: Date.now() / 1000 });
      return reply({ status: 'updated', alert_id: alert.alert_id });
    }
    if (alertRoute && method === 'DELETE') {
      if (!state.user) return reply({ detail: 'Sign in required' }, 401);
      if (state.user.role !== 'doctor') return reply({ detail: 'Doctor access required' }, 403);
      const alertId = decodeURIComponent(alertRoute[1]);
      if (!state.alerts.some((alert) => String(alert.alert_id) === alertId)) {
        return reply({ detail: 'Alert not found' }, 404);
      }
      state.alerts = state.alerts.filter((alert) => String(alert.alert_id) !== alertId);
      return reply({ status: 'deleted', alert_id: Number(alertId) });
    }
    if (path === '/api/v1/doctor/alert-thresholds') return reply({ thresholds: {
      spo2_min: 95, temperature_warning_c: 38, temperature_critical_c: 39,
      heart_rate_max_age_0_3: 150, heart_rate_max_age_over_3: 130,
      respiratory_rate_max_age_0_3: 40, respiratory_rate_max_age_over_3: 30,
    } });
    if (path === '/api/v1/children') {
      if (method === 'POST') {
        const created = { ...body, child_id: 'child_03' };
        state.profiles.push(created);
        return reply(created);
      }
      return reply(state.profiles);
    }
    const childRoute = path.match(/^\/api\/v1\/children\/(child_\d+)(.*)$/);
    if (childRoute) {
      const [, id, suffix] = childRoute;
      if (suffix === '/readings/latest') return reply(state.readings[id] || { status: 'waiting' });
      if (suffix.startsWith('/readings/history?period=')) return reply({
        child_id: id, period: suffix.split('period=')[1], readings: state.histories[id] || [], sampled: false,
      });
      if (suffix === '/report/latest') return reply(state.reports[id]);
      if (suffix === '/report/latest/send') return reply({ message: 'Test report sent', email_status: 'sent' });
      if (suffix === '/report/latest/pdf') return new Response('%PDF-test-fixture', {
        headers: { 'Content-Type': 'application/pdf' },
      });
      if (!suffix && method === 'PUT') {
        const target = state.profiles.find((item) => item.child_id === id);
        Object.assign(target, body);
        return reply(target);
      }
      if (!suffix && method === 'DELETE') {
        state.profiles = state.profiles.filter((item) => item.child_id !== id);
        return reply({ status: 'deleted' });
      }
    }
    throw new Error(`Unstubbed fetch prevented: ${method} ${path}`);
  };
}

export async function startBrowser() {
  const executable = process.env.NEOCARE_TEST_BROWSER || [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ].find(existsSync);
  if (!executable) throw new Error('No Chrome/Edge found; set NEOCARE_TEST_BROWSER to a Chromium binary.');
  const artifactRoot = resolve(projectRoot, 'test-results/frontend');
  await mkdir(artifactRoot, { recursive: true });
  const profileDir = await mkdtemp(resolve(artifactRoot, 'browser-profile-'));
  const browserProcess = spawn(executable, [
    '--headless=new', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
    `--user-data-dir=${profileDir}`, '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-component-update', '--disable-sync',
    '--disable-default-apps', '--disable-extensions', '--disable-features=MediaRouter',
    '--metrics-recording-only', '--no-pings', '--proxy-server=http://127.0.0.1:9',
    '--proxy-bypass-list=<-loopback>', 'about:blank',
  ], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  const killOwnedBrowser = () => {
    if (browserProcess.exitCode === null) browserProcess.kill();
  };
  process.once('exit', killOwnedBrowser);
  let browserStderr = '';
  browserProcess.stderr.on('data', (data) => {
    browserStderr += data.toString();
    appendFileSync(resolve(artifactRoot, 'browser-stderr.log'), data);
  });
  let launchError;
  browserProcess.once('error', (error) => { launchError = error; });
  let debugPort;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (launchError) throw launchError;
    try {
      debugPort = (await readFile(resolve(profileDir, 'DevToolsActivePort'), 'utf8')).split('\n')[0];
      break;
    } catch {}
    if (browserProcess.exitCode !== null) throw new Error(`Browser exited: ${browserStderr}`);
    await delay(100);
  }
  if (!debugPort) { browserProcess.kill(); throw new Error(`Browser did not start: ${browserStderr}`); }
  const version = await fetch(`http://127.0.0.1:${debugPort}/json/version`, { signal: AbortSignal.timeout(5000) }).then((response) => response.json());
  const browserCDP = new CDP(version.webSocketDebuggerUrl);
  await browserCDP.ready;
  return {
    version: version.Browser,
    profileDir,
    async page(options = {}) {
      const { targetId } = await browserCDP.send('Target.createTarget', { url: 'about:blank' });
      const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`, { signal: AbortSignal.timeout(5000) }).then((response) => response.json());
      const pageCDP = new CDP(targets.find((target) => target.id === targetId).webSocketDebuggerUrl);
      await pageCDP.send('Page.enable');
      await pageCDP.send('Network.enable');
      await pageCDP.send('Network.setBlockedURLs', { urls: ['http://*', 'https://*', 'ws://*', 'wss://*'] });
      const emulatedMedia = { media: 'screen', reducedMotion: undefined, colorScheme: undefined };
      const applyEmulatedMedia = () => pageCDP.send('Emulation.setEmulatedMedia', {
        media: emulatedMedia.media,
        features: [
          ...(emulatedMedia.reducedMotion === undefined ? [] : [{ name: 'prefers-reduced-motion', value: emulatedMedia.reducedMotion ? 'reduce' : 'no-preference' }]),
          ...(emulatedMedia.colorScheme === undefined ? [] : [{ name: 'prefers-color-scheme', value: emulatedMedia.colorScheme }]),
        ],
      });
      const page = {
        async evaluate(expression) {
          const result = await pageCDP.send('Runtime.evaluate', {
            expression, awaitPromise: true, returnByValue: true, userGesture: true,
          });
          if (result.exceptionDetails) throw new Error(
            result.exceptionDetails.exception?.description || result.exceptionDetails.text,
          );
          return result.result.value;
        },
        async settle(milliseconds = 30) {
          await page.evaluate(`new Promise(resolve => setTimeout(resolve, ${Number(milliseconds)}))`);
        },
        async waitFor(expression, timeoutMs = 5000) {
          const deadline = Date.now() + timeoutMs;
          do {
            if (await page.evaluate(expression)) return;
            await delay(20);
          } while (Date.now() < deadline);
          throw new Error(`Timed out waiting for browser condition: ${expression}`);
        },
        async click(selector) {
          await page.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
          await page.settle();
        },
        async change(selector, value) {
          await page.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); element.value = ${JSON.stringify(value)}; element.dispatchEvent(new Event('change', { bubbles: true })); })()`);
          await page.settle();
        },
        async visible(selector) {
          return page.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); return Boolean(element && element.checkVisibility()); })()`);
        },
        async viewport(width, height, { mobile = false } = {}) {
          if (!Number.isInteger(width) || !Number.isInteger(height) || width < 240 || height < 240) {
            throw new Error('Viewport dimensions must be integer pixels of at least 240');
          }
          await pageCDP.send('Emulation.setDeviceMetricsOverride', {
            width, height, deviceScaleFactor: 1, mobile,
          });
          await pageCDP.send('Emulation.setTouchEmulationEnabled', { enabled: mobile });
          await page.settle();
        },
        async reducedMotion(enabled = true) {
          emulatedMedia.reducedMotion = enabled;
          await applyEmulatedMedia();
          await page.settle();
        },
        async colorScheme(scheme = 'light') {
          if (!['light', 'dark'].includes(scheme)) throw new Error('Unsupported emulated color scheme');
          emulatedMedia.colorScheme = scheme;
          await applyEmulatedMedia();
          await page.settle();
        },
        async media(type = 'screen') {
          if (!['screen', 'print', ''].includes(type)) throw new Error('Unsupported emulated media type');
          emulatedMedia.media = type;
          await applyEmulatedMedia();
          await page.settle();
        },
        async focus(selector) {
          await page.evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
        },
        async press(key, { shift = false } = {}) {
          const keys = {
            Tab: { code: 'Tab', number: 9 },
            Enter: { code: 'Enter', number: 13, text: '\r' },
            Escape: { code: 'Escape', number: 27 },
            Space: { key: ' ', code: 'Space', number: 32, text: ' ' },
            ArrowLeft: { code: 'ArrowLeft', number: 37 },
            ArrowUp: { code: 'ArrowUp', number: 38 },
            ArrowRight: { code: 'ArrowRight', number: 39 },
            ArrowDown: { code: 'ArrowDown', number: 40 },
          };
          const definition = keys[key];
          if (!definition) throw new Error(`Unsupported test keyboard key: ${key}`);
          const params = {
            key: definition.key || key, code: definition.code,
            windowsVirtualKeyCode: definition.number, nativeVirtualKeyCode: definition.number,
            modifiers: shift ? 8 : 0,
          };
          await pageCDP.send('Input.dispatchKeyEvent', {
            type: 'keyDown', ...params, ...(definition.text ? { text: definition.text } : {}),
          });
          await pageCDP.send('Input.dispatchKeyEvent', { type: 'keyUp', ...params });
          await page.settle();
        },
        async screenshot(filename, { fullPage = false } = {}) {
          if (basename(filename) !== filename || !filename.endsWith('.png')) {
            throw new Error('Screenshot name must be a PNG filename without directory components');
          }
          await page.evaluate('document.fonts.ready.then(() => true)');
          const screenshotDirectory = resolve(artifactRoot, 'screenshots');
          await mkdir(screenshotDirectory, { recursive: true });
          const params = { format: 'png', fromSurface: true, captureBeyondViewport: fullPage };
          if (fullPage) {
            const { cssContentSize } = await pageCDP.send('Page.getLayoutMetrics');
            params.clip = { x: 0, y: 0, width: cssContentSize.width, height: cssContentSize.height, scale: 1 };
          }
          const { data } = await pageCDP.send('Page.captureScreenshot', params);
          const outputPath = resolve(screenshotDirectory, filename);
          await writeFile(outputPath, Buffer.from(data, 'base64'));
          return outputPath;
        },
        async close() { pageCDP.close(); await browserCDP.send('Target.closeTarget', { targetId }); },
      };
      if (options.viewport) await page.viewport(options.viewport.width, options.viewport.height, { mobile: options.viewport.mobile || false });
      if (options.reducedMotion !== undefined) await page.reducedMotion(options.reducedMotion);
      if (options.colorScheme !== undefined) await page.colorScheme(options.colorScheme);
      await page.evaluate(`(${installFixtures.toString()})(${JSON.stringify(options)})`);
      const { frameTree } = await pageCDP.send('Page.getFrameTree');
      const configScript = Object.hasOwn(options, 'hostingConfig')
        ? options.hostingConfig === null ? '' : `window.NEOCARE_HOSTING_CONFIG=Object.freeze(${JSON.stringify(options.hostingConfig).replaceAll('<', '\\u003c')});`
        : hostingConfigScript;
      const configuredHtml = html.replace('<script src="/assets/hosting-config.js"></script>', () => `<script>${configScript}</script>`);
      const pageHtml = options.observeThemeInitialization
        ? configuredHtml.replace(/(<body\b[^>]*>)/i, '$1<script>window.__fixture.themeAtBodyStart=document.documentElement.getAttribute("data-theme");</script>')
        : configuredHtml;
      await pageCDP.send('Page.setDocumentContent', { frameId: frameTree.frame.id, html: pageHtml });
      await page.settle();
      return page;
    },
    async close() {
      try { await browserCDP.send('Browser.close'); } catch {}
      browserCDP.close();
      await Promise.race([
        new Promise((resolveExit) => browserProcess.once('exit', resolveExit)), delay(1000),
      ]);
      if (browserProcess.exitCode === null) browserProcess.kill();
      process.removeListener('exit', killOwnedBrowser);
      // Only remove this harness's newly-created profile, after checking the
      // resolved path remains directly inside the test artifact directory.
      const resolvedProfile = await realpath(profileDir);
      const resolvedArtifacts = await realpath(artifactRoot);
      if (dirname(resolvedProfile) !== resolvedArtifacts || !basename(resolvedProfile).startsWith('browser-profile-')) {
        throw new Error('Refusing to remove a profile outside test artifacts');
      }
      await rm(resolvedProfile, { recursive: true, force: false, maxRetries: 8, retryDelay: 250 });
    },
  };
}
