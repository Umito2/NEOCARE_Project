// Synthetic fixtures only; no API, patient database, or external network access.
// Run: node tests/frontend/capture-theme.mjs
import { writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startBrowser } from './browser-harness.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const captures = [];
const browser = await startBrowser();
try {
  for (const viewport of [
    { label: 'desktop', width: 1440, height: 1000 },
    { label: 'mobile', width: 390, height: 844, mobile: true },
  ]) {
    for (const language of ['en', 'ar']) {
      for (const state of ['auth', 'parent', 'doctor', 'report', 'print-report']) {
        const page = await browser.page({
          signedOut: state === 'auth', role: state === 'doctor' ? 'doctor' : 'parent',
          viewport, reducedMotion: true, colorScheme: 'light',
          localStorage: { 'neocare-theme': 'dark', 'neocare-language': language },
          alerts: [{ alert_id: 1, child_id: 'child_02', child_name: 'Test Child B', severity: 'Warning', subject: 'Synthetic review request', message: 'Synthetic monitoring notice for theme review.', email_status: 'not_configured', created_at: Date.now() / 1000, pdf_available: false, workflow_status: 'new', notes: [] }],
        });
        try {
          await page.waitFor(state === 'auth'
            ? `document.querySelector('#auth-card').checkVisibility()`
            : `document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length === 2`);
          await page.waitFor(`document.documentElement.dataset.theme === 'dark' && document.documentElement.lang === '${language}'`);
          if (state === 'doctor') {
            await page.evaluate(`window.__fixture.profiles[1].risk_status='Warning'`);
            await page.click('#refresh-button');
          }
          if (state === 'report' || state === 'print-report') {
            await page.evaluate(`window.__fixture.reports.child_01.recommendation_source='Local AI (Ollama)'`);
            await page.click('#generate-report');
            await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
            await page.evaluate(`document.querySelector('#sensor-report').scrollIntoView({ block: 'start', behavior: 'instant' })`);
          }
          if (state === 'print-report') {
            await page.media('print');
            await page.evaluate(`scrollTo({ top: 0, behavior: 'instant' })`);
          }
          await page.settle(100);
          const filename = `theme-${state}-${language}-${viewport.label}.png`;
          const path = await page.screenshot(filename, { fullPage: state === 'print-report' });
          const dimensions = await page.evaluate(`({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight })`);
          const errors = await page.evaluate('window.__fixture.errors');
          captures.push({ state, language, theme: 'dark', media: state === 'print-report' ? 'print' : 'screen', viewport: viewport.label, path, dimensions, errors });
          if (errors.length) throw new Error(`Page errors in ${filename}: ${JSON.stringify(errors)}`);
          console.log(`${filename}: ${dimensions.width}x${dimensions.height}; page width ${dimensions.scrollWidth}; errors ${errors.length}`);
        } finally {
          await page.close();
        }
      }
    }
  }
} finally {
  await browser.close();
}
await writeFile(resolve(root, 'test-results/frontend/screenshots/theme-manifest.json'), JSON.stringify({ browser: browser.version, syntheticData: true, captures }, null, 2));
