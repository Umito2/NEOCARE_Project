import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBrowser } from './browser-harness.mjs';

let browser;
before(async () => { browser = await startBrowser(); });
after(async () => { await browser?.close(); });

async function pageFor(t, options = {}) {
  const page = await browser.page({ reducedMotion: true, localStorage: {}, colorScheme: 'light', ...options });
  t.after(async () => {
    const errors = await page.evaluate('window.__fixture.errors');
    await page.close();
    assert.deepEqual(errors, []);
  });
  await page.waitFor(options.signedOut
    ? `document.querySelector('#auth-card').checkVisibility()`
    : `document.querySelector('#workspace').checkVisibility() && document.querySelectorAll('#profile-list tbody tr').length === 2`);
  return page;
}

async function setColor(page, value, selector = '#accent-color') {
  await page.evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    input.value = ${JSON.stringify(value)};
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

test('saved custom color is normalized and applied before body rendering', async (t) => {
  const page = await pageFor(t, {
    signedOut: true, observeThemeInitialization: true,
    localStorage: {'neocare-accent': '#A52CE3', 'neocare-theme': 'dark'},
  });
  assert.equal(await page.evaluate('window.__fixture.accentAtBodyStart'), '#a52ce3');
  assert.equal(await page.evaluate('document.documentElement.dataset.theme'), 'dark');
  await page.click('#appearance-toggle');
  assert.equal(await page.evaluate(`document.querySelector('#accent-color').value`), '#a52ce3');
});

test('picker applies any color, stores it, and a fresh page restores it', async (t) => {
  const page = await pageFor(t, {signedOut: true});
  const original = await page.evaluate('getComputedStyle(document.body).backgroundColor');
  await page.click('#appearance-toggle');
  await setColor(page, '#de4c85');
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#de4c85');
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-accent')`), '#de4c85');
  assert.notEqual(await page.evaluate('getComputedStyle(document.body).backgroundColor'), original);
  const next = await pageFor(t, {localStorage: {'neocare-accent': '#de4c85'}});
  assert.equal(await next.evaluate('document.documentElement.dataset.accent'), '#de4c85');
});

test('HEX entry accepts short colors and rejects invalid input without replacing the saved color', async (t) => {
  const page = await pageFor(t);
  await page.click('#appearance-toggle');
  await setColor(page, '#F0A', '#accent-hex');
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#ff00aa');
  await setColor(page, '#not-a-color', '#accent-hex');
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#ff00aa');
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-accent')`), '#ff00aa');
  assert.equal(await page.evaluate(`document.querySelector('#accent-hex').getAttribute('aria-invalid')`), 'true');
});

test('presets and reset update the palette without changing the selected light/dark mode', async (t) => {
  const page = await pageFor(t, {localStorage: {'neocare-theme': 'dark'}});
  await page.click('#appearance-toggle');
  const preset = await page.evaluate(`document.querySelector('[data-accent-color]').dataset.accentColor`);
  await page.click('[data-accent-color]');
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), preset.toLowerCase());
  await page.click('#accent-reset');
  assert.equal(await page.evaluate(`document.documentElement.hasAttribute('data-accent')`), false);
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-accent')`), null);
  assert.equal(await page.evaluate('document.documentElement.dataset.theme'), 'dark');
});

test('typing a full HEX value does not expand partial shorthand or move the caret', async (t) => {
  const page = await pageFor(t, {signedOut: true});
  await page.click('#appearance-toggle');
  await page.focus('#accent-hex');
  const result = await page.evaluate(`(() => {
    const input = document.querySelector('#accent-hex');
    input.value = '';
    const snapshots = [];
    for (const char of '#1a2b3c') {
      input.value += char;
      input.setSelectionRange(input.value.length, input.value.length);
      input.dispatchEvent(new Event('input', {bubbles: true}));
      snapshots.push(input.value);
    }
    input.dispatchEvent(new Event('change', {bubbles: true}));
    return {snapshots, accent: document.documentElement.dataset.accent};
  })()`);
  assert.deepEqual(result.snapshots, ['#', '#1', '#1a', '#1a2', '#1a2b', '#1a2b3', '#1a2b3c']);
  assert.equal(result.accent, '#1a2b3c');
});

