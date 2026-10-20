#!/usr/bin/env node
/**
 * Unauthenticated frontend privacy smoke test.
 *
 * Uses Chrome DevTools Protocol instead of --dump-dom because the cookie-based
 * SPA performs a /api/auth/session check and client-side redirects.  Requires
 * Node.js 22+ (global WebSocket) and Google Chrome / Chromium.
 *
 * Usage:
 *   BASE_URL=http://127.0.0.1:5000 node scripts/check_frontend_privacy.mjs
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '')
const ROUTES = ['/login', '/', '/dashboard', '/modules', '/modules/1', '/logs', '/push-center', '/system-logs', '/settings', '/guide']
const FORBIDDEN = [
  'schedule-preview',
  'privacy-panel',
  'preview-row',
  'LIVE SCHEDULE',
  '演示签到',
  '摸鱼能量签到',
  'demo_checkin',
  'moyu_energy',
  '02 modules',
  '已排程',
  '待启用',
]
const TIME_WINDOW = /\b(?:[01]\d|2[0-3]):[0-5]\d\s*[–-]\s*(?:[01]\d|2[0-3]):[0-5]\d\b/
const ACCOUNT_COUNT = /\b\d{1,3}\s*个账号\b/
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function findChrome() {
  const explicit = process.env.CHROME_BIN
  if (explicit) {
    if (!existsSync(explicit)) throw new Error(`CHROME_BIN 不存在：${explicit}`)
    return explicit
  }
  for (const candidate of [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ]) {
    if (existsSync(candidate)) return candidate
  }
  throw new Error('未找到 Chrome/Chromium，请设置 CHROME_BIN 或安装 Google Chrome')
}

async function waitForTarget(port) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      const page = list.find((item) => item.type === 'page')
      if (page) return page
    } catch {
      // Chrome is still starting.
    }
    await sleep(250)
  }
  throw new Error('Chrome DevTools 端口未就绪')
}

function cdpClient(url) {
  const socket = new WebSocket(url)
  let nextId = 1
  const pending = new Map()
  const errors = []
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id) {
      const entry = pending.get(message.id)
      if (!entry) return
      pending.delete(message.id)
      message.error
        ? entry.reject(new Error(JSON.stringify(message.error)))
        : entry.resolve(message.result)
      return
    }
    if (message.method === 'Runtime.exceptionThrown') {
      errors.push(
        message.params.exceptionDetails?.exception?.description ||
          message.params.exceptionDetails?.text ||
          'Runtime exception',
      )
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      errors.push(message.params.args.map((arg) => arg.value || arg.description).join(' '))
    }
  })
  const opened = new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })
  const send = (method, params = {}) => {
    const id = nextId++
    const promise = new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
    socket.send(JSON.stringify({ id, method, params }))
    return promise
  }
  return { socket, opened, send, errors }
}

function checkDom(route, html, bodyText, errors) {
  const problems = []
  if (errors.length) problems.push(`浏览器异常：${errors.join(' | ')}`)
  for (const text of FORBIDDEN) {
    if (html.includes(text)) problems.push(`包含禁止内容「${text}」`)
  }
  const timeWindow = html.match(TIME_WINDOW)
  if (timeWindow) problems.push(`包含时间窗「${timeWindow[0]}」`)
  const accountCount = html.match(ACCOUNT_COUNT)
  if (accountCount) problems.push(`包含账号数量「${accountCount[0]}」`)
  if (!bodyText.includes('登录控制台')) {
    problems.push('未显示登录页（缺少“登录控制台”）')
  }
  if (problems.length) {
    throw new Error(`${route} 隐私检查失败：\n  - ${problems.join('\n  - ')}`)
  }
}

const chrome = findChrome()
const profile = mkdtempSync(join(tmpdir(), 'checkin-privacy-chrome-'))
const port = 9300 + Math.floor(Math.random() * 300)
const child = spawn(
  chrome,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--hide-scrollbars',
    '--disable-crash-reporter',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    'about:blank',
  ],
  { stdio: 'ignore' },
)
let client

try {
  const target = await waitForTarget(port)
  client = cdpClient(target.webSocketDebuggerUrl)
  await client.opened
  await client.send('Page.enable')
  await client.send('Runtime.enable')
  await client.send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  })
  console.log(`[privacy] Chrome: ${chrome}`)
  console.log(`[privacy] Base URL: ${BASE_URL}`)

  for (const route of ROUTES) {
    await client.send('Page.navigate', { url: `${BASE_URL}${route}` })
    await sleep(2800)
    const result = await client.send('Runtime.evaluate', {
      expression:
        '({html: document.documentElement.outerHTML, text: document.body.innerText})',
      returnByValue: true,
    })
    checkDom(route, result.result.value.html, result.result.value.text, client.errors)
    client.errors.length = 0
    console.log(`  [PASS] ${route} 未认证 DOM 无模块敏感信息 / schedule-preview / privacy-panel`)
  }
  console.log('[privacy] 所有未认证路由检查通过')
} catch (error) {
  console.error(`\n[FAIL] ${error.message}`)
  process.exitCode = 1
} finally {
  try {
    client?.socket.close()
  } catch {
    // ignore
  }
  child.kill('SIGTERM')
  await sleep(400)
  rmSync(profile, { recursive: true, force: true })
}
