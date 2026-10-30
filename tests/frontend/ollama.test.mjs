import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => {
  browser = await startBrowser();
  console.log(`Local AI interface tests: ${browser.version}; synthetic API responses only.`);
});
after(async () => { if (browser) await browser.close(); });

async function withReportPage(t) {
  const page = await browser.page({ role: 'parent' });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'No uncaught browser errors or unhandled rejections');
  });
  await page.waitFor(`document.querySelector('#workspace').checkVisibility() && !document.querySelector('#generate-report').disabled`);
  return page;
}

test('successful local generation identifies Ollama in the report and completion message', async (t) => {
  const page = await withReportPage(t);
  await page.evaluate(`window.__fixture.reports.child_01.recommendation_source='Local AI (Ollama)';`);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  const reportText = await page.evaluate(`document.querySelector('#sensor-report').textContent`);
  assert.match(reportText, /Local AI recommendations \(Ollama\)/);
  assert.match(reportText, /generated locally with Ollama/);
  assert.doesNotMatch(reportText, /OpenAI/);
  assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Report ready.*local AI \(Ollama\)/);
});

test('fallback report clearly shows rule-based source and the provider failure notice', async (t) => {
  const page = await withReportPage(t);
  await page.evaluate(`window.__fixture.reports.child_01.recommendation_source='Rule-based fallback'; window.__fixture.reports.child_01.recommendation_notice='Local AI is unavailable. Start Ollama and make sure the configured model is downloaded. Showing rule-based guidance instead.';`);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  const reportText = await page.evaluate(`document.querySelector('#sensor-report').textContent`);
  assert.match(reportText, /Rule-based recommendations/);
  assert.match(reportText, /Local AI is unavailable.*Start Ollama/);
  assert.doesNotMatch(reportText, /Local AI recommendations \(Ollama\)/);
  assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Rule-based recommendations are shown/);
});

test('critical report identifies immediate safety guidance without claiming AI is unavailable', async (t) => {
  const page = await withReportPage(t);
  await page.evaluate(`window.__fixture.reports.child_01.risk_status='Critical'; window.__fixture.reports.child_01.recommendation_source='Rule-based safety guidance'; window.__fixture.reports.child_01.recommendation_notice='Urgent guidance is provided immediately without waiting for AI.';`);
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  const reportText = await page.evaluate(`document.querySelector('#sensor-report').textContent`);
  assert.match(reportText, /Immediate safety guidance/);
  assert.match(reportText, /Urgent guidance is provided immediately without waiting for AI/);
  assert.doesNotMatch(reportText, /unavailable|Local AI recommendations \(Ollama\)/);
  assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Urgent guidance.*without waiting for AI/);
});

test('long local generation keeps progress visible and prevents duplicate requests during sensor polling', async (t) => {
  const page = await withReportPage(t);
  await page.evaluate(`window.__fixture.reports.child_01.recommendation_source='Local AI (Ollama)'; window.__fixture.deferredRequests['/api/v1/children/child_01/report/latest']=new Promise(resolve=>{ window.__completeLocalReport=resolve; }); void 0;`);
  await page.click('#generate-report');
  assert.equal(await page.evaluate(`document.querySelector('#generate-report').disabled`), true);
  assert.match(await page.evaluate(`document.querySelector('#generate-report').textContent`), /Generating report/);
  assert.equal(await page.visible('#report-status'), true);
  const progressText = await page.evaluate(`document.querySelector('#report-status').textContent`);
  assert.match(progressText, /Generating recommendations/);
  assert.doesNotMatch(progressText, /local AI|Ollama|OpenAI/);
  await page.evaluate(`window.__fixture.readings.child_01.heart_rate_bpm=111; window.__fixture.intervals.forEach(timer=>timer.callback());`);
  await page.waitFor(`document.querySelector('#sensor-hr').textContent==='111'`);
  assert.equal(await page.evaluate(`document.querySelector('#generate-report').disabled`), true);
  assert.doesNotMatch(await page.evaluate(`document.querySelector('#sensor-status').textContent`), /Respiratory rate and activity are needed/);
  await page.click('#generate-report');
  assert.equal(await page.evaluate(`window.__fixture.calls.filter(call=>call.path==='/api/v1/children/child_01/report/latest').length`), 1);
  await page.evaluate('window.__completeLocalReport()');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility() && !document.querySelector('#generate-report').disabled`);
  assert.equal(await page.evaluate(`document.querySelector('#generate-report').textContent`), 'Generate report from latest reading');
  assert.match(await page.evaluate(`document.querySelector('#report-status').textContent`), /Report ready/);
});
