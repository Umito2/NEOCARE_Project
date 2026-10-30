import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { if (browser) await browser.close(); });
const alert = { alert_id: 1, child_id: 'child_01', child_name: 'Test Child A', severity: 'Warning', subject: 'Review requested', message: 'Synthetic reading notice', email_status: 'not_configured', created_at: 1700000000, pdf_available: false, workflow_status: 'new', notes: [] };
async function pageFor(t, options = {}) {
  const page = await browser.page(options);
  t.after(async () => { const errors = await page.evaluate('window.__fixture.errors'); await page.close(); assert.deepEqual(errors, []); });
  await page.waitFor(options.signedOut ? `document.querySelector('#auth-card').checkVisibility()` : `document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length===2 && !document.querySelector('#refresh-history').disabled`);
  return page;
}
async function fillHistory(page) {
  await page.evaluate(`window.__fixture.histories.child_01=[{timestamp:new Date(Date.now()-120000).toISOString(),heart_rate_bpm:101,spo2_percent:98,temperature_c:36.5,respiratory_rate_br_min:22},{timestamp:new Date(Date.now()-60000).toISOString(),heart_rate_bpm:null,spo2_percent:97,temperature_c:36.6,respiratory_rate_br_min:null},{timestamp:new Date().toISOString(),heart_rate_bpm:119,spo2_percent:99,temperature_c:36.7,respiratory_rate_br_min:25}];`);
  await page.click('#refresh-history');
  await page.waitFor(`document.querySelectorAll('#history-table-body tr').length===3`);
}

test('history plots only actual measurements and exposes missing fields in an accessible table', async (t) => {
  const page = await pageFor(t);
  await fillHistory(page);
  assert.equal(await page.evaluate(`document.querySelectorAll('#history-chart .chart-point').length`), 2);
  assert.equal(await page.evaluate(`document.querySelectorAll('#history-chart .chart-line').length`), 0);
  assert.equal(await page.evaluate(`document.querySelector('#history-table-body tr:nth-child(2) td:nth-child(2)').textContent`), 'Not provided');
  assert.match(await page.evaluate(`document.querySelector('#history-chart-description').textContent`), /2 recorded measurements/);
});

test('history period control requests seven-day data and handles an empty response honestly', async (t) => {
  const page = await pageFor(t);
  await page.change('#history-period', '7d');
  await page.waitFor(`window.__fixture.calls.some(call=>call.path.endsWith('/readings/history?period=7d')) && !document.querySelector('#refresh-history').disabled`);
  assert.equal(await page.visible('#history-figure'), false);
  assert.match(await page.evaluate(`document.querySelector('#history-status').textContent`), /No recorded measurements/);
});

test('history failure shows a retryable error and clears the old plot', async (t) => {
  const page = await pageFor(t);
  await fillHistory(page);
  await page.evaluate(`window.__fixture.failures['/api/v1/children/child_01/readings/history?period=24h']='Synthetic history failure';`);
  await page.click('#refresh-history');
  await page.waitFor(`document.querySelector('#history-status').textContent.includes('Synthetic history failure')`);
  assert.equal(await page.visible('#history-figure'), false);
  assert.equal(await page.evaluate(`document.querySelector('#refresh-history').disabled`), false);
});

test('a late history response cannot restore the previous child chart', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__fixture.histories.child_01=[{timestamp:new Date().toISOString(),heart_rate_bpm:177}]; window.__fixture.deferredRequests['/api/v1/children/child_01/readings/history?period=24h']=new Promise(resolve=>window.__releaseHistory=resolve); void 0;`);
  await page.click('#refresh-history');
  await page.change('#sensor-child', 'child_02');
  await page.waitFor(`document.querySelector('#history-status').textContent==='No recorded measurements in this time range.'`);
  await page.evaluate('window.__releaseHistory()');
  await page.settle(100);
  assert.equal(await page.visible('#history-figure'), false);
  assert.equal(await page.evaluate(`document.querySelectorAll('#history-table-body tr').length`), 0);
});

test('device status reports API stale and missing-field information without claiming hardware is online', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__fixture.readings.child_01.freshness={status:'stale',last_received:new Date(Date.now()-600000).toISOString(),age_seconds:600,max_age_seconds:300,missing_fields:['respiratory_rate_br_min','activity_state']};`);
  await page.click('#refresh-sensors');
  assert.match(await page.evaluate(`document.querySelector('#device-connection').textContent`), /No recent device readings/);
  assert.match(await page.evaluate(`document.querySelector('#device-missing').textContent`), /Respiratory rate.*Activity/);
  assert.equal(await page.evaluate(`document.querySelector('#device-status').classList.contains('is-stale')`), true);
});

test('doctor acknowledges an alert and saves an internal note', async (t) => {
  const page = await pageFor(t, { role: 'doctor', alerts: [alert] });
  await page.waitFor(`document.querySelector('.alert-workflow-form') !== null`);
  await page.evaluate(`document.querySelector('.alert-review').open=true; document.querySelector('.alert-workflow-form select').value='acknowledged'; document.querySelector('.alert-workflow-form textarea').value='Synthetic clinician note'; document.querySelector('.alert-workflow-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('.workflow-badge').textContent==='Acknowledged'`);
  assert.match(await page.evaluate(`document.querySelector('.alert-notes').textContent`), /Synthetic clinician note/);
  const request = await page.evaluate(`window.__fixture.calls.find(call=>call.method==='PATCH')`);
  assert.deepEqual(request.body, { workflow_status: 'acknowledged', note: 'Synthetic clinician note' });
});

