import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => {
  browser = await startBrowser();
  console.log(`Redesign browser: ${browser.version}; all data and API responses are synthetic.`);
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

async function assertNoHorizontalOverflow(page) {
  const geometry = await page.evaluate(`(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    overflowing: Array.from(document.body.querySelectorAll('*')).filter(element => {
      const rect = element.getBoundingClientRect();
      return element.checkVisibility() && rect.width > 0 && rect.right > innerWidth + 1;
    }).slice(0, 8).map(element => element.id || element.className || element.tagName),
  }))()`);
  assert.ok(geometry.scrollWidth <= geometry.width + 1, `Page overflows horizontally: ${JSON.stringify(geometry)}`);
}

for (const viewport of [
  { label: 'desktop', width: 1440, height: 1000 },
  { label: 'mobile', width: 390, height: 844, mobile: true },
]) {
  for (const state of ['auth', 'signup', 'parent', 'doctor']) {
    test(`${state} layout fits the ${viewport.label} viewport without horizontal page overflow`, async (t) => {
      const page = await withPage(t, {
        signedOut: state === 'auth' || state === 'signup',
        role: state === 'doctor' ? 'doctor' : 'parent',
        viewport, reducedMotion: true,
      });
      if (state === 'signup') await page.click('#show-signup');
      assert.equal(await page.evaluate('innerWidth'), viewport.width, 'The responsive viewport must not expand beyond the device width');
      await assertNoHorizontalOverflow(page);
      assert.equal(await page.visible(state === 'auth' ? '#login-form' : state === 'signup' ? '#signup-form' : '#workspace'), true);
    });
  }
}

test('parent dashboard also fits a narrow 320px mobile viewport', async (t) => {
  const page = await withPage(t, { viewport: { width: 320, height: 740, mobile: true }, reducedMotion: true });
  assert.equal(await page.evaluate('innerWidth'), 320);
  await assertNoHorizontalOverflow(page);
});

test('accessible role buttons update login mode and selection state', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.click('[data-login-role="doctor"]');
  assert.equal(await page.evaluate('document.querySelector("#login-role").value'), 'doctor');
  assert.equal(await page.evaluate('document.querySelector("[data-login-role=doctor]").getAttribute("aria-pressed")'), 'true');
  assert.equal(await page.evaluate('document.querySelector("[data-login-role=parent]").getAttribute("aria-pressed")'), 'false');
  assert.equal(await page.visible('#signup-switch'), false);
  await page.click('[data-login-role="parent"]');
  assert.equal(await page.evaluate('document.querySelector("#login-role").value'), 'parent');
  assert.equal(await page.evaluate('document.querySelector("[data-login-role=parent]").getAttribute("aria-pressed")'), 'true');
  assert.equal(await page.visible('#signup-switch'), true);
});

test('login password reveal works by keyboard without submitting or changing its value', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.evaluate("document.querySelector('#login-password').value = 'synthetic-password-123'");
  await page.focus('#login-password');
  await page.press('Tab');
  assert.equal(await page.evaluate('document.activeElement.id'), 'toggle-login-password');
  const accessible = await page.evaluate(`(() => {
    const button = document.querySelector('#toggle-login-password');
    const style = getComputedStyle(button);
    return { name: button.getAttribute('aria-label') || button.textContent, type: button.type,
      focusVisible: button.matches(':focus-visible'), outline: style.outlineStyle, shadow: style.boxShadow };
  })()`);
  assert.match(accessible.name, /show.*password/i);
  assert.equal(accessible.type, 'button');
  assert.equal(accessible.focusVisible, true);
  assert.ok(accessible.outline !== 'none' || accessible.shadow !== 'none', 'Keyboard focus must have a visible indicator');
  await page.press('Enter');
  assert.equal(await page.evaluate('document.querySelector("#login-password").type'), 'text');
  assert.equal(await page.evaluate('document.querySelector("#toggle-login-password").getAttribute("aria-pressed")'), 'true');
  await page.press('Enter');
  assert.equal(await page.evaluate('document.querySelector("#login-password").type'), 'password');
  assert.equal(await page.evaluate('document.querySelector("#login-password").value'), 'synthetic-password-123');
  assert.equal(await page.evaluate('window.__fixture.calls.some(call => call.path === "/api/v1/auth/login")'), false);
});

test('signup password reveal has an accessible independent state', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.click('#show-signup');
  await page.evaluate("document.querySelector('#signup-password').value = 'synthetic-signup-123'");
  await page.click('#toggle-signup-password');
  assert.equal(await page.evaluate('document.querySelector("#signup-password").type'), 'text');
  assert.equal(await page.evaluate('document.querySelector("#toggle-signup-password").getAttribute("aria-pressed")'), 'true');
  assert.match(await page.evaluate('document.querySelector("#toggle-signup-password").getAttribute("aria-label")'), /hide.*password/i);
  assert.equal(await page.evaluate('document.querySelector("#login-password").type'), 'password');
  assert.equal(await page.evaluate('window.__fixture.calls.some(call => call.path === "/api/v1/auth/signup")'), false);
});

