import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const networkQuestion = 'How does the platform stop a model server from reaching the internet?';
const probeQuestion = 'What happens when a liveness probe fails?';

async function signIn(page: Page, scenario = 'default', waitForWorkspace = true) {
  await page.goto(`/?scenario=${scenario}`);
  await page.getByLabel('Username', { exact: true }).fill('platform');
  await page.getByLabel('Password', { exact: true }).fill('platform-demo');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  if (waitForWorkspace) await expect(page.getByLabel('Ask about your platform')).toBeEnabled();
}

async function ask(page: Page, question = networkQuestion) {
  await page.getByLabel('Ask about your platform').fill(question);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
}

function answer(page: Page) { return page.getByRole('article', { name: 'Assistant answer' }).last(); }

async function complete(page: Page) {
  await expect(answer(page).getByText('Complete', { exact: true })).toBeVisible();
}

test('sign-in rejects a wrong password, clears it, and accepts demo credentials', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill('platform');
  await page.getByLabel('Password', { exact: true }).fill('wrong');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Signing in...' })).toBeDisabled();
  await expect(page.locator('#login-error')).toContainText('username or password is incorrect');
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  await page.getByLabel('Password', { exact: true }).fill('platform-demo');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByLabel('Ask about your platform')).toBeEnabled();
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, cookie: document.cookie })))
    .toEqual({ local: 0, session: 0, cookie: '' });
});

