import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { if (browser) await browser.close(); });

async function pageFor(t, options = {}) {
  const page = await browser.page({ reducedMotion: true, localStorage: {}, colorScheme: 'light', ...options });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, [], 'Theme changes must not cause uncaught page errors');
  });
  await page.waitFor(options.signedOut
    ? `document.querySelector('#auth-card').checkVisibility()`
    : `document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length === 2`);
  return page;
}

async function assertTheme(page, expected, { english = true } = {}) {
  await page.waitFor(`document.documentElement.dataset.theme === ${JSON.stringify(expected)}`);
  const button = await page.evaluate(`(() => {
    const button = document.querySelector('#theme-toggle');
    return { pressed: button.getAttribute('aria-pressed'), label: button.getAttribute('aria-label'), visible: button.checkVisibility() };
  })()`);
  assert.equal(button.pressed, expected === 'dark' ? 'true' : 'false');
  assert.equal(button.visible, true);
  if (english) assert.equal(button.label, `Switch to ${expected === 'dark' ? 'light' : 'dark'} mode`);
}

for (const scheme of ['light', 'dark']) {
  test(`no saved choice uses the ${scheme} system preference before body content renders`, async (t) => {
    const page = await pageFor(t, { signedOut: true, colorScheme: scheme, observeThemeInitialization: true });
    await assertTheme(page, scheme);
    assert.equal(await page.evaluate('window.__fixture.themeAtBodyStart'), scheme);
    assert.equal(await page.evaluate(`localStorage.getItem('neocare-theme')`), null, 'A system default must not become an explicit saved choice');
  });
}

for (const saved of ['light', 'dark']) {
  test(`saved ${saved} overrides the opposite system preference on the first render`, async (t) => {
    const page = await pageFor(t, {
      colorScheme: saved === 'light' ? 'dark' : 'light',
      localStorage: { 'neocare-theme': saved }, observeThemeInitialization: true,
    });
    await assertTheme(page, saved);
    assert.equal(await page.evaluate('window.__fixture.themeAtBodyStart'), saved);
  });
}

test('invalid saved theme falls back to the system preference and still follows changes', async (t) => {
  const page = await pageFor(t, { colorScheme: 'dark', localStorage: { 'neocare-theme': 'unsupported-value' } });
  await assertTheme(page, 'dark');
  await page.colorScheme('light');
  await assertTheme(page, 'light');
});

test('system changes update the theme until the user explicitly selects a mode', async (t) => {
  const page = await pageFor(t);
  await page.colorScheme('dark');
  await assertTheme(page, 'dark');
  await page.click('#theme-toggle');
  await assertTheme(page, 'light');
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-theme')`), 'light');
  await page.colorScheme('light');
  await page.colorScheme('dark');
  await assertTheme(page, 'light');
  assert.equal(await page.evaluate(`matchMedia('(prefers-reduced-motion: reduce)').matches`), true, 'Changing color scheme must preserve the reduced-motion test setting');
});

test('a fresh page restores the choice written by the previous page', async (t) => {
  const first = await pageFor(t, { signedOut: true, colorScheme: 'dark' });
  await first.click('#theme-toggle');
  const saved = await first.evaluate(`localStorage.getItem('neocare-theme')`);
  assert.equal(saved, 'light');
  const second = await pageFor(t, { colorScheme: 'dark', localStorage: { 'neocare-theme': saved } });
  await assertTheme(second, 'light');
});

test('keyboard Enter and Space toggle the theme while retaining visible focus', async (t) => {
  const page = await pageFor(t, { signedOut: true });
  await page.focus('#theme-toggle');
  await page.press('Enter');
  await assertTheme(page, 'dark');
  const focused = await page.evaluate(`(() => {
    const button = document.querySelector('#theme-toggle');
    const style = getComputedStyle(button);
    return { active: document.activeElement === button, focusVisible: button.matches(':focus-visible'), outline: style.outlineStyle, width: parseFloat(style.outlineWidth) };
  })()`);
  assert.equal(focused.active, true);
  assert.equal(focused.focusVisible, true);
  assert.notEqual(focused.outline, 'none');
  assert.ok(focused.width > 0);
  await page.press('Space');
  await assertTheme(page, 'light');
});

