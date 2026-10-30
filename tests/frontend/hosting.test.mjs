import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

// Actual UI in Chrome with intercepted synthetic responses. These tests check
// routing and request options, not browser acceptance of real cross-site cookies.
const API_ORIGIN = 'https://umito.pythonanywhere.com';
let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { if (browser) await browser.close(); });

async function pageFor(t, options = {}) {
  const page = await browser.page(options);
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught page errors');
  });
  await page.waitFor(options.signedOut
    ? `document.querySelector('#auth-card').checkVisibility()`
    : `document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length===2 && !document.querySelector('#refresh-history').disabled`);
  return page;
}

function assertRouting(calls, origin = '') {
  assert.ok(calls.length > 0);
  for (const call of calls) {
    assert.equal(call.url, origin + call.path, `Destination for ${call.path}`);
    assert.equal(call.credentials, origin ? 'include' : 'same-origin', `Cookie mode for ${call.path}`);
    assert.equal(call.redirect, 'error');
    assert.equal(call.headers.authorization, undefined, 'No JavaScript authentication token');
  }
}

for (const [label, options] of [
  ['default configuration', {}],
  ['absent configuration', { hostingConfig: null }],
]) {
  test(`${label} preserves same-origin health and dashboard requests`, async (t) => {
    const page = await pageFor(t, options);
    const calls = await page.evaluate('window.__fixture.calls');
    for (const path of ['/health', '/api/v1/auth/me', '/api/v1/children']) assert.ok(calls.some(call => call.path === path));
    assertRouting(calls);
  });
}

test('hosted configuration routes health, profiles, readings, history and alerts to the approved HTTPS API', async (t) => {
  const page = await pageFor(t, { hostingConfig: { apiOrigin: API_ORIGIN } });
  await page.waitFor(`window.__fixture.calls.some(call=>call.path==='/api/v1/alerts')`);
  const calls = await page.evaluate('window.__fixture.calls');
  for (const path of ['/health', '/api/v1/auth/me', '/api/v1/children', '/api/v1/children/child_01/readings/latest', '/api/v1/children/child_01/readings/history?period=24h', '/api/v1/alerts']) {
    assert.ok(calls.some(call => call.path === path), path);
  }
  assertRouting(calls, API_ORIGIN);
  assert.equal(await page.evaluate(`document.querySelector('#health-label').textContent`), 'Server connected');
});

test('hosted clinic login and logout retain cookie transport without browser tokens', async (t) => {
  const page = await pageFor(t, { signedOut: true, hostingConfig: { apiOrigin: API_ORIGIN }, localStorage: {} });
  await page.change('#login-role', 'doctor');
  await page.evaluate(`document.querySelector('#login-identifier').value='synthetic-clinic'; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#threshold-card').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length===2`);
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
  const calls = await page.evaluate('window.__fixture.calls');
  assert.ok(calls.some(call => call.path === '/api/v1/auth/login' && call.method === 'POST'));
  assert.ok(calls.some(call => call.path === '/api/v1/auth/logout' && call.method === 'POST'));
  assertRouting(calls, API_ORIGIN);
  assert.deepEqual(await page.evaluate(`Array.from({length:localStorage.length},(_,index)=>localStorage.key(index)).filter(key=>!['neocare-theme','neocare-language'].includes(key))`), []);
  assert.equal(await page.evaluate(`document.querySelector('#login-password').value`), '');
});