test('streams an answer with sources, validates citations only on completion, and copies text', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await signIn(page);
  await ask(page);
  await expect(answer(page).getByText('Searching the documentation, then thinking...')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
  // Sources appear only once the answer is finished, and citations link only after they are checked.
  await expect(answer(page).locator('.sources')).toHaveCount(0);
  await expect(answer(page).locator('a.citation')).toHaveCount(0);
  await complete(page);
  await expect(answer(page).locator('a.citation')).toHaveText(['S1 (opens Platform architecture in a new tab)',
    'S3 (opens Network Policies in a new tab)', 'S1 (opens Platform architecture in a new tab)', 'S2 (opens Network Policies in a new tab)']);
  await expect(answer(page).getByText('From your documentation', { exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Answer complete.');
  await answer(page).getByRole('button', { name: 'Copy answer' }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('NetworkPolicy');
});

test('answers render Markdown, code copies, and sources group by document with section links', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await signIn(page);
  await ask(page);
  await complete(page);
  await expect(answer(page).locator('ol > li')).toHaveCount(3);
  await answer(page).getByRole('button', { name: 'Copy', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    'apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: default-deny-egress\nspec:\n  podSelector: {}\n  policyTypes:\n    - Egress');
  const sources = answer(page).locator('.sources');
  await expect(sources.locator('summary')).toContainText('Sources 2');
  await sources.locator('summary').click();
  const policies = sources.getByRole('link', { name: /^Network Policies/ });
  await expect(policies).toHaveAttribute('href', /network-policies\/#the-two-sorts-of-pod-isolation$/);
  await expect(policies).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(policies).toHaveAttribute('target', '_blank');
  await expect(sources.locator('li').nth(1)).toContainText('S2 S3');
});

test('stopping a stream retains text and preserves it when reopening history', async ({ page }) => {
  await signIn(page);
  await ask(page);
  await expect(answer(page).locator('.answer-text')).toContainText('The platform');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(answer(page).getByText('Stopped', { exact: true })).toBeVisible();
  const stoppedText = await answer(page).locator('.answer-text').innerText();
  await expect(answer(page).locator('a.citation')).toHaveCount(0);
  await page.getByRole('button', { name: 'New conversation', exact: true }).click();
  await page.getByRole('navigation', { name: 'Conversations' }).getByRole('button', { name: /How does the platform stop/ }).first().click();
  await expect(answer(page).getByText('Stopped', { exact: true })).toBeVisible();
  await expect(answer(page).locator('.answer-text')).toHaveText(stoppedText);
});

test('stopping before the first token keeps an explicit stopped state', async ({ page }) => {
  await signIn(page);
  await ask(page);
  await expect(answer(page).getByText('Searching the documentation, then thinking...')).toBeVisible();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(answer(page).getByText('Stopped before any answer text arrived.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
});

test('delete asks for confirmation, supports Escape, and removes the conversation', async ({ page }) => {
  await signIn(page);
  const remove = page.getByRole('button', { name: 'Delete Keeping inference traffic private', exact: true });
  await remove.click();
  const dialog = page.getByRole('dialog', { name: 'Delete conversation?' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(remove).toBeFocused();
  await expect(remove).toBeVisible();
  await remove.click();
  await dialog.getByRole('button', { name: 'Delete conversation', exact: true }).click();
  await expect(remove).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Deleted conversation');
});

test('signing out during generation clears the workspace', async ({ page }) => {
  await signIn(page);
  await ask(page);
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
  await expect(page.getByRole('main')).toContainText('You have signed out.');
  await expect(page.getByRole('article', { name: 'Assistant answer' })).toHaveCount(0);
});

test('loading scenario shows workspace loading and the long first-token wait', async ({ page }) => {
  await signIn(page, 'loading', false);
  await expect(page.getByText('Loading your workspace...', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Ask about your platform')).toBeEnabled();
  await ask(page);
  const start = Date.now();
  await expect(answer(page).getByText('Searching the documentation, then thinking...')).toBeVisible();
  await expect(answer(page).locator('.answer-text')).toBeVisible();
  expect(Date.now() - start).toBeGreaterThanOrEqual(7_000);
  await complete(page);
});

test('a question without matching documentation gets a labelled general answer and no sources', async ({ page }) => {
  await signIn(page, 'no-sources');
  await ask(page, 'ping');
  await complete(page);
  await expect(answer(page).getByText('General answer', { exact: true })).toBeVisible();
  await expect(answer(page).locator('.sources, .citation')).toHaveCount(0);
});

test('unauthorized chat sends the user back to sign-in', async ({ page }) => {
  await signIn(page, 'unauthorized');
  await ask(page);
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
  await expect(page.getByRole('main')).toContainText('Your session has expired.');
});

for (const scenario of ['busy', 'rate-limited'] as const) {
  test(`${scenario} honours Retry-After and never retries automatically`, async ({ page }) => {
    await signIn(page, scenario);
    await ask(page);
    await expect(page.locator('.rate-notice')).toContainText(scenario === 'busy' ? 'All answer slots are in use, try again in' : 'You have reached the request limit.');
    const retry = answer(page).getByRole('button', { name: 'Retry answer' });
    await expect(retry).toBeDisabled();
    await expect(page.locator('.rate-notice')).toContainText('You can try again now.');
    await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(1);
    await retry.click();
    const dialog = page.getByRole('dialog', { name: 'Send this question again?' });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(1);
    await dialog.getByRole('button', { name: 'Send again', exact: true }).click();
    await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(2);
    await complete(page);
  });
}

test('sign-in rate limiting counts down and requires another explicit submit', async ({ page }) => {
  await signIn(page, 'sign-in-rate-limited', false);
  await expect(page.locator('#login-error')).toContainText('Too many sign-in attempts');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeDisabled();
  await expect(page.getByRole('main')).toContainText(/Try again in \d seconds/);
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  await page.getByLabel('Password', { exact: true }).fill('platform-demo');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByLabel('Ask about your platform')).toBeEnabled();
});

for (const [scenario, message] of [
  ['model-unavailable', 'The model is unavailable.'],
  ['retrieval-unavailable', 'Documentation retrieval is unavailable.'],
  ['upstream-failed', 'The model request failed before an answer could be returned.'],
  ['question-empty', 'Enter a question before sending.'],
  ['question-too-long', 'Your question is too long.'],
] as const) {
  test(`${scenario} is visible and offers an explicit retry`, async ({ page }) => {
    await signIn(page, scenario);
    await ask(page);
    await expect(answer(page).locator('.error-text')).toContainText(message);
    await expect(answer(page).getByRole('button', { name: 'Retry answer' })).toBeEnabled();
    await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(1);
  });
}

test('length limit preserves the answer and explains how to continue', async ({ page }) => {
  await signIn(page, 'length');
  await ask(page);
  await expect(answer(page).getByText('Length limit reached', { exact: true })).toBeVisible();
  await expect(answer(page)).toContainText('Ask a narrower follow-up question');
  await expect(answer(page).getByRole('button', { name: 'Copy answer' })).toBeEnabled();
});

for (const [scenario, message] of [
  ['partial-failure', 'The answer stream failed.'],
  ['deadline', 'The answer exceeded its time limit.'],
  ['stalled', 'The answer stream stalled.'],
  ['stream-model-unavailable', 'The model became unavailable.'],
] as const) {
  test(`${scenario} keeps partial text and asks before retrying`, async ({ page }) => {
    await signIn(page, scenario);
    await ask(page);
    await expect(answer(page).getByText('Incomplete', { exact: true })).toBeVisible();
    await expect(answer(page).locator('.answer-text')).not.toBeEmpty();
    await expect(answer(page).locator('.error-text')).toContainText(message);
    await expect(answer(page).locator('a.citation')).toHaveCount(0);
    await answer(page).getByRole('button', { name: 'Retry answer' }).click();
    const dialog = page.getByRole('dialog', { name: 'Send this question again?' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(1);
    await expect(answer(page).getByRole('button', { name: 'Retry answer' })).toBeFocused();
  });
}

test('stream failure before any text gives a distinct explanation', async ({ page }) => {
  await signIn(page, 'stream-failure');
  await ask(page);
  await expect(answer(page).locator('.error-text')).toContainText('No answer text was received.');
  await expect(answer(page).locator('.answer-text')).toHaveCount(0);
  await expect(answer(page).getByText('Incomplete', { exact: true })).toBeVisible();
});

test('untrusted model text stays literal and invalid citations are noninteractive', async ({ page }) => {
  const dialogs: string[] = [];
  page.on('dialog', (dialog) => { dialogs.push(dialog.message()); void dialog.dismiss(); });
  await signIn(page, 'invalid-citations');
  await ask(page);
  await complete(page);
  await expect(answer(page)).toContainText('<script>alert("demo")</script>');
  await expect(answer(page).getByText('[S9: unverified citation]', { exact: true })).toBeVisible();
  await expect(answer(page).locator('a.citation')).not.toContainText(['S9']);
  expect(dialogs).toEqual([]);
});

test('unsafe source URLs are not turned into links', async ({ page }) => {
  await signIn(page, 'unsafe-source');
  await ask(page);
  await complete(page);
  await answer(page).locator('.sources summary').click();
  await expect(answer(page).locator('.sources li')).toHaveCount(2);
  await expect(answer(page).getByRole('link')).toHaveCount(0);
});

test('history links citations that name a saved source', async ({ page }) => {
  await signIn(page);
  await page.getByRole('button', { name: /Liveness and readiness probes/ }).first().click();
  await expect(page.getByRole('heading', { name: 'Liveness and readiness probes' })).toBeVisible();
  await expect(answer(page).locator('a.citation').first()).toHaveAttribute('href', /pod-lifecycle\/#container-probes$/);
  await expect(answer(page).locator('.sources summary')).toContainText('Pod Lifecycle');
});

test('composer supports newlines, blocks over-limit input, and sends on Enter', async ({ page }) => {
  await signIn(page);
  const input = page.getByLabel('Ask about your platform');
  await input.fill('a'.repeat(2001));
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
  await input.press('Enter');
  await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(0);
  await input.fill('What happens');
  await input.press('Shift+Enter');
  await expect(input).toHaveValue('What happens\n');
  await input.fill(probeQuestion);
  await input.press('Enter');
  await expect(page.getByRole('article', { name: 'Your question' })).toHaveCount(1);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});

test('suggested questions send immediately', async ({ page }) => {
  await signIn(page);
  await page.getByRole('button', { name: new RegExp(probeQuestion.replace('?', '\\?')) }).click();
  await expect(page.getByRole('article', { name: 'Your question' })).toContainText(probeQuestion);
  await complete(page);
  await expect(answer(page)).toContainText('kubelet restarts');
});

test('retrieval mismatch is labelled and refuses a grounded answer', async ({ page }) => {
  await signIn(page, 'retrieval-mismatch');
  await expect(page.getByText('Retrieval: Index mismatch', { exact: true })).toBeVisible();
  await ask(page);
  await expect(answer(page).locator('.error-text')).toContainText('Documentation retrieval is unavailable.');
});

test('disabled retrieval is labelled and returns an answer without sources', async ({ page }) => {
  await signIn(page, 'retrieval-disabled');
  await expect(page.getByText('Retrieval: Disabled', { exact: true })).toBeVisible();
  await ask(page);
  await complete(page);
  await expect(answer(page).getByText('General answer', { exact: true })).toBeVisible();
});

test('missing conversation leaves the workspace usable', async ({ page }) => {
  await signIn(page, 'conversation-not-found');
  await page.getByRole('button', { name: /Liveness and readiness probes/ }).first().click();
  await expect(page.locator('.error-notice')).toContainText('This conversation is no longer available.');
  await expect(page.getByLabel('Ask about your platform')).toBeEnabled();
});

for (const endpoint of ['status', 'list', 'history', 'delete', 'signout'] as const) {
  test(`a 401 from ${endpoint} also returns to sign-in`, async ({ page }) => {
    await signIn(page, `unauthorized-${endpoint}`, endpoint !== 'status' && endpoint !== 'list');
    if (endpoint === 'history') {
      await page.getByRole('button', { name: /Keeping inference traffic private/ }).first().click();
    } else if (endpoint === 'delete') {
      await page.getByRole('button', { name: 'Delete Keeping inference traffic private', exact: true }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete conversation', exact: true }).click();
    } else if (endpoint === 'signout') {
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    }
    await expect(page.getByRole('main')).toContainText('Your session has expired.');
    await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
  });
}

for (const colorScheme of ['light', 'dark'] as const) {
  test(`360px ${colorScheme} layout supports keyboard drawer use without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
    await signIn(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const trigger = page.getByRole('button', { name: 'Conversations', exact: true });
    await trigger.focus();
    await page.keyboard.press('Enter');
    const drawer = page.getByRole('dialog', { name: 'Conversations', exact: true });
    await expect(drawer).toBeVisible();
    await page.keyboard.press('Shift+Tab');
    expect(await drawer.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await ask(page, probeQuestion);
    await complete(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await answer(page).locator('.sources summary').click();
    await expect(answer(page).locator('.sources').getByRole('link', { name: /^Pod Lifecycle/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('production preview makes only same-origin asset requests and obeys its CSP', async ({ page }) => {
  const unexpected: string[] = [];
  const violations: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin !== 'http://127.0.0.1:4173' || url.pathname.startsWith('/api/')) unexpected.push(request.url());
  });
  page.on('console', (message) => { if (/Content Security Policy|Refused to/i.test(message.text())) violations.push(message.text()); });
  page.on('pageerror', (error) => violations.push(error.message));
  await signIn(page);
  await ask(page);
  await complete(page);
  expect(unexpected).toEqual([]);
  expect(violations).toEqual([]);
});