test('workspace navigation is hidden before sign-in and clinic settings stay hidden from parents', async (t) => {
  const page = await withPage(t, { signedOut: true });
  assert.equal(await page.visible('#workspace-nav'), false);
  await page.evaluate("document.querySelector('#login-identifier').value = 'parent@example.test'; document.querySelector('#login-password').value = 'synthetic-password-123'; document.querySelector('#login-form').requestSubmit()");
  await page.settle();
  assert.equal(await page.visible('#workspace-nav'), true);
  assert.equal(await page.visible('#workspace-nav [data-section="settings"]'), false);
});

test('keyboard navigation marks and focuses the requested clinic section', async (t) => {
  const page = await withPage(t, { role: 'doctor', viewport: { width: 1440, height: 1000 }, reducedMotion: true });
  for (const [section, target] of Object.entries({ overview: 'overview-section', monitoring: 'monitoring-section', alerts: 'alerts-card', settings: 'threshold-card' })) {
    await page.focus(`#workspace-nav [data-section="${section}"]`);
    await page.press('Enter');
    assert.equal(await page.evaluate(`document.querySelector('#workspace-nav [data-section="${section}"]').getAttribute('aria-current')`), 'location');
    assert.equal(await page.evaluate('document.activeElement.id'), target);
    assert.equal(await page.evaluate('document.querySelectorAll("#workspace-nav [aria-current=location]").length'), 1);
    const top = await page.evaluate(`document.querySelector('#${target}').getBoundingClientRect().top`);
    assert.ok(top >= -1 && top < 1000, `${section} must be scrolled into view, top=${top}`);
  }
});

test('summary metrics represent the loaded children, attention flags, and available readings', async (t) => {
  const page = await withPage(t, { role: 'doctor' });
  await page.evaluate("window.__fixture.profiles[1].risk_status = 'Warning'; window.__fixture.profiles[1].latest_reading = null");
  await page.click('#refresh-button');
  const values = await page.evaluate("['summary-children','summary-attention','summary-readings'].map(id => document.getElementById(id).textContent.trim())");
  assert.deepEqual(values, ['2', '1', '1']);
});

test('reduced-motion preference removes ongoing decorative animation and smooth scrolling', async (t) => {
  const page = await withPage(t, { signedOut: true, reducedMotion: true });
  await page.settle(100);
  const result = await page.evaluate(`({
    preference: matchMedia('(prefers-reduced-motion: reduce)').matches,
    scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    runningAnimations: document.getAnimations().filter(animation => animation.playState === 'running' && animation.effect.getTiming().duration > 1).length,
  })`);
  assert.equal(result.preference, true);
  assert.equal(result.runningAnimations, 0);
  assert.notEqual(result.scrollBehavior, 'smooth');
});

test('mobile parent edit exposes an editable form without expanding the page width', async (t) => {
  const page = await withPage(t, { viewport: { width: 390, height: 844, mobile: true }, reducedMotion: true });
  await page.click('#profile-list .edit-button');
  assert.equal(await page.visible('#parent-profile-card'), true);
  assert.equal(await page.evaluate('document.querySelector("#name").value'), 'Test Child A');
  await assertNoHorizontalOverflow(page);
  await page.evaluate("document.querySelector('#name').value = 'Updated Synthetic Child'; document.querySelector('#profile-form').requestSubmit()");
  await page.settle();
  const call = await page.evaluate('window.__fixture.calls.find(call => call.method === "PUT")');
  assert.equal(call.body.name, 'Updated Synthetic Child');
});

test('mobile report preserves child identity and stays inside the viewport', async (t) => {
  const page = await withPage(t, { viewport: { width: 390, height: 844, mobile: true }, reducedMotion: true });
  await page.evaluate("window.__fixture.reports.child_01.recommendation_source = 'Local AI (Ollama)'");
  await page.click('#generate-report');
  assert.equal(await page.visible('#sensor-report'), true);
  assert.match(await page.evaluate('document.querySelector("#sensor-report").textContent'), /Test Child A/);
  await assertNoHorizontalOverflow(page);
  await page.change('#sensor-child', 'child_02');
  assert.equal(await page.visible('#sensor-report'), false);
});

test('mobile alerts remain readable and clinic deletion stays in the alert workflow', async (t) => {
  const page = await withPage(t, {
    role: 'doctor', viewport: { width: 390, height: 844, mobile: true }, reducedMotion: true,
    alerts: [{ alert_id: 1, child_id: 'child_01', child_name: 'Test Child A', severity: 'Warning', subject: 'Synthetic review request', message: 'A synthetic alert for layout testing.', email_status: 'not_configured', created_at: Math.floor(Date.now() / 1000), pdf_available: false }],
  });
  await page.click('#workspace-nav [data-section="alerts"]');
  assert.equal(await page.visible('#alerts-card'), true);
  assert.match(await page.evaluate('document.querySelector("#alerts-card").textContent'), /Synthetic review request/);
  await assertNoHorizontalOverflow(page);
  await page.evaluate("Array.from(document.querySelectorAll('#alert-list button')).find(button => /delete/i.test(button.textContent)).click()");
  await page.settle();
  assert.equal(await page.evaluate('window.__fixture.alerts.length'), 0);
});
