/* Visual QA helper. Requires Playwright and an already-built frontend. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.RELEASEPROOF_PYTHON || path.join(root, 'backend', '.venv', 'bin', 'python');
const output = path.join(root, 'tmp', 'ui');
fs.mkdirSync(output, { recursive: true });

function launch(command, args, cwd, env = {}) {
  return spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
}

async function ready(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function main() {
  const backend = launch(
    python,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'warning'],
    path.join(root, 'backend'),
    { RELEASEPROOF_USE_VERTEX: 'false' },
  );
  const frontend = launch(
    'npm',
    ['run', 'preview', '--', '--host', '127.0.0.1', '--port', '4173'],
    path.join(root, 'frontend'),
  );
  let browser;
  try {
    await Promise.all([
      ready('http://127.0.0.1:8000/health'),
      ready('http://127.0.0.1:4173'),
    ]);
    const executablePath = process.env.RELEASEPROOF_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    browser = await chromium.launch({ headless: true, executablePath });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, deviceScaleFactor: 1 });
    await page.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(output, 'releaseproof-home.png'), fullPage: true });
    await page.getByRole('button', { name: /Run release proof/i }).click();
    await page.getByText('Release decision').waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(output, 'releaseproof-result.png'), fullPage: true });
    await page.getByRole('radio', { name: /Response schema changed/i }).click();
    await page.getByRole('button', { name: /Run release proof/i }).click();
    await page.waitForTimeout(2800);
    await page.getByText(/Required field 'total' is missing/i).waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(output, 'releaseproof-contract-result.png'), fullPage: true });
    console.log(output);
  } finally {
    if (browser) await browser.close();
    backend.kill('SIGTERM');
    frontend.kill('SIGTERM');
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