test('hosted parent registration and profile updates use the same approved API', async (t) => {
  const page = await pageFor(t, { signedOut: true, hostingConfig: { apiOrigin: API_ORIGIN } });
  await page.click('#show-signup');
  await page.evaluate(`(() => {
    const values={'signup-parent-name':'Synthetic Parent','signup-email':'parent@example.test','signup-phone':'01000000000','signup-password':'synthetic-password-123','signup-child-name':'Synthetic Child','signup-age':'4','signup-height':'102','signup-weight':'16.5'};
    Object.entries(values).forEach(([id,value])=>document.getElementById(id).value=value);
    document.querySelector('#signup-form').requestSubmit();
  })()`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length===2`);
  await page.click('[data-profile-action="edit"][data-child-id="child_01"]');
  await page.evaluate(`document.querySelector('#name').value='Updated Synthetic Child'; document.querySelector('#profile-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#dashboard-message').textContent.includes('Updated Synthetic Child')`);
  const calls = await page.evaluate('window.__fixture.calls');
  assert.equal(calls.find(call => call.path === '/api/v1/auth/signup').body.child_name, 'Synthetic Child');
  assert.equal(calls.find(call => call.method === 'PUT').body.name, 'Updated Synthetic Child');
  assertRouting(calls, API_ORIGIN);
});

test('hosted report generation, PDF download and clinician sharing retain the selected child', async (t) => {
  const page = await pageFor(t, { role: 'doctor', hostingConfig: { apiOrigin: API_ORIGIN } });
  await page.change('#sensor-child', 'child_02');
  await page.waitFor(`!document.querySelector('#generate-report').disabled`);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.click('#sensor-report [aria-label="Download report for Test Child B"]');
  await page.click('#sensor-report [aria-label="Send Test Child B\'s report to their parent"]');
  await page.waitFor(`document.querySelector('#dashboard-message').textContent==='Test report sent'`);
  const calls = await page.evaluate('window.__fixture.calls');
  for (const suffix of ['', '/pdf', '/send']) assert.ok(calls.some(call => call.path === `/api/v1/children/child_02/report/latest${suffix}`));
  assertRouting(calls, API_ORIGIN);
});

test('saved-alert PDF downloads also use the approved hosted API and cookies', async (t) => {
  const page = await pageFor(t, { hostingConfig: { apiOrigin: API_ORIGIN }, alerts: [{
    alert_id: 7, child_id: 'child_01', child_name: 'Test Child A', severity: 'Normal', message: 'Synthetic saved report', created_at: 1700000000, pdf_available: true,
  }] });
  await page.waitFor(`document.querySelector('#alert-list [aria-label="Download alert report for Test Child A"]') !== null`);
  await page.click('#alert-list [aria-label="Download alert report for Test Child A"]');
  await page.waitFor(`window.__fixture.calls.some(call=>call.path==='/api/v1/alerts/7/pdf')`);
  assertRouting(await page.evaluate('window.__fixture.calls'), API_ORIGIN);
});

for (const origin of ['http://umito.pythonanywhere.com', 'https://umito.pythonanywhere.com.attacker.test', 'https://umito.pythonanywhere.com/private']) {
  test(`invalid configured origin is rejected before sending credentials: ${origin}`, async (t) => {
    const page = await pageFor(t, { signedOut: true, hostingConfig: { apiOrigin: origin } });
    await page.evaluate(`document.querySelector('#login-identifier').value='parent@example.test'; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
    await page.waitFor(`document.querySelector('#auth-message').textContent.includes('not configured correctly')`);
    assert.deepEqual(await page.evaluate('window.__fixture.calls'), []);
    assert.equal(await page.visible('#workspace'), false);
  });
}

test('browser storage cannot override the deployment API origin', async (t) => {
  const page = await pageFor(t, { localStorage: { apiOrigin: 'https://attacker.test', 'neocare-api-origin': API_ORIGIN } });
  assertRouting(await page.evaluate('window.__fixture.calls'));
});

test('request helper rejects absolute URLs and keeps the configured credential policy', async (t) => {
  const page = await pageFor(t, { hostingConfig: { apiOrigin: API_ORIGIN } });
  const result = await page.evaluate(`(async () => {
    const before=window.__fixture.calls.length;
    const errors=[];
    for (const path of ['https://attacker.test/api/v1/children','//attacker.test/api/v1/children','/assets/neocare-i18n.js']) {
      try { await apiFetch(path); } catch(error) { errors.push(error.message); }
    }
    const blockedCalls=window.__fixture.calls.length-before;
    await apiFetch('/health',{credentials:'omit',redirect:'follow'});
    return {errors,blockedCalls,last:window.__fixture.calls.at(-1)};
  })()`);
  assert.equal(result.errors.length, 3);
  assert.equal(result.blockedCalls, 0);
  assertRouting([result.last], API_ORIGIN);
});
