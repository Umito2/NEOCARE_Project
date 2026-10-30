import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { if (browser) await browser.close(); });

async function withPage(t, options = {}) {
  const page = await browser.page({ reducedMotion: true, ...options });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, []);
  });
  return page;
}

async function assertPasswordsReset(page) {
  const fields = await page.evaluate(`['login', 'signup'].map(prefix => ({
    value: document.getElementById(prefix + '-password').value,
    type: document.getElementById(prefix + '-password').type,
    pressed: document.getElementById('toggle-' + prefix + '-password').getAttribute('aria-pressed'),
    label: document.getElementById('toggle-' + prefix + '-password').getAttribute('aria-label'),
  }))`);
  for (const field of fields) {
    assert.equal(field.value, '');
    assert.equal(field.type, 'password');
    assert.equal(field.pressed, 'false');
    assert.match(field.label, /show.*password/i);
  }
}

test('successful login clears and conceals both password fields', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.evaluate("document.querySelector('#login-identifier').value='parent@example.test'; document.querySelector('#login-password').value='synthetic-login-123'; document.querySelector('#signup-password').value='synthetic-hidden-123'");
  await page.click('#toggle-login-password');
  await page.evaluate("document.querySelector('#login-form').requestSubmit()");
  await page.waitFor("!document.querySelector('#workspace').hidden");
  await assertPasswordsReset(page);
});

test('successful signup clears and conceals both password fields', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.click('#show-signup');
  await page.evaluate(`(() => {
    const values = {'signup-parent-name':'Test Parent','signup-email':'parent@example.test','signup-phone':'0000000000','signup-password':'synthetic-signup-123','signup-child-name':'Test Child A','signup-age':'4','signup-height':'102','signup-weight':'16.5','login-password':'synthetic-hidden-123'};
    for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
  })()`);
  await page.click('#toggle-signup-password');
  await page.evaluate("document.querySelector('#signup-form').requestSubmit()");
  await page.waitFor("!document.querySelector('#workspace').hidden");
  await assertPasswordsReset(page);
});

test('signing out removes any retained passwords and resets reveal controls', async (t) => {
  const page = await withPage(t);
  await page.evaluate("document.querySelector('#login-password').value='synthetic-retained-123'; document.querySelector('#signup-password').value='synthetic-retained-456'; document.querySelector('#toggle-login-password').click(); document.querySelector('#toggle-signup-password').click()");
  await page.click('#logout-button');
  assert.equal(await page.visible('#login-form'), true);
  await assertPasswordsReset(page);
});

test('keyboard-focused row action survives a changed-profile background refresh', async (t) => {
  const page = await withPage(t, { role: 'doctor', viewport: { width: 1440, height: 1000 } });
  await page.focus('[data-child-id="child_02"][data-profile-action="edit"]');
  await page.evaluate("window.__oldFocused = document.activeElement; window.__fixture.profiles[1].latest_reading.heart_rate_bpm=122; window.__fixture.profiles[1].latest_reading.timestamp=new Date(Date.now()+1000).toISOString(); window.__fixture.intervals.forEach(timer=>timer.callback())");
  await page.waitFor("document.querySelector('#profile-list').textContent.includes('122')");
  const focus = await page.evaluate("({id:document.activeElement.dataset.childId,action:document.activeElement.dataset.profileAction,replaced:document.activeElement!==window.__oldFocused})");
  assert.deepEqual(focus, { id: 'child_02', action: 'edit', replaced: true });
  await page.press('Enter');
  assert.equal(await page.visible('#parent-profile-card'), true);
  assert.equal(await page.evaluate("document.querySelector('#name').value"), 'Test Child B');
});

