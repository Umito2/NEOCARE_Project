import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { if (browser) await browser.close(); });
const alert = { alert_id: 1, child_id: 'child_01', child_name: 'Test Child A', severity: 'Warning', message: 'Synthetic private report', created_at: 1700000000, pdf_available: true };

async function pageFor(t, options = {}) {
  const page = await browser.page({ role: 'doctor', alerts: [alert], ...options });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught browser failures');
  });
  await page.waitFor(`document.querySelectorAll('#profile-list tbody tr').length===2 && document.querySelector('#alert-list button') !== null`);
  return page;
}

// Hold a response AFTER the fixture snapshots its payload, accurately modelling
// an earlier request arriving late instead of rereading newer fixture state.
async function holdResponse(page, path, key, { method = 'GET', status, body } = {}) {
  await page.evaluate(`(() => {
    const baseFetch=window.fetch;
    window.__held ||= {};
    const held=window.__held[${JSON.stringify(key)}]={arrived:false,released:false};
    let used=false;
    window.fetch=async (...args)=>{
      let response=await baseFetch(...args);
      const path=new URL(String(args[0]),'https://fixture.test').pathname;
      if (!used && path===${JSON.stringify(path)} && (args[1]?.method||'GET')===${JSON.stringify(method)}) {
        used=true;
        ${status ? `response=new Response(${JSON.stringify(JSON.stringify(body))},{status:${status},headers:{'Content-Type':'application/json'}});` : ''}
        held.arrived=true;
        await new Promise(resolve=>held.release=resolve);
        held.released=true;
      }
      return response;
    };
  })()`);
}

async function release(page, key) {
  await page.evaluate(`window.__held[${JSON.stringify(key)}].release()`);
  await page.waitFor(`window.__held[${JSON.stringify(key)}].released`);
  await page.settle(60);
}

async function signOut(page) {
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
}

async function signIn(page, role = 'parent') {
  await page.change('#login-role', role);
  await page.evaluate(`document.querySelector('#login-identifier').value=${JSON.stringify(role === 'parent' ? 'second@example.test' : 'second-clinic')}; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length===2`);
}

for (const fails of [false, true]) {
  test(`an older same-child reading ${fails ? 'error' : 'success'} cannot overwrite a newer successful refresh`, async (t) => {
    const page = await pageFor(t);
    await holdResponse(page, '/api/v1/children/child_01/readings/latest', 'oldReading', fails ? { status: 503, body: { detail: 'Obsolete sensor failure' } } : {});
    await page.evaluate('void refreshSensorReading()');
    await page.waitFor('window.__held.oldReading.arrived');
    await page.evaluate(`window.__fixture.readings.child_01.heart_rate_bpm=123;`);
    await page.evaluate('refreshSensorReading()');
    assert.equal(await page.evaluate(`document.querySelector('#sensor-hr').textContent`), '123');
    await release(page, 'oldReading');
    assert.equal(await page.evaluate(`document.querySelector('#sensor-hr').textContent`), '123');
    assert.doesNotMatch(await page.evaluate(`document.querySelector('#sensor-status').textContent`), /Obsolete/);
  });
}

test('an older profile poll cannot replace newly refreshed profile details', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/children', 'oldProfiles');
  await page.evaluate('void loadProfiles({refreshReading:false,background:true})');
  await page.waitFor('window.__held.oldProfiles.arrived');
  await page.evaluate(`window.__fixture.profiles[0].name='Updated Synthetic Child';`);
  await page.evaluate('loadProfiles({refreshReading:false})');
  await release(page, 'oldProfiles');
  assert.match(await page.evaluate(`document.querySelector('#profile-list').textContent`), /Updated Synthetic Child/);
});