test('palette changes and clearing preferences synchronize across tabs', async (t) => {
  const page = await pageFor(t, {localStorage: {'neocare-accent': '#7733cc'}});
  await page.evaluate(`window.dispatchEvent(new StorageEvent('storage', {key: 'neocare-accent', newValue: '#3355dd'}))`);
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#3355dd');
  await page.evaluate(`window.dispatchEvent(new StorageEvent('storage', {key: 'neocare-theme', newValue: 'dark'}))`);
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#3355dd');
  await page.evaluate(`window.dispatchEvent(new StorageEvent('storage', {key: null, newValue: null}))`);
  assert.equal(await page.evaluate(`document.documentElement.hasAttribute('data-accent')`), false);
});

for (const storageFailure of ['read', 'write', 'all']) {
  test(`custom colors and reset remain usable with blocked storage ${storageFailure}`, async (t) => {
    const page = await pageFor(t, {signedOut: true, storageFailure});
    await page.click('#appearance-toggle');
    await setColor(page, '#3366dd');
    assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#3366dd');
    await page.click('#accent-reset');
    assert.equal(await page.evaluate(`document.documentElement.hasAttribute('data-accent')`), false);
  });
}

test('invalid stored colors are ignored without injecting CSS', async (t) => {
  for (const value of ['red', 'url(https://untrusted.example/)', '#fff; color:red', '#12345', 'javascript:alert(1)']) {
    const page = await pageFor(t, {signedOut: true, localStorage: {'neocare-accent': value}});
    assert.equal(await page.evaluate(`document.documentElement.hasAttribute('data-accent')`), false);
  }
});

test('appearance panel supports keyboard, Escape focus return and outside dismissal', async (t) => {
  const page = await pageFor(t, {signedOut: true});
  await page.focus('#appearance-toggle');
  await page.press('Enter');
  assert.equal(await page.visible('#appearance-panel'), true);
  assert.equal(await page.evaluate(`document.querySelector('#appearance-toggle').getAttribute('aria-expanded')`), 'true');
  await page.focus('#accent-hex');
  await page.press('Escape');
  assert.equal(await page.visible('#appearance-panel'), false);
  assert.equal(await page.evaluate(`document.activeElement.id`), 'appearance-toggle');
  await page.click('#appearance-toggle');
  await page.focus('#login-identifier');
  await page.click('#login-identifier');
  assert.equal(await page.visible('#appearance-panel'), false);
  assert.equal(await page.evaluate(`document.activeElement.id`), 'login-identifier', 'Outside dismissal must not steal input focus');
});

test('color choice survives sign-in, sign-out and light/dark changes', async (t) => {
  const page = await pageFor(t, {signedOut: true, localStorage: {'neocare-accent': '#cc3355'}});
  await page.click('#theme-toggle');
  await page.evaluate(`document.querySelector('#login-identifier').value='parent@example.test'; document.querySelector('#login-password').value='synthetic-password-123'; document.querySelector('#login-form').requestSubmit();`);
  await page.waitFor(`document.querySelector('#workspace').checkVisibility()`);
  await page.click('#logout-button');
  await page.waitFor(`document.querySelector('#auth-card').checkVisibility()`);
  assert.equal(await page.evaluate('document.documentElement.dataset.accent'), '#cc3355');
  assert.equal(await page.evaluate('document.documentElement.dataset.theme'), 'dark');
});

