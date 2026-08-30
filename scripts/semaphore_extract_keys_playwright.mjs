#!/usr/bin/env node
/**
 * Playwright + Semaphore API: log in, then per project SSH to inventory hosts
 * (via Semaphore's Key Store connection) and extract authorized_keys.
 *
 * Processes one project at a time. Uses the browser session cookie for API calls,
 * or captures a Bearer token from /api/user/tokens after login.
 *
 * Usage:
 *   SEMAPHORE_URL=https://devops.nextere.com \
 *   SEMAPHORE_USERNAME=you SEMAPHORE_PASSWORD=secret \
 *   node scripts/semaphore_extract_keys_playwright.mjs --all-projects
 *
 *   # Preview only (no tasks):
 *   node scripts/semaphore_extract_keys_playwright.mjs --all-projects --dry-run
 *
 *   # Register glowing-goggles repo + collect template per inventory, then run:
 *   node scripts/semaphore_extract_keys_playwright.mjs --all-projects --ensure-template
 *
 *   # Single project:
 *   node scripts/semaphore_extract_keys_playwright.mjs --project-id 10 --ensure-template
 *
 * Output: reports/authorized-keys/project-<id>.json (and summary.json)
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const DEFAULT_URL = process.env.SEMAPHORE_URL || 'https://devops.nextere.com';
const ENV_URL = (process.env.SEMAPHORE_URL || '').replace(/\/$/, '');
const USERNAME = process.env.SEMAPHORE_USERNAME || '';
const PASSWORD = process.env.SEMAPHORE_PASSWORD || '';
const TOKEN_ENV = (ENV_URL && ENV_URL === DEFAULT_URL.replace(/\/$/, ''))
  ? (process.env.SEMAPHORE_TOKEN || '') : '';

const AUDIT_REPO = process.env.AUDIT_REPO_URL
  || 'https://github.com/techcapanicus/glowing-goggles.git';
const AUDIT_BRANCH = process.env.AUDIT_REPO_BRANCH || 'cursor/dev-ssh-key-provision-1218';
const AUDIT_PLAYBOOK = 'ansible/audit_ssh_connections.yml';
const TEMPLATE_PREFIX = 'Playwright SSH Extract Keys';
const REPO_NAME = 'glowing-goggles-audit';

const HOST_LINE = /^\s{4,}(\S+):\s*$/;
const KV_LINE = /^\s{6,}(\w[\w_-]*):\s*(.+?)\s*$/;
const INI_HOST = /^\s*(\S+)\s+ansible_host=(\S+)/;
const INI_USER = /ansible_user=(\S+)/;

function parseArgs(argv) {
  const args = {
    url: DEFAULT_URL,
    token: '',
    username: USERNAME,
    password: PASSWORD,
    projectIds: [],
    allProjects: false,
    dryRun: false,
    ensureTemplate: false,
    headless: true,
    pollSec: 8,
    outDir: path.join(ROOT, 'reports', 'authorized-keys'),
    openTaskUi: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--url') { args.url = argv[++i]; args.token = ''; }
    else if (a === '--token') args.token = argv[++i];
    else if (a === '--username') { args.username = argv[++i]; args.token = ''; }
    else if (a === '--password') { args.password = argv[++i]; args.token = ''; }
    else if (a === '--project-id') args.projectIds.push(Number(argv[++i]));
    else if (a === '--all-projects') args.allProjects = true;
    else if (a === '--dry-run') args.dryRun = true;
    else if (a === '--ensure-template') args.ensureTemplate = true;
    else if (a === '--headed') args.headless = false;
    else if (a === '--open-task-ui') args.openTaskUi = true;
    else if (a === '--poll-sec') args.pollSec = Number(argv[++i]);
    else if (a === '--out-dir') args.outDir = argv[++i];
    else if (a === '--help') {
      console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(0, 24).join('\n'));
      process.exit(0);
    }
  }
  args.url = args.url.replace(/\/$/, '');
  if (!args.token && !args.username && !args.password && TOKEN_ENV) {
    args.token = TOKEN_ENV;
  }
  return args;
}

function parseInventoryYaml(yaml) {
  const hosts = [];
  let current = null;
  for (const line of (yaml || '').split('\n')) {
    const hm = line.match(INI_HOST);
    if (hm) {
      const userM = line.match(INI_USER);
      hosts.push({
        name: hm[1],
        ansible_host: hm[2],
        ansible_user: userM ? userM[1] : 'root',
      });
      continue;
    }
    const hostMatch = HOST_LINE.exec(line);
    if (hostMatch) {
      const name = hostMatch[1];
      if (['hosts', 'children', 'vars', 'all'].includes(name)) {
        current = null;
        continue;
      }
      current = { name, ansible_host: '', ansible_user: 'root' };
      hosts.push(current);
      continue;
    }
    if (!current) continue;
    const kv = KV_LINE.exec(line);
    if (!kv) continue;
    const [, key, val] = kv;
    const v = val.replace(/^['"]|['"]$/g, '');
    if (['ansible_host', 'public_ip_addr', 'public_ip', 'host'].includes(key) && v) {
      current.ansible_host = current.ansible_host || v;
    } else if (['ansible_user', 'ssh_user'].includes(key) && v) {
      current.ansible_user = v;
    }
  }
  const seen = new Set();
  return hosts.filter((h) => {
    const addr = h.ansible_host || h.name;
    if (!addr || seen.has(addr)) return false;
    seen.add(addr);
    if (!h.ansible_host) h.ansible_host = addr;
    return true;
  });
}

function stripAnsi(text) {
  return text.replace(/\u001b\[[0-9;]*m/g, '');
}

function parseAuthorizedKeys(taskOutput) {
  const clean = stripAnsi(taskOutput);
  const keys = [];
  let section = '';
  for (const line of clean.split('\n')) {
    const t = line.trim();
    if (t.includes('AUTHORIZED_KEYS')) section = 'auth';
    else if (t.startsWith('===')) section = '';
    else if (section === 'auth' && t.includes('SHA256:')) {
      const m = t.match(/SHA256:[^\s]+/);
      const comment = t.split(/\s+/).pop();
      if (m) keys.push({ fingerprint: m[0], comment, raw: t });
    } else if (section === 'auth' && t.startsWith('ssh-')) {
      keys.push({ fingerprint: '', comment: t.split(/\s+/).pop(), raw: t });
    }
  }
  return keys;
}

async function api(token, base, method, apiPath, body = null) {
  const headers = { Accept: 'application/json', Authorization: `Bearer ${token}` };
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${base}${apiPath}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!res.ok) {
    throw new Error(`${method} ${apiPath} -> HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  return data;
}

async function loginAndGetToken(page, context, args) {
  if (args.token) return args.token;

  if (!args.username || !args.password) {
    throw new Error('Set SEMAPHORE_TOKEN or SEMAPHORE_USERNAME + SEMAPHORE_PASSWORD');
  }

  await page.goto(`${args.url}/auth/login`, { waitUntil: 'networkidle' });
  await page.locator('input[type="text"]').fill(args.username);
  await page.locator('input[type="password"]').fill(args.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(/\/project\//, { timeout: 20000 });

  let captured = '';
  page.on('request', (req) => {
    const auth = req.headers().authorization;
    if (auth?.startsWith('Bearer ') && !captured) captured = auth.slice(7);
  });
  await page.goto(`${args.url}/api/projects`, { waitUntil: 'networkidle' }).catch(() => {});
  if (captured) return captured;

  const tokens = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/user/tokens`, { credentials: 'include' });
    return r.json();
  }, args.url);
  if (Array.isArray(tokens) && tokens[0]?.id) return tokens[0].id;

  throw new Error('Could not obtain API token after login');
}

async function ensureAuditRepo(token, base, projectId) {
  const repos = await api(token, base, 'GET', `/api/project/${projectId}/repositories`);
  let repo = repos.find((r) => r.name === REPO_NAME || r.git_url?.includes('glowing-goggles'));
  if (repo) return repo.id;

  await api(token, base, 'POST', `/api/project/${projectId}/repositories`, {
    name: REPO_NAME,
    project_id: projectId,
    git_url: AUDIT_REPO,
    git_branch: AUDIT_BRANCH,
    ssh_key_id: 1,
  });
  const refreshed = await api(token, base, 'GET', `/api/project/${projectId}/repositories`);
  repo = refreshed.find((r) => r.name === REPO_NAME);
  if (!repo) throw new Error(`Failed to create repository in project ${projectId}`);
  return repo.id;
}

async function ensureCollectTemplate(token, base, projectId, inventory, repoId) {
  const templates = await api(token, base, 'GET', `/api/project/${projectId}/templates`);
  const name = `${TEMPLATE_PREFIX} — ${inventory.name}`;
  let tpl = templates.find((t) => t.name === name)
    || templates.find((t) => (t.playbook || '').includes('audit_ssh_connections'));

  const envs = await api(token, base, 'GET', `/api/project/${projectId}/environment`);
  const envId = envs[0]?.id || 1;

  const payload = {
    project_id: projectId,
    name,
    playbook: AUDIT_PLAYBOOK,
    inventory_id: inventory.id,
    repository_id: repoId,
    environment_id: envId,
    app: 'ansible',
    type: '',
    arguments: '[]',
    description: 'Collect authorized_keys on inventory hosts via Semaphore SSH',
  };

  if (tpl) {
    await api(token, base, 'PUT', `/api/project/${projectId}/templates/${tpl.id}`, {
      ...payload,
      id: tpl.id,
    });
    return tpl.id;
  }

  const created = await api(token, base, 'POST', `/api/project/${projectId}/templates`, payload);
  return created.id;
}

async function runCollectTask(token, base, projectId, templateId, pollSec) {
  const task = await api(token, base, 'POST', `/api/project/${projectId}/tasks`, {
    template_id: templateId,
    environment: JSON.stringify({ audit_mode: 'collect' }),
  });
  const taskId = task.id;
  const terminal = new Set(['success', 'error', 'failed', 'stopped']);
  while (true) {
    await new Promise((r) => setTimeout(r, pollSec * 1000));
    const cur = await api(token, base, 'GET', `/api/project/${projectId}/tasks/${taskId}`);
    if (terminal.has(cur.status)) {
      const output = await api(token, base, 'GET', `/api/project/${projectId}/tasks/${taskId}/output`);
      const text = (output || []).map((e) => e.output || '').join('\n');
      return { taskId, status: cur.status, output: text };
    }
  }
}

async function processProject(page, token, args, project) {
  const pid = project.id;
  const pname = project.name;
  console.log(`\n${'='.repeat(70)}\nPROJECT [${pid}] ${pname}\n${'='.repeat(70)}`);

  const inventories = await api(token, args.url, 'GET', `/api/project/${pid}/inventory`);
  const keys = await api(token, args.url, 'GET', `/api/project/${pid}/keys`);
  const keyNames = Object.fromEntries(keys.map((k) => [k.id, k.name]));

  const report = {
    project_id: pid,
    project_name: pname,
    extracted_at: new Date().toISOString(),
    inventories: [],
  };

  let repoId = null;
  if (args.ensureTemplate) {
    if (args.dryRun) {
      console.log('  [dry-run] would ensure audit repository + templates');
    } else {
      repoId = await ensureAuditRepo(token, args.url, pid);
      console.log(`  audit repository id=${repoId}`);
    }
  }

  for (const inv of inventories) {
    const full = await api(token, args.url, 'GET', `/api/project/${pid}/inventory/${inv.id}`);
    const hosts = parseInventoryYaml(full.inventory || '');
    const sshKeyId = full.ssh_key_id;
    const sshKeyName = keyNames[sshKeyId] || `id=${sshKeyId}`;

    const entry = {
      inventory_id: inv.id,
      inventory_name: inv.name,
      ssh_key_id: sshKeyId,
      ssh_key_name: sshKeyName,
      hosts,
      status: 'skipped',
      authorized_keys: [],
      task_id: null,
      error: null,
    };

    console.log(`\n  Inventory [${inv.id}] ${inv.name} — ssh_key=${sshKeyName} hosts=${hosts.length}`);

    if (!hosts.length) {
      entry.status = 'no_hosts';
      entry.error = 'inventory has no parseable hosts';
      report.inventories.push(entry);
      continue;
    }
    if (!sshKeyId) {
      entry.status = 'no_ssh_key';
      entry.error = 'inventory has no ssh_key_id (no Semaphore SSH connection)';
      report.inventories.push(entry);
      continue;
    }

    hosts.forEach((h) => {
      console.log(`    ${h.ansible_user}@${h.ansible_host} (${h.name})`);
    });

    if (args.dryRun) {
      entry.status = 'dry_run';
      report.inventories.push(entry);
      continue;
    }

    try {
      let templateId;
      const templates = await api(token, args.url, 'GET', `/api/project/${pid}/templates`);
      const tplName = `${TEMPLATE_PREFIX} — ${inv.name}`;
      let tpl = templates.find((t) => t.name === tplName)
        || templates.find((t) => (t.playbook || '').includes('audit_ssh_connections')
          && t.inventory_id === inv.id);

      if (!tpl && args.ensureTemplate) {
        if (!repoId) repoId = await ensureAuditRepo(token, args.url, pid);
        templateId = await ensureCollectTemplate(token, args.url, pid, full, repoId);
        console.log(`  created/updated template id=${templateId}`);
      } else if (tpl) {
        templateId = tpl.id;
        console.log(`  using template id=${templateId} (${tpl.name})`);
      } else {
        entry.status = 'no_template';
        entry.error = 'no collect template; re-run with --ensure-template';
        report.inventories.push(entry);
        continue;
      }

      console.log(`  running SSH collect task...`);
      const result = await runCollectTask(token, args.url, pid, templateId, args.pollSec);
      entry.task_id = result.taskId;
      entry.task_status = result.status;
      entry.authorized_keys = parseAuthorizedKeys(result.output);
      entry.status = result.status === 'success' ? 'ok' : 'task_failed';
      console.log(`  task #${result.taskId} ${result.status} — ${entry.authorized_keys.length} authorized key(s)`);
      entry.authorized_keys.forEach((k) => {
        console.log(`    ${k.fingerprint} ${k.comment}`);
      });

      if (args.openTaskUi) {
        await page.goto(`${args.url}/project/${pid}/tasks/${result.taskId}`, {
          waitUntil: 'networkidle',
        });
      }
    } catch (err) {
      entry.status = 'error';
      entry.error = String(err.message || err);
      console.error(`  ERROR: ${entry.error}`);
    }

    report.inventories.push(entry);
  }

  return report;
}

async function main() {
  const args = parseArgs(process.argv);
  fs.mkdirSync(args.outDir, { recursive: true });

  const browser = await chromium.launch({ headless: args.headless });
  const context = await browser.newContext();
  const page = await context.newPage();

  let token;
  try {
    if (args.token) {
      token = args.token;
      await api(token, args.url, 'GET', '/api/user');
      console.log(`Using SEMAPHORE_TOKEN against ${args.url}`);
    } else {
      console.log(`Logging in to ${args.url} as ${args.username}...`);
      token = await loginAndGetToken(page, context, args);
      const me = await api(token, args.url, 'GET', '/api/user');
      console.log(`Logged in: ${me.username} (${me.name})`);
    }

    let projects = await api(token, args.url, 'GET', '/api/projects');
    if (args.projectIds.length) {
      const wanted = new Set(args.projectIds);
      projects = projects.filter((p) => wanted.has(p.id));
    } else if (!args.allProjects && projects.length > 1) {
      console.error('Pass --all-projects or --project-id <id> (multiple projects found)');
      process.exit(2);
    }

    const summary = [];
    for (const project of projects) {
      const report = await processProject(page, token, args, project);
      const outFile = path.join(args.outDir, `project-${project.id}.json`);
      fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
      console.log(`  saved ${outFile}`);
      summary.push({
        project_id: project.id,
        project_name: project.name,
        inventories: report.inventories.length,
        ok: report.inventories.filter((i) => i.status === 'ok').length,
        skipped: report.inventories.filter((i) => i.status !== 'ok').length,
        total_keys: report.inventories.reduce((n, i) => n + i.authorized_keys.length, 0),
      });
    }

    const summaryPath = path.join(args.outDir, 'summary.json');
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    console.log(`\nDone. Summary: ${summaryPath}`);
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