test('a saved-alert PDF completing after logout cannot download into another session', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__downloads=[]; HTMLAnchorElement.prototype.click=function(){window.__downloads.push(this.download);};`);
  await holdResponse(page, '/api/v1/alerts/1/pdf', 'oldPdf');
  await page.click('#alert-list [aria-label="Download alert report for Test Child A"]');
  await page.waitFor('window.__held.oldPdf.arrived');
  await signOut(page);
  await signIn(page);
  await release(page, 'oldPdf');
  assert.deepEqual(await page.evaluate('window.__downloads'), []);
});

test('an old alert deletion completion cannot show success in a different account', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/alerts/1', 'oldDelete', { method: 'DELETE' });
  await page.click('.delete-alert-button');
  await page.waitFor('window.__held.oldDelete.arrived');
  await signOut(page);
  await signIn(page);
  const before = await page.evaluate(`window.__fixture.calls.filter(call=>call.path==='/api/v1/alerts').length`);
  await release(page, 'oldDelete');
  assert.doesNotMatch(await page.evaluate(`document.querySelector('#dashboard-message').textContent`), /Alert deleted/);
  assert.equal(await page.evaluate(`window.__fixture.calls.filter(call=>call.path==='/api/v1/alerts').length`), before);
});

test('detached previous-session alert buttons cannot issue deletion or PDF requests', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__oldAlertButtons=[...document.querySelectorAll('#alert-list .alert-actions button')];`);
  await signOut(page);
  await signIn(page, 'doctor');
  const before = await page.evaluate('window.__fixture.calls.length');
  await page.evaluate('window.__oldAlertButtons.forEach(button=>button.click())');
  await page.settle(60);
  const calls = await page.evaluate(`window.__fixture.calls.slice(${before})`);
  assert.equal(calls.some(call => call.path === '/api/v1/alerts/1/pdf' || call.method === 'DELETE'), false);
});

test('expired authentication clears private dashboard data and explains sign-in', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`(() => { const original=window.fetch; window.fetch=async(...args)=>String(args[0]).endsWith('/api/v1/children')?new Response(JSON.stringify({detail:'Please sign in.'}),{status:401,headers:{'Content-Type':'application/json'}}):original(...args); })()`);
  await page.click('#refresh-button');
  await page.settle(60);
  assert.equal(await page.visible('#auth-card'), true);
  assert.equal(await page.visible('#workspace'), false);
  assert.equal(await page.evaluate(`document.querySelector('#profile-list').childElementCount+document.querySelector('#alert-list').childElementCount`), 0);
  assert.match(await page.evaluate(`document.querySelector('#auth-message').textContent`), /session.*sign in/i);
  assert.equal(await page.visible('#logout-button'), false);
});

test('clinic thresholds and result messages are cleared when leaving the session', async (t) => {
  const page = await pageFor(t);
  assert.equal(await page.evaluate(`document.querySelector('#th-spo2').value`), '95');
  await signOut(page);
  assert.equal(await page.evaluate(`document.querySelector('#th-spo2').value`), '');
});

test('a delayed threshold response cannot repopulate the signed-out clinic form', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/doctor/alert-thresholds', 'oldThresholds');
  await page.evaluate('void loadDoctorThresholds()');
  await page.waitFor('window.__held.oldThresholds.arrived');
  await signOut(page);
  await release(page, 'oldThresholds');
  assert.equal(await page.evaluate(`document.querySelector('#th-spo2').value`), '');
});

test('a delayed dashboard startup stops follow-up clinic requests after logout', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/children', 'startupProfiles');
  await page.evaluate(`void enterDashboard({role:'doctor',display_name:'Synthetic Clinic'})`);
  await page.waitFor('window.__held.startupProfiles.arrived');
  await signOut(page);
  const before = await page.evaluate('window.__fixture.calls.length');
  await release(page, 'startupProfiles');
  assert.deepEqual(await page.evaluate(`window.__fixture.calls.slice(${before}).map(call=>call.path)`), []);
});