test('mobile table horizontal scroll survives changed-profile background refresh', async (t) => {
  const page = await withPage(t, { role: 'doctor', viewport: { width: 390, height: 844, mobile: true } });
  const previous = await page.evaluate("(() => { const table = document.querySelector('#profile-list .table-wrap'); table.scrollLeft=150; return {left:table.scrollLeft,overflow:table.scrollWidth>table.clientWidth}; })()");
  assert.equal(previous.overflow, true, 'The clinic table must have an internal horizontal scroll area on mobile');
  assert.ok(previous.left > 0);
  await page.evaluate("window.__fixture.profiles[0].latest_reading.heart_rate_bpm=123; window.__fixture.profiles[0].latest_reading.timestamp=new Date(Date.now()+1000).toISOString(); window.__fixture.intervals.forEach(timer=>timer.callback())");
  await page.waitFor("document.querySelector('#profile-list').textContent.includes('123')");
  assert.equal(await page.evaluate("document.querySelector('#profile-list .table-wrap').scrollLeft"), previous.left);
});

test('recent readings show a formatted time without a stale warning', async (t) => {
  const page = await withPage(t);
  const timestamp = new Date(Date.now() - 60000).toISOString();
  await page.evaluate(`window.__fixture.readings.child_01.timestamp=${JSON.stringify(timestamp)}`);
  await page.click('#refresh-sensors');
  const status = await page.evaluate("({text:document.querySelector('#sensor-status').textContent,stale:document.querySelector('#sensor-status').classList.contains('is-stale')})");
  assert.match(status.text, /Last received/);
  assert.equal(status.stale, false);
  assert.ok(!status.text.includes(timestamp), 'Raw ISO timestamps should be formatted for readers');
});

test('readings older than five minutes are visibly marked as not recent', async (t) => {
  const page = await withPage(t);
  await page.evaluate("window.__fixture.readings.child_01.timestamp=new Date(Date.now()-600000).toISOString()");
  await page.click('#refresh-sensors');
  assert.equal(await page.evaluate("document.querySelector('#sensor-status').classList.contains('is-stale')"), true);
  assert.match(await page.evaluate("document.querySelector('#sensor-status').textContent"), /Reading not recent.*More than 5 minutes ago/);
});

test('missing and invalid timestamps explain uncertainty and clear obsolete stale styling', async (t) => {
  const page = await withPage(t);
  await page.evaluate("window.__fixture.readings.child_01.timestamp='2000-01-01T00:00:00Z'");
  await page.click('#refresh-sensors');
  for (const timestamp of [null, '', 'not-a-timestamp']) {
    await page.evaluate(`window.__fixture.readings.child_01.timestamp=${JSON.stringify(timestamp)}`);
    await page.click('#refresh-sensors');
    assert.match(await page.evaluate("document.querySelector('#sensor-status').textContent"), /Measurement time unavailable/);
    assert.equal(await page.evaluate("document.querySelector('#sensor-status').classList.contains('is-stale')"), false);
  }
});

test('skip link points to the visible sign-in form before authentication', async (t) => {
  const page = await withPage(t, { signedOut: true });
  await page.focus('.skip-link');
  assert.equal(await page.evaluate("document.querySelector('.skip-link').getAttribute('href')"), '#login-form');
  await page.press('Enter');
  const target = await page.evaluate("document.querySelector('#login-form').getBoundingClientRect().top");
  assert.ok(target >= 0 && target < 1000);
  assert.equal(await page.visible('#login-form'), true);
});

test('print media retains the report while hiding navigation and interactive controls', async (t) => {
  const page = await withPage(t, { role: 'doctor', viewport: { width: 1440, height: 1000 } });
  await page.click('#generate-report');
  await page.media('print');
  assert.equal(await page.visible('#sensor-report'), true);
  assert.match(await page.evaluate("document.querySelector('#sensor-report').textContent"), /Test Child A/);
  for (const selector of ['.topbar', '#workspace-nav', '#generate-report', '.workspace-footer', '#sensor-report .print-report']) {
    assert.equal(await page.visible(selector), false, `${selector} should not appear on printed reports`);
  }
});
