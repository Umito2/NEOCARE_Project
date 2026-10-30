// Screenshots contain synthetic data only; the harness blocks application network access.
import { startBrowser } from './browser-harness.mjs';
const browser = await startBrowser();
try {
  for (const language of ['en', 'ar']) {
    for (const mobile of [false, true]) {
      const page = await browser.page({
        role: 'doctor', viewport: mobile ? { width: 390, height: 844, mobile: true } : { width: 1440, height: 1000 },
        alerts: [{ alert_id: 1, child_id: 'child_01', child_name: 'Test Child A', severity: 'Warning', subject: 'Synthetic review request', message: 'Synthetic readings for interface review.', workflow_status: 'acknowledged', notes: [{ text: 'Synthetic clinician review note.', author: 'Test Clinician', created_at: Date.now() / 1000 }], email_status: 'not_configured', created_at: Date.now() / 1000, pdf_available: false }],
      });
      try {
        await page.waitFor(`document.querySelector('#workspace').checkVisibility() && document.querySelector('.alert-workflow-form') !== null`);
        await page.evaluate(`window.__fixture.histories.child_01=Array.from({length:8},(_,index)=>({timestamp:new Date(Date.now()-(7-index)*3600000).toISOString(),heart_rate_bpm:[105,108,102,110,107,106,104,109][index],spo2_percent:98,temperature_c:36.6,respiratory_rate_br_min:24}));`);
        await page.click('#refresh-history');
        await page.waitFor(`document.querySelectorAll('#history-chart .chart-point').length===8`);
        await page.click(`[data-language="${language}"]`);
        for (const panel of ['history', 'alerts', 'settings']) {
          await page.evaluate(`document.querySelector(${JSON.stringify(panel === 'history' ? '#reading-history' : panel === 'alerts' ? '#alerts-card' : '#doctor-management')}).scrollIntoView({block:'start',behavior:'instant'});`);
          if (panel === 'alerts') await page.evaluate(`document.querySelector('.alert-review').open=true;`);
          if (panel === 'settings') await page.evaluate(`document.querySelector('#doctor-management').open=true;`);
          await page.settle(300);
          console.log(await page.screenshot(`features-${language}-${mobile ? 'mobile' : 'desktop'}-${panel}.png`));
        }
      } finally { await page.close(); }
    }
  }
} finally { await browser.close(); }
