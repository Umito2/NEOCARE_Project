import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => {
  browser = await startBrowser();
  console.log(`Report identity tests: ${browser.version}; synthetic deferred responses only.`);
});
after(async () => { if (browser) await browser.close(); });

async function withReportPage(t) {
  const page = await browser.page({ role: 'doctor' });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught browser errors or unhandled rejections');
  });
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && !document.querySelector('#generate-report').disabled`);
  return page;
}

async function deferResponse(page, path, token) {
  await page.evaluate(`(() => {
    const path = ${JSON.stringify(path)};
    const token = ${JSON.stringify(token)};
    window.__responseState ||= {};
    window.__releaseResponses ||= {};
    window.__responseState[token] = { fetch: false, body: false };
    window.__fixture.deferredRequests[path] = new Promise(resolve => { window.__releaseResponses[token] = resolve; });
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (String(args[0]) === path) {
        window.__responseState[token].fetch = true;
        for (const method of ['json', 'blob']) {
          const originalMethod = response[method].bind(response);
          response[method] = async () => {
            try { return await originalMethod(); }
            finally { window.__responseState[token].body = true; }
          };
        }
      }
      return response;
    };
  })()`);
}

async function releaseResponse(page, token, phase = 'body') {
  await page.evaluate(`window.__releaseResponses[${JSON.stringify(token)}]()`);
  await page.waitFor(`window.__responseState[${JSON.stringify(token)}][${JSON.stringify(phase)}]`);
}

async function selectChild(page, childId) {
  await page.change('#sensor-child', childId);
  await page.waitFor(`document.querySelector('#sensor-child').value === ${JSON.stringify(childId)} && !document.querySelector('#generate-report').disabled`);
}

test('changing child clears the visible report and makes its detached action buttons inert', async (t) => {
  const page = await withReportPage(t);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.evaluate(`window.__oldReportButtons = Array.from(document.querySelectorAll('#sensor-report button'));`);
  await selectChild(page, 'child_02');
  assert.equal(await page.visible('#sensor-report'), false);
  assert.equal(await page.evaluate(`document.querySelector('#sensor-report').childElementCount`), 0);
  await page.evaluate(`window.__oldReportButtons.forEach(button => button.click());`);
  assert.equal(await page.evaluate(`window.__fixture.calls.some(call => call.path.endsWith('/report/latest/send') || call.path.endsWith('/report/latest/pdf'))`), false);
});

test('a late report for the previous child is discarded after selection changes', async (t) => {
  const page = await withReportPage(t);
  await deferResponse(page, '/api/v1/children/child_01/report/latest', 'oldChild');
  await page.click('#generate-report');
  await selectChild(page, 'child_02');
  await releaseResponse(page, 'oldChild');
  assert.equal(await page.visible('#sensor-report'), false);
  assert.equal(await page.visible('#report-status'), false);
  assert.equal(await page.evaluate(`document.querySelector('#generate-report').disabled`), false);
});

for (const oldFails of [false, true]) {
  test(`an old child report ${oldFails ? 'failure' : 'success'} cannot overwrite a newer request or end its progress`, async (t) => {
    const page = await withReportPage(t);
    const oldPath = '/api/v1/children/child_01/report/latest';
    await deferResponse(page, oldPath, 'oldChild');
    if (oldFails) await page.evaluate(`window.__fixture.failures[${JSON.stringify(oldPath)}] = 'Obsolete report error';`);
    await page.click('#generate-report');
    await selectChild(page, 'child_02');
    await deferResponse(page, '/api/v1/children/child_02/report/latest', 'newChild');
    await page.click('#generate-report');
    await releaseResponse(page, 'oldChild');
    assert.equal(await page.visible('#sensor-report'), false);
    assert.equal(await page.evaluate(`document.querySelector('#generate-report').disabled`), true);
    assert.match(await page.evaluate(`document.querySelector('#generate-report').textContent`), /Generating report/);
    assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Generating recommendations/);
    assert.doesNotMatch(await page.evaluate(`document.querySelector('#dashboard-message').textContent`), /Obsolete report error/);
    await releaseResponse(page, 'newChild');
    await page.waitFor(`document.querySelector('#sensor-report').checkVisibility() && !document.querySelector('#generate-report').disabled`);
    assert.match(await page.evaluate(`document.querySelector('.report-subject').textContent`), /Test Child B/);
  });
}

test('logout and a new login invalidate an old report even when both accounts select the same child ID', async (t) => {
  const page = await withReportPage(t);
  const path = '/api/v1/children/child_01/report/latest';
  await deferResponse(page, path, 'oldSession');
  await page.click('#generate-report');
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
  assert.equal(await page.evaluate(`document.querySelector('#sensor-report').childElementCount`), 0);
  await page.change('#login-role', 'doctor');
  await page.evaluate(`document.querySelector('#login-identifier').value='second-clinic'; document.querySelector('#login-password').value='test-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && !document.querySelector('#generate-report').disabled`);
  await deferResponse(page, path, 'newSession');
  await page.click('#generate-report');
  await releaseResponse(page, 'oldSession');
  assert.equal(await page.visible('#sensor-report'), false);
  assert.equal(await page.evaluate(`document.querySelector('#generate-report').disabled`), true);
  assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Generating recommendations/);
  await releaseResponse(page, 'newSession');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility() && !document.querySelector('#generate-report').disabled`);
  assert.match(await page.evaluate(`document.querySelector('.report-subject').textContent`), /Test Child A/);
});

test('a PDF response from the previous child does not download after selection changes', async (t) => {
  const page = await withReportPage(t);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.evaluate(`window.__downloadNames=[]; HTMLAnchorElement.prototype.click=function(){window.__downloadNames.push(this.download);};`);
  await deferResponse(page, '/api/v1/children/child_01/report/latest/pdf', 'oldPdf');
  await page.evaluate(`Array.from(document.querySelectorAll('#sensor-report button')).find(button=>button.textContent==='Download recommendation PDF').click();`);
  await page.waitFor(`window.__fixture.calls.some(call=>call.path==='/api/v1/children/child_01/report/latest/pdf')`);
  await selectChild(page, 'child_02');
  await releaseResponse(page, 'oldPdf', 'fetch');
  assert.deepEqual(await page.evaluate('window.__downloadNames'), []);
  assert.equal(await page.visible('#sensor-report'), false);
});

test('current report send and download actions use its captured child ID', async (t) => {
  const page = await withReportPage(t);
  await selectChild(page, 'child_02');
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.evaluate(`window.__downloadNames=[]; HTMLAnchorElement.prototype.click=function(){window.__downloadNames.push(this.download);}; Array.from(document.querySelectorAll('#sensor-report button')).find(button=>button.textContent==='Download recommendation PDF').click();`);
  await page.waitFor('window.__downloadNames.length === 1');
  await page.evaluate(`Array.from(document.querySelectorAll('#sensor-report button')).find(button=>button.textContent==='Send PDF to parent').click();`);
  await page.waitFor(`window.__fixture.calls.some(call=>call.path==='/api/v1/children/child_02/report/latest/send')`);
  assert.deepEqual(await page.evaluate('window.__downloadNames'), ['NEOCARE_child_02_Report.pdf']);
  const actions = await page.evaluate(`window.__fixture.calls.filter(call=>call.path.endsWith('/report/latest/pdf') || call.path.endsWith('/report/latest/send')).map(call=>call.path)`);
  assert.deepEqual(actions, ['/api/v1/children/child_02/report/latest/pdf', '/api/v1/children/child_02/report/latest/send']);
});
