import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => {
  browser = await startBrowser();
  console.log(`Real browser: ${browser.version}; all application fetch calls use synthetic fixtures.`);
});
after(async () => { if (browser) await browser.close(); });

async function withPage(t, options = {}) {
  const page = await browser.page(options);
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught browser errors or unhandled rejections');
  });
  return page;
}

test('signed-out page shows sign-in and hides patient dashboard', async (t) => {
  const page = await withPage(t, { signedOut: true });
  assert.equal(await page.visible('#auth-card'), true);
  assert.equal(await page.visible('#workspace'), false);
});

test('switching clinic and parent roles updates login fields', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.change('#login-role', 'doctor');
  assert.equal(await page.evaluate('document.querySelector("#login-identifier-label").textContent'), 'Clinic username');
  assert.equal(await page.visible('#signup-switch'), false);
  await page.change('#login-role', 'parent');
  assert.equal(await page.evaluate('document.querySelector("#login-identifier").type'), 'email');
  assert.equal(await page.visible('#signup-switch'), true);
});

for (const role of ['parent', 'doctor']) {
  test(`${role} login enters the correct dashboard`, async (t) => {
    const page = await withPage(t, { signedOut: true });
    await page.change('#login-role', role);
    await page.evaluate(`document.querySelector('#login-identifier').value = ${JSON.stringify(role === 'parent' ? 'parent@example.test' : 'testclinic')}; document.querySelector('#login-password').value = 'test-password-123'; document.querySelector('#login-form').requestSubmit();`);
    await page.settle();
    assert.equal(await page.visible('#workspace'), true);
    assert.equal(await page.evaluate('document.querySelector("#dashboard-title").textContent'), role === 'parent' ? 'Parent dashboard' : 'Clinic overview');
    assert.equal(await page.visible('#threshold-card'), role === 'doctor');
  });
}

test('login failure is visible to a signed-out user', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.evaluate(`window.__fixture.failures['/api/v1/auth/login'] = 'Test login failure'; document.querySelector('#login-identifier').value = 'parent@example.test'; document.querySelector('#login-password').value = 'test-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.settle();
  assert.equal(await page.visible('#auth-message'), true);
  assert.match(await page.evaluate('document.querySelector("#auth-message").textContent'), /Test login failure/);
});

test('parent signup submits the supplied child data and opens dashboard', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.click('#show-signup');
  await page.evaluate(`(() => { const fields = {'signup-parent-name':'Test Parent','signup-email':'parent@example.test','signup-phone':'0000000000','signup-password':'test-password-123','signup-child-name':'Test Child A','signup-age':'4','signup-height':'102','signup-weight':'16.5'}; for (const [id,value] of Object.entries(fields)) document.getElementById(id).value=value; document.querySelector('#signup-form').requestSubmit(); })()`);
  await page.settle();
  const call = await page.evaluate('window.__fixture.calls.find(call => call.path === "/api/v1/auth/signup")');
  assert.equal(call.body.child_name, 'Test Child A');
  assert.equal(call.body.age_years, 4);
  assert.equal(await page.visible('#workspace'), true);
});

test('parent Add child opens a visible form and saves profile', async (t) => {
  const page = await withPage(t);
  await page.click('#add-child-button');
  assert.equal(await page.visible('#parent-profile-card'), true);
  await page.evaluate(`document.querySelector('#name').value='Test Child C'; document.querySelector('#age').value='2'; document.querySelector('#height').value='85'; document.querySelector('#weight').value='12'; document.querySelector('#profile-form').requestSubmit();`);
  await page.settle();
  assert.equal(await page.evaluate('window.__fixture.profiles.length'), 3);
  assert.equal(await page.visible('#parent-profile-card'), false);
  assert.match(await page.evaluate('document.querySelector("#dashboard-message").textContent'), /Child added/);
});

test('parent Edit exposes the populated form', async (t) => {
  const page = await withPage(t);
  await page.click('#profile-list .edit-button');
  assert.equal(await page.visible('#parent-profile-card'), true, 'Clicking Edit must display the form');
  assert.equal(await page.evaluate('document.querySelector("#name").value'), 'Test Child A');
});

test('clinic Edit exposes the populated form', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.click('#profile-list .edit-button');
  assert.equal(await page.visible('#parent-profile-card'), true);
  assert.equal(await page.evaluate('document.querySelector("#name").value'), 'Test Child A');
});

test('clinic profile edit submits a PUT and renders saved value', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.click('#profile-list .edit-button');
  await page.evaluate(`document.querySelector('#name').value='Updated Test Name'; document.querySelector('#profile-form').requestSubmit();`);
  await page.settle();
  const call = await page.evaluate('window.__fixture.calls.find(call => call.method === "PUT")');
  assert.equal(call.path, '/api/v1/children/child_01');
  assert.equal(call.body.name, 'Updated Test Name');
  assert.match(await page.evaluate('document.querySelector("#profile-list").textContent'), /Updated Test Name/);
});

test('missing sensor readings clear values and disable report generation', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.readings.child_01 = {status:'waiting'};`);
  await page.click('#refresh-sensors');
  assert.equal(await page.evaluate('document.querySelector("#sensor-hr").textContent'), '—');
  assert.equal(await page.evaluate('document.querySelector("#generate-report").disabled'), true);
  assert.match(await page.evaluate('document.querySelector("#sensor-status").textContent'), /No sensor readings/);
});