test('parent sees workflow state but no internal notes, lifecycle controls, or doctor management API requests', async (t) => {
  const page = await pageFor(t, { role: 'parent', alerts: [{ ...alert, workflow_status: 'resolved', notes: [{ text: 'Private clinician note', author: 'Doctor', created_at: 1700000000 }] }] });
  await page.waitFor(`document.querySelector('.workflow-badge') !== null`);
  assert.equal(await page.evaluate(`document.querySelector('.workflow-badge').textContent`), 'Resolved');
  assert.equal(await page.evaluate(`document.querySelectorAll('.alert-workflow-form,.alert-notes').length`), 0);
  assert.doesNotMatch(await page.evaluate(`document.querySelector('#alert-list').textContent`), /Private clinician note/);
  assert.equal(await page.evaluate(`window.__fixture.calls.some(call=>call.path==='/api/v1/doctor/accounts' || call.path==='/api/v1/doctor/audit')`), false);
});

test('unsaved clinician note and selected workflow state survive automatic polling', async (t) => {
  const page = await pageFor(t, { role: 'doctor', alerts: [alert] });
  await page.waitFor(`document.querySelector('.alert-workflow-form') !== null`);
  await page.evaluate(`document.querySelector('.alert-review').open=true; document.querySelector('.alert-workflow-form textarea').value='Unsaved note'; document.querySelector('.alert-workflow-form select').value='resolved'; window.__oldAlertForm=document.querySelector('.alert-workflow-form'); window.__fixture.intervals.forEach(timer=>timer.callback());`);
  await page.waitFor(`document.querySelector('.alert-workflow-form') !== window.__oldAlertForm`);
  assert.equal(await page.evaluate(`document.querySelector('.alert-workflow-form textarea').value`), 'Unsaved note');
  assert.equal(await page.evaluate(`document.querySelector('.alert-workflow-form select').value`), 'resolved');
});

test('doctor account creation refreshes the list and clears the submitted password', async (t) => {
  const page = await pageFor(t, { role: 'doctor' });
  await page.evaluate(`document.querySelector('#doctor-management').open=true; document.querySelector('#doctor-account-username').value='new.clinician'; document.querySelector('#doctor-account-name').value='New Clinician'; document.querySelector('#doctor-account-password').value='synthetic-password-123'; document.querySelector('#doctor-account-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#doctor-account-list').textContent.includes('New Clinician')`);
  assert.equal(await page.evaluate(`document.querySelector('#doctor-account-password').value`), '');
  assert.equal(await page.evaluate(`document.querySelectorAll('#doctor-account-list li').length`), 2);
});

test('audit table shows returned actor, action, and target data', async (t) => {
  const page = await pageFor(t, { role: 'doctor' });
  await page.evaluate(`window.__fixture.auditEvents=[{actor_role:'doctor',actor_id:'17',action:'alert.updated',target:'alert:1',created_at:1700000000}]; document.querySelector('#audit-panel').open=true;`);
  await page.click('#refresh-audit');
  await page.waitFor(`document.querySelectorAll('#audit-table-body tr').length===1`);
  assert.match(await page.evaluate(`document.querySelector('#audit-table-body').textContent`), /Doctor 17.*Alert updated.*alert:1/);
});

test('Arabic mode translates static and dynamic controls with RTL and preserves patient names', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__fixture.profiles[0].name='Normal';`);
  await page.click('#refresh-button');
  await page.click('[data-language="ar"]');
  await page.waitFor(`document.documentElement.dir==='rtl' && document.querySelector('#history-title').textContent==='سجل القراءات'`);
  assert.equal(await page.evaluate(`document.querySelector('.child-name').textContent`), 'Normal');
  assert.equal(await page.evaluate(`document.querySelector('#dashboard-title').textContent`), 'لوحة ولي الأمر');
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility() && document.querySelector('#report-status').textContent.includes('التقرير جاهز')`);
  assert.match(await page.evaluate(`document.querySelector('#sensor-report').textContent`), /توصيات مستندة إلى القواعد/);
  await page.click('[data-language="en"]');
  await page.waitFor(`document.querySelector('#dashboard-title').textContent==='Parent dashboard'`);
  assert.equal(await page.evaluate(`document.documentElement.dir`), 'ltr');
  assert.equal(await page.evaluate(`document.querySelector('.child-name').textContent`), 'Normal');
});

test('Arabic mobile history and controls fit the viewport', async (t) => {
  const page = await pageFor(t, { viewport: { width: 390, height: 844, mobile: true } });
  await fillHistory(page);
  await page.click('[data-language="ar"]');
  await page.waitFor(`document.documentElement.lang==='ar'`);
  assert.equal(await page.evaluate(`document.documentElement.scrollWidth <= innerWidth + 1`), true);
  assert.equal(await page.evaluate(`document.querySelector('#history-chart').getBoundingClientRect().right <= innerWidth + 1`), true);
});

test('old clinician alerts and notes are cleared before a new account whose data fails to load', async (t) => {
  const page = await pageFor(t, { role: 'doctor', alerts: [{ ...alert, notes: [{ text: 'Sensitive old clinician note', author: 'Doctor', created_at: 1700000000 }] }] });
  await page.waitFor(`document.querySelector('.alert-notes') !== null`);
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
  await page.evaluate(`window.__fixture.failures['/api/v1/children']='New account unavailable'; document.querySelector('#login-role').value='parent'; document.querySelector('#login-identifier').value='new-parent@example.test'; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility()`);
  assert.equal(await page.evaluate(`document.querySelector('#alert-list').childElementCount`), 0);
  assert.equal(await page.evaluate(`document.querySelector('#profile-list').childElementCount`), 0);
  assert.doesNotMatch(await page.evaluate(`document.querySelector('#workspace').textContent`), /Sensitive old clinician note/);
});