function contrast(foreground, background) {
  const luminance = color => {
    const rgb = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(channel => {
      const normalized = channel / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  };
  const [high, low] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

for (const mode of ['light', 'dark']) {
  test(`extreme and saturated custom colors retain readable ${mode} text and semantic alerts`, async (t) => {
    const page = await pageFor(t, {signedOut: true, localStorage: {'neocare-theme': mode}});
    const semantic = () => page.evaluate(`(() => {
      const container = document.createElement('div');
      container.innerHTML = '<span class="risk-status normal">Normal</span><span class="risk-status warning">Warning</span><span class="risk-status critical">Critical</span>';
      document.body.append(container);
      const colors = [...container.children].map(el => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor]);
      container.remove(); return colors;
    })()`);
    const before = await semantic();
    await page.click('#appearance-toggle');
    for (const color of ['#ffffff', '#000000', '#ffff00', '#00ff00', '#0000ff', '#ff0000', '#ff00ff', '#777777']) {
      await setColor(page, color);
      const samples = await page.evaluate(`(() => {
        return ['body', '#login-form .primary', '#auth-description', '#appearance-panel', '#accent-hex'].map(selector => {
          const node = document.querySelector(selector);
          const foreground = getComputedStyle(node).color;
          let parent = node, background;
          while (parent) {
            background = getComputedStyle(parent).backgroundColor;
            if (background !== 'rgba(0, 0, 0, 0)' && background !== 'transparent') break;
            parent = parent.parentElement;
          }
          return {selector, foreground, background};
        });
      })()`);
      for (const sample of samples) {
        assert.ok(contrast(sample.foreground, sample.background) >= 4.5,
          `${mode} ${color} ${sample.selector} must remain readable: ${JSON.stringify(sample)}`);
      }
      assert.deepEqual(await semantic(), before, 'Custom colors must preserve clinical status colors');
    }
  });
}

for (const width of [320, 360, 390]) {
  for (const signedOut of [true, false]) {
    test(`color controls fit ${width}px ${signedOut ? 'sign-in' : 'clinic'} in English and Arabic`, async (t) => {
      const page = await pageFor(t, {signedOut, role: 'doctor',
        viewport: {width, height: 844, mobile: true},
        localStorage: {'neocare-accent': '#6633bb', 'neocare-theme': 'dark'}});
      for (const lang of ['en', 'ar']) {
        await page.click(`[data-language="${lang}"]`);
        await page.click('#appearance-toggle');
        const layout = await page.evaluate(`(() => {
          const rect = document.querySelector('#appearance-panel').getBoundingClientRect();
          return {width: innerWidth, scrollWidth: document.documentElement.scrollWidth, left: rect.left, right: rect.right,
            label: document.querySelector('#appearance-toggle').getAttribute('aria-label'),
            direction: getComputedStyle(document.querySelector('#accent-hex')).direction};
        })()`);
        assert.ok(layout.scrollWidth <= layout.width + 1, JSON.stringify(layout));
        assert.ok(layout.left >= 0 && layout.right <= layout.width + 1, JSON.stringify(layout));
        assert.equal(layout.direction, 'ltr');
        if (lang === 'ar') assert.match(layout.label, /[\u0600-\u06ff]/);
        await page.focus('#accent-hex');
        await page.press('Escape');
      }
    });
  }
}

test('printing ignores custom screen colors and preserves the stored preference', async (t) => {
  const page = await pageFor(t, {localStorage: {'neocare-accent': '#ff00ff', 'neocare-theme': 'dark'}});
  await page.click('#generate-report');
  await page.waitFor(`document.querySelector('#sensor-report').checkVisibility()`);
  await page.click('#appearance-toggle');
  await page.media('print');
  assert.equal(await page.visible('#appearance-panel'), false);
  assert.equal(await page.visible('#appearance-toggle'), false);
  const colors = await page.evaluate(`({body: getComputedStyle(document.body).backgroundColor,
    report: getComputedStyle(document.querySelector('#sensor-report')).backgroundColor,
    text: getComputedStyle(document.querySelector('#sensor-report')).color})`);
  assert.equal(colors.body, 'rgb(255, 255, 255)');
  assert.equal(colors.report, 'rgb(255, 255, 255)');
  assert.ok(contrast(colors.text, colors.report) >= 4.5);
  assert.equal(await page.evaluate(`localStorage.getItem('neocare-accent')`), '#ff00ff');
});