test('incomplete readings display available values and explain blocked reports', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.readings.child_01.respiratory_rate_br_min=null; window.__fixture.readings.child_01.activity_state=null;`);
  await page.click('#refresh-sensors');
  assert.equal(await page.evaluate('document.querySelector("#sensor-hr").textContent'), '110');
  assert.equal(await page.evaluate('document.querySelector("#sensor-resp").textContent'), 'Not provided');
  assert.equal(await page.evaluate('document.querySelector("#generate-report").disabled'), true);
  assert.match(await page.evaluate('document.querySelector("#sensor-status").textContent'), /needed for the report/);
});

test('sensor fetch errors clear values and show a visible reason', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.failures['/api/v1/children/child_01/readings/latest']='Test device unavailable';`);
  await page.click('#refresh-sensors');
  assert.equal(await page.evaluate('document.querySelector("#generate-report").disabled'), true);
  assert.equal(await page.visible('#sensor-status'), true);
  assert.match(await page.evaluate('document.querySelector("#sensor-status").textContent'), /Test device unavailable/);
});

test('old readings are explicitly identified as stale or offline', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.readings.child_01.timestamp='2000-01-01T00:00:00Z';`);
  await page.click('#refresh-sensors');
  assert.match(await page.evaluate('document.querySelector("#sensor-status").textContent'), /stale|offline|outdated|old reading|not recent|no recent/i, 'An old timestamp must not be presented as current live data');
});

test('complete readings generate a report for the selected child', async (t) => {
  const page = await withPage(t);
  await page.click('#generate-report');
  assert.equal(await page.visible('#sensor-report'), true);
  assert.match(await page.evaluate('document.querySelector(".report-subject").textContent'), /Test Child A/);
  assert.equal(await page.evaluate('Array.from(document.querySelectorAll("#sensor-report button")).find(button => button.textContent === "Send PDF to parent").hidden'), true);
});

test('changing child clears a previously generated report', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.click('#generate-report');
  await page.change('#sensor-child', 'child_02');
  assert.equal(await page.visible('#sensor-report'), false, 'Child A report must not remain under child B readings');
});

test('send report remains bound to the report shown after child selection changes', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.click('#generate-report');
  await page.change('#sensor-child', 'child_02');
  if (!await page.visible('#sensor-report')) return; // Clearing obsolete actions is also correct.
  await page.evaluate(`Array.from(document.querySelectorAll('#sensor-report button')).find(button=>button.textContent==='Send PDF to parent').click()`);
  await page.settle();
  const call = await page.evaluate('window.__fixture.calls.find(call => call.path.endsWith("/send"))');
  assert.equal(call.path, '/api/v1/children/child_01/report/latest/send', 'Send must use the displayed report child, not a later dropdown selection');
});

test('report generation failures appear in visible page content', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.failures['/api/v1/children/child_01/report/latest']='Test report generation failed';`);
  await page.click('#generate-report');
  assert.equal(await page.evaluate(`Array.from(document.querySelectorAll('.message, .sensor-status')).some(element=>element.checkVisibility() && element.textContent.includes('Test report generation failed'))`), true, 'Report errors must not be placed in a hidden profile form');
});

test('periodic refresh updates selected sensor values', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.readings.child_01.heart_rate_bpm=121; window.__fixture.intervals.forEach(timer=>timer.callback());`);
  await page.settle();
  assert.equal(await page.evaluate('document.querySelector("#sensor-hr").textContent'), '121');
});

test('periodic refresh updates clinic overview risk statuses', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.evaluate(`window.__fixture.profiles[0].risk_status='Critical'; window.__fixture.profiles[0].latest_reading.heart_rate_bpm=180; window.__fixture.intervals.forEach(timer=>timer.callback());`);
  await page.settle();
  assert.equal(await page.evaluate('document.querySelector("#profile-list .risk-status").textContent'), 'Critical', 'Clinic overview must reflect refreshed risk status');
});

test('manual profile refresh failures appear in visible page content', async (t) => {
  const page = await withPage(t);
  await page.evaluate(`window.__fixture.failures['/api/v1/children']='Test profile refresh failed';`);
  await page.click('#refresh-button');
  assert.equal(await page.evaluate(`Array.from(document.querySelectorAll('.message')).some(element=>element.checkVisibility() && element.textContent.includes('Test profile refresh failed'))`), true);
});

test('signing out hides the dashboard and returns to login', async (t) => {
  const page = await withPage(t);
  await page.click('#logout-button');
  assert.equal(await page.visible('#workspace'), false);
  assert.equal(await page.visible('#auth-card'), true);
});

test('a report from the previous account is not exposed after the next login', async (t) => {
  const page = await withPage(t);
  await page.click('#generate-report');
  await page.click('#logout-button');
  await page.evaluate(`window.__fixture.profiles=[window.__fixture.profiles[1]]; document.querySelector('#login-identifier').value='second-parent@example.test'; document.querySelector('#login-password').value='test-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.settle();
  assert.equal(await page.visible('#sensor-report'), false, 'A new account must not inherit the previous account report DOM');
  assert.doesNotMatch(await page.evaluate('document.querySelector("#sensor-report").textContent'), /Test Child A/);
});
