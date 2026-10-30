import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => {
  browser = await startBrowser();
  console.log(`Alert deletion tests: ${browser.version}; synthetic API responses only.`);
});
after(async () => { if (browser) await browser.close(); });

const makeAlert = (alertId, pdfAvailable = false) => ({
  alert_id: alertId,
  child_id: `child_0${alertId}`,
  child_name: `Test Child ${alertId}`,
  severity: 'Warning',
  message: 'Synthetic test alert',
  email_status: 'not_configured',
  created_at: 1700000000 + alertId,
  pdf_available: pdfAvailable,
});

async function withAlerts(t, options = {}) {
  const fixtureOptions = {
    role: 'doctor', alerts: [makeAlert(1, true), makeAlert(2)], ...options,
  };
  const page = await browser.page(fixtureOptions);
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught browser errors or unhandled rejections');
  });
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#alert-list .alert-item').length === ${fixtureOptions.alerts.length}`);
  return page;
}

test('doctor sees deletion controls for alerts with and without a saved PDF', async (t) => {
  const page = await withAlerts(t);
  assert.equal(await page.evaluate('document.querySelectorAll("#alert-list .delete-alert-button").length'), 2);
  assert.equal(await page.visible('.delete-alert-button[data-alert-id="1"]'), true);
  assert.equal(await page.visible('.delete-alert-button[data-alert-id="2"]'), true);
  assert.equal(await page.evaluate('Array.from(document.querySelectorAll("#alert-list button")).filter(button => button.textContent === "Download report PDF").length'), 1);
});

test('parent can view alerts but receives no deletion controls', async (t) => {
  const page = await withAlerts(t, { role: 'parent' });
  assert.equal(await page.evaluate('document.querySelectorAll("#alert-list .alert-item").length'), 2);
  assert.equal(await page.evaluate('document.querySelectorAll("#alert-list .delete-alert-button").length'), 0);
  assert.equal(await page.evaluate('window.__fixture.calls.some(call => call.method === "DELETE")'), false);
});

test('canceling confirmation preserves the alert and sends no delete request', async (t) => {
  const page = await withAlerts(t, { confirmResult: false });
  await page.click('.delete-alert-button[data-alert-id="1"]');
  const confirmations = await page.evaluate('window.__fixture.confirmations');
  assert.equal(confirmations.length, 1);
  assert.match(confirmations[0], /Test Child 1/);
  assert.match(confirmations[0], /clinic and parent alert histories/);
  assert.match(confirmations[0], /saved PDF/);
  assert.match(confirmations[0], /cannot be undone/i);
  assert.equal(await page.evaluate('window.__fixture.calls.some(call => call.method === "DELETE")'), false);
  assert.equal(await page.evaluate('window.__fixture.alerts.length'), 2);
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]').disabled`), false);
});

for (const pdfAvailable of [false, true]) {
  test(`confirming deletes only the selected alert (${pdfAvailable ? 'with' : 'without'} PDF) and refreshes the list`, async (t) => {
    const page = await withAlerts(t, { alerts: [makeAlert(1, pdfAvailable), makeAlert(2)] });
    await page.click('.delete-alert-button[data-alert-id="1"]');
    await page.waitFor(`document.querySelector('#dashboard-message').classList.contains('success') && document.querySelector('.delete-alert-button[data-alert-id="1"]') === null`);
    const calls = await page.evaluate('window.__fixture.calls');
    const deleteIndex = calls.findIndex((call) => call.method === 'DELETE');
    assert.notEqual(deleteIndex, -1);
    assert.equal(calls[deleteIndex].path, '/api/v1/alerts/1');
    assert.ok(calls.slice(deleteIndex + 1).some((call) => call.path === '/api/v1/alerts' && call.method === 'GET'));
    assert.deepEqual(await page.evaluate('window.__fixture.alerts.map(alert => alert.alert_id)'), [2]);
    assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]') === null`), true);
    assert.equal(await page.visible('.delete-alert-button[data-alert-id="2"]'), true);
    assert.equal(await page.visible('#dashboard-message'), true);
    assert.match(await page.evaluate('document.querySelector("#dashboard-message").textContent'), /Alert deleted.*parent histories.*saved PDF/);
    assert.equal(await page.evaluate('document.querySelector("#dashboard-message").classList.contains("success")'), true);
  });
}

test('deleting the last alert renders the empty state', async (t) => {
  const page = await withAlerts(t, { alerts: [makeAlert(1)] });
  await page.click('.delete-alert-button[data-alert-id="1"]');
  await page.waitFor(`document.querySelector('#alert-list').textContent === 'No parent alerts have been recorded.'`);
  assert.equal(await page.evaluate('document.querySelector("#alert-list").textContent'), 'No parent alerts have been recorded.');
  assert.equal(await page.evaluate('document.querySelectorAll("#alert-list button").length'), 0);
  assert.equal(await page.evaluate('window.__fixture.alerts.length'), 0);
});

test('failed deletion retains the alert and shows a visible error with retry available', async (t) => {
  const page = await withAlerts(t);
  await page.evaluate(`window.__fixture.failures['/api/v1/alerts/1'] = 'Test alert deletion failed';`);
  await page.click('.delete-alert-button[data-alert-id="1"]');
  await page.waitFor(`document.querySelector('#dashboard-message').textContent.includes('Test alert deletion failed')`);
  assert.equal(await page.evaluate('window.__fixture.alerts.length'), 2);
  assert.equal(await page.visible('.delete-alert-button[data-alert-id="1"]'), true);
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]').disabled`), false);
  assert.equal(await page.visible('#dashboard-message'), true);
  assert.equal(await page.evaluate('document.querySelector("#dashboard-message").classList.contains("error")'), true);
  assert.match(await page.evaluate('document.querySelector("#dashboard-message").textContent'), /Test alert deletion failed/);
});

test('pending deletion stays disabled across automatic refresh and prevents duplicate requests', async (t) => {
  const page = await withAlerts(t);
  await page.evaluate(`window.__fixture.deferredRequests['/api/v1/alerts/1'] = new Promise(resolve => { window.__finishAlertDelete = resolve; }); void 0;`);
  await page.click('.delete-alert-button[data-alert-id="1"]');
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]').disabled`), true);
  await page.evaluate(`window.__previousDeleteButton = document.querySelector('.delete-alert-button[data-alert-id="1"]'); window.__fixture.intervals.forEach(timer => timer.callback());`);
  await page.waitFor(`document.querySelector('.delete-alert-button[data-alert-id="1"]') !== window.__previousDeleteButton`);
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]').disabled`), true);
  await page.click('.delete-alert-button[data-alert-id="1"]');
  assert.equal(await page.evaluate('window.__fixture.calls.filter(call => call.method === "DELETE").length'), 1);
  await page.evaluate('window.__finishAlertDelete()');
  await page.waitFor(`document.querySelector('.delete-alert-button[data-alert-id="1"]') === null`);
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="1"]') === null`), true);
  assert.equal(await page.evaluate(`document.querySelector('.delete-alert-button[data-alert-id="2"]').disabled`), false);
});
