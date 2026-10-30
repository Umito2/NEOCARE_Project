// Capture the actual page in Chromium with invented profiles and intercepted API calls.
// Run: node tests/frontend/capture-redesign.mjs
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startBrowser } from './browser-harness.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const alerts = [{
  alert_id: 1, child_id: 'child_02', child_name: 'Test Child B', severity: 'Warning',
  subject: 'Reading review requested', message: 'Synthetic monitoring notice for layout testing.',
  email_status: 'not_configured', created_at: Math.floor(Date.now() / 1000), pdf_available: false,
}];
const captures = [];
const browser = await startBrowser();
try {
  for (const viewport of [
    { label: 'desktop', width: 1440, height: 1000 },
    { label: 'mobile', width: 390, height: 844, mobile: true },
  ]) {
    for (const state of ['auth', 'signup', 'parent', 'doctor', 'monitoring', 'alerts', 'settings', 'report', 'print-report']) {
      const page = await browser.page({
        signedOut: state === 'auth' || state === 'signup',
        role: ['doctor', 'alerts', 'settings'].includes(state) ? 'doctor' : 'parent',
        viewport, alerts,
      });
      try {
        if (state === 'signup') await page.click('#show-signup');
        if (state === 'doctor') {
          await page.evaluate("window.__fixture.profiles[1].risk_status = 'Warning'");
          await page.click('#refresh-button');
        }
        if (['monitoring', 'alerts', 'settings'].includes(state)) {
          await page.click(`#workspace-nav [data-section="${state}"]`);
        }
        if (state === 'report' || state === 'print-report') {
          await page.evaluate("window.__fixture.reports.child_01.recommendation_source = 'Local AI (Ollama)'");
          await page.click('#generate-report');
          await page.evaluate("document.querySelector('#sensor-report').scrollIntoView({block:'start',behavior:'instant'})");
        }
        if (state === 'print-report') {
          await page.media('print');
          await page.evaluate("scrollTo({top:0,behavior:'instant'})");
        }
        await page.settle(1000);
        const filename = `${state}-${viewport.label}.png`;
        const path = await page.screenshot(filename, { fullPage: state === 'print-report' });
        const dimensions = await page.evaluate('({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight })');
        const errors = await page.evaluate('window.__fixture.errors');
        captures.push({ state, viewport: viewport.label, path, dimensions, errors });
        console.log(`${filename}: ${dimensions.width}x${dimensions.height}; page width ${dimensions.scrollWidth}; errors ${errors.length}`);
      } finally {
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}
const outputDirectory = resolve(root, 'test-results/frontend/screenshots');
await mkdir(outputDirectory, { recursive: true });
await writeFile(resolve(outputDirectory, 'manifest.json'), JSON.stringify({ browser: browser.version, syntheticData: true, captures }, null, 2));