test('an old unauthorized response cannot sign out a newly authenticated account', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/children/child_01/readings/latest', 'oldUnauthorized', { status: 401, body: { detail: 'Expired old session' } });
  await page.evaluate('void refreshSensorReading()');
  await page.waitFor('window.__held.oldUnauthorized.arrived');
  await signOut(page);
  await signIn(page);
  await release(page, 'oldUnauthorized');
  assert.equal(await page.visible('#workspace'), true);
  assert.equal(await page.visible('#auth-card'), false);
  assert.equal(await page.evaluate(`document.querySelector('#dashboard-title').textContent`), 'Parent dashboard');
  assert.equal(await page.evaluate(`document.querySelector('#sensor-hr').textContent`), '110');
});

test('a PDF unauthorized response clears the session without downloading private content', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__downloads=[]; HTMLAnchorElement.prototype.click=function(){window.__downloads.push(this.download);};`);
  await holdResponse(page, '/api/v1/alerts/1/pdf', 'expiredPdf', { status: 401, body: { detail: 'Please sign in.' } });
  await page.click('#alert-list [aria-label="Download alert report for Test Child A"]');
  await page.waitFor('window.__held.expiredPdf.arrived');
  await release(page, 'expiredPdf');
  assert.equal(await page.visible('#auth-card'), true);
  assert.equal(await page.visible('#workspace'), false);
  assert.deepEqual(await page.evaluate('window.__downloads'), []);
});

test('expired-session explanation is translated in Arabic and permits signing in again', async (t) => {
  const page = await pageFor(t);
  await page.click('[data-language="ar"]');
  await holdResponse(page, '/api/v1/children', 'expiredArabic', { status: 401, body: { detail: 'Please sign in.' } });
  await page.click('#refresh-button');
  await page.waitFor('window.__held.expiredArabic.arrived');
  await release(page, 'expiredArabic');
  assert.match(await page.evaluate(`document.querySelector('#auth-message').textContent`), /انتهت جلستك/);
  await signIn(page);
  assert.equal(await page.visible('#workspace'), true);
  assert.equal(await page.evaluate(`document.querySelector('#refresh-button').disabled`), false);
});

test('a delayed clinic-threshold save cannot update feedback or refresh a different account', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/doctor/alert-thresholds', 'oldThresholdSave', { method: 'PUT' });
  await page.evaluate(`document.querySelector('#threshold-form').requestSubmit()`);
  await page.waitFor('window.__held.oldThresholdSave.arrived');
  await signOut(page);
  await signIn(page);
  const before = await page.evaluate('window.__fixture.calls.length');
  await release(page, 'oldThresholdSave');
  assert.equal(await page.evaluate(`document.querySelector('#threshold-message').textContent`), '');
  assert.equal(await page.evaluate('window.__fixture.calls.length'), before);
  assert.equal(await page.evaluate(`document.querySelector('#threshold-form button[type="submit"]').disabled`), false);
});

test('an older alert list cannot undo a newly loaded workflow status', async (t) => {
  const page = await pageFor(t);
  await holdResponse(page, '/api/v1/alerts', 'oldAlerts');
  await page.evaluate('void loadAlerts()');
  await page.waitFor('window.__held.oldAlerts.arrived');
  await page.evaluate(`window.__fixture.alerts[0].workflow_status='resolved';`);
  await page.evaluate('loadAlerts()');
  await release(page, 'oldAlerts');
  assert.equal(await page.evaluate(`document.querySelector('.workflow-badge').textContent`), 'Resolved');
});

test('old profile-edit controls cannot populate another account with the previous child details', async (t) => {
  const page = await pageFor(t);
  await page.evaluate(`window.__oldEdit=document.querySelector('[data-profile-action="edit"]');`);
  await signOut(page);
  await signIn(page);
  await page.evaluate('window.__oldEdit.click()');
  assert.equal(await page.visible('#parent-profile-card'), false);
  assert.equal(await page.evaluate(`document.querySelector('#name').value`), '');
});