test('the theme stays selected across sign-in and sign-out and remains usable', async (t) => {
  const page = await pageFor(t, { signedOut: true });
  await page.click('#theme-toggle');
  await page.evaluate(`document.querySelector('#login-identifier').value='parent@example.test'; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility()`);
  await assertTheme(page, 'dark');
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
  await assertTheme(page, 'dark');
  await page.click('#theme-toggle');
  await assertTheme(page, 'light');
});

test('Arabic translates both theme actions and switching back restores English labels', async (t) => {
  const page = await pageFor(t, { signedOut: true });
  await page.click('[data-language="ar"]');
  await page.waitFor(`document.documentElement.dir === 'rtl'`);
  const darkAction = await page.evaluate(`document.querySelector('#theme-toggle').getAttribute('aria-label')`);
  assert.match(darkAction, /[\u0600-\u06ff]/);
  assert.doesNotMatch(darkAction, /Switch to/);
  await page.click('#theme-toggle');
  await assertTheme(page, 'dark', { english: false });
  const lightAction = await page.evaluate(`document.querySelector('#theme-toggle').getAttribute('aria-label')`);
  assert.match(lightAction, /[\u0600-\u06ff]/);
  assert.notEqual(lightAction, darkAction);
  await page.click('[data-language="en"]');
  await assertTheme(page, 'dark');
});

for (const storageFailure of ['read', 'write', 'all']) {
  test(`blocked storage ${storageFailure} does not prevent the system default or a manual toggle`, async (t) => {
    const page = await pageFor(t, { signedOut: true, colorScheme: 'dark', storageFailure });
    await assertTheme(page, 'dark');
    await page.click('#theme-toggle');
    await assertTheme(page, 'light');
    await page.colorScheme('light');
    await page.colorScheme('dark');
    await assertTheme(page, 'light');
  });
}

for (const width of [320, 390]) {
  for (const signedOut of [true, false]) {
    test(`dark ${signedOut ? 'sign-in' : 'workspace'} controls fit ${width}px in English and Arabic`, async (t) => {
      const page = await pageFor(t, {
        signedOut, role: 'doctor', localStorage: { 'neocare-theme': 'dark' },
        viewport: { width, height: 844, mobile: true },
      });
      for (const language of ['en', 'ar']) {
        await page.click(`[data-language="${language}"]`);
        await page.waitFor(`document.documentElement.lang === ${JSON.stringify(language)}`);
        const layout = await page.evaluate(`(() => {
          const rect = document.querySelector('#theme-toggle').getBoundingClientRect();
          return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, left: rect.left, right: rect.right, height: rect.height };
        })()`);
        assert.ok(layout.scrollWidth <= layout.width + 1, `${language} page must not overflow horizontally: ${JSON.stringify(layout)}`);
        assert.ok(layout.left >= 0 && layout.right <= layout.width, `${language} theme button must fit the viewport`);
        assert.ok(layout.height >= 24);
        await assertTheme(page, 'dark', { english: language === 'en' });
      }
    });
  }
}

test('printing a dark-mode report uses white paper and dark text without changing the saved theme', async (t) => {
  const page = await pageFor(t, { localStorage: { 'neocare-theme': 'dark' } });
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.media('print');
  const print = await page.evaluate(`(() => {
    const report = document.querySelector('#sensor-report');
    return { bodyBackground: getComputedStyle(document.body).backgroundColor, reportBackground: getComputedStyle(report).backgroundColor, text: getComputedStyle(report).color, visible: report.checkVisibility(), scheme: getComputedStyle(document.documentElement).colorScheme };
  })()`);
  assert.equal(print.visible, true);
  assert.equal(print.bodyBackground, 'rgb(255, 255, 255)');
  assert.equal(print.reportBackground, 'rgb(255, 255, 255)');
  const channels = print.text.match(/[\d.]+/g).slice(0, 3).map(Number);
  assert.ok(channels.every(channel => channel < 130), `Printed report text must remain dark: ${print.text}`);
  assert.equal(print.scheme, 'light');
  assert.equal(await page.visible('#theme-toggle'), false);
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-theme')`), 'dark');
  await page.media('screen');
  await assertTheme(page, 'dark');
});
