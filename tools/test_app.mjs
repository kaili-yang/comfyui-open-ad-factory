// Browser test for the /open_ad_factory/ web app against a running ComfyUI with this node pack.
//   PLAYWRIGHT_DIR=../ComfyUI_frontend node tools/test_app.mjs [server] [screenshot_dir]
// Checks every UI language is complete, the submitted prompt carries the form values, progress and results render
// from ComfyUI websocket messages, and a real submission without models surfaces the server's validation error.
import { mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const { chromium } = createRequire(join(process.env.PLAYWRIGHT_DIR ?? process.cwd(), 'package.json'))('@playwright/test')
const [server = 'http://127.0.0.1:8188', shots = ''] = process.argv.slice(2)
const fail = (msg) => { console.error('FAIL:', msg); process.exitCode = 1 }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })
page.on('pageerror', (e) => fail(`page error: ${e.message}`))
await page.addInitScript(() => {
  const Native = window.WebSocket
  window.__oafSockets = []
  window.WebSocket = class extends Native {
    constructor(...args) { super(...args); window.__oafSockets.push(this) }
  }
})
await page.goto(`${server}/open_ad_factory/`)
await page.waitForSelector('#styles .chip')

// 1. Every language fills every label, and all six differ from English
const english = await page.evaluate(() => [...document.querySelectorAll('[data-i18n]')].map((e) => e.textContent))
for (const lang of ['en', 'es', 'ja', 'ko', 'zh', 'hi']) {
  await page.selectOption('#ui-lang', lang)
  const texts = await page.evaluate(() => [...document.querySelectorAll('[data-i18n]')].map((e) => [e.dataset.i18n, e.textContent]))
  const empty = texts.filter(([k, v]) => !v || v === k)
  if (empty.length) fail(`${lang}: untranslated ${empty.map(([k]) => k)}`)
  const htmlLang = await page.evaluate(() => document.documentElement.lang)
  const same = texts.filter(([, v], i) => v === english[i]).length
  console.log(`${lang}: ${texts.length} labels, html lang=${htmlLang}, identical to English: ${same}`)
  if (htmlLang !== lang) fail(`${lang}: html lang is ${htmlLang}`)
  if ((await page.inputValue('#ad-lang')) !== lang) fail(`${lang}: ad language did not follow the interface`)
  const visible = await page.evaluate(() => ['stop', 'download', 'results', 'progress', 'error'].filter((id) => document.getElementById(id).offsetParent !== null))
  if (visible.length) fail(`${lang}: should be hidden before a run: ${visible}`)
  if (lang !== 'en' && same > 3) fail(`${lang}: ${same} labels still English`)
  if (shots) { mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/app_${lang}.png`, fullPage: true }) }
}

// 2. Submitting patches the API prompt; answer with a fake prompt id, then drive the UI with ComfyUI-style ws messages
await page.selectOption('#ui-lang', 'zh')
await page.fill('#url', 'https://www.allbirds.com/products/mens-tree-runners')
await page.fill('#notes', 'Free returns within 30 days')
await page.fill('#project', 'ui_test')
await page.selectOption('#ad-lang', 'ja')
await page.click('#styles .chip[data-style="cinematic"]')
let submitted = null
await page.route('**/prompt', async (route) => {
  submitted = JSON.parse(route.request().postData())
  await route.fulfill({ json: { prompt_id: 'fake-1', number: 1, node_errors: {} } })
})
await page.click('#generate')
await page.waitForFunction(() => !document.getElementById('progress').hidden)
await page.waitForTimeout(300)
const nodes = Object.values(submitted?.prompt ?? {})
const get = (t) => nodes.find((n) => n.class_type === t)?.inputs ?? {}
const planner = get('OpenAdPlanner')
if (get('OpenAdProductPage').url !== 'https://www.allbirds.com/products/mens-tree-runners') fail('url not patched')
if (planner.language !== 'Japanese' || planner.style !== 'cinematic' || planner.project !== 'ui_test') fail(`planner not patched: ${JSON.stringify(planner)}`)
if (get('OpenAdViralityJudge').project !== 'ui_test') fail('judge project not patched')
if (get('SaveVideo').filename_prefix !== 'open_ad_factory/ui_test') fail('save prefix not patched')
console.log('submitted prompt nodes:', nodes.length, 'planner:', JSON.stringify({ language: planner.language, style: planner.style, project: planner.project }))

const ids = await page.evaluate(async () => (await (await fetch('static/prompt.json')).json()).stages)
const idOf = (pred) => Object.entries(ids).find(([, s]) => pred(s))[0]
const msgs = [
  ['executing', { node: idOf((s) => s.stage === 'plan') }],
  ['executed', { node: idOf((s) => s.output === 'storyboard'), output: { text: ['# Tree Runner storyboard'] } }],
  ['executing', { node: `${idOf((s) => s.stage === 'video' && s.shot === 2)}:292` }],
]
const fire = (list) => page.evaluate((list) => {
  // Reach the app's websocket handler through a synthetic MessageEvent on every open socket
  for (const ws of window.__oafSockets) for (const [type, data] of list) ws.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, data: { ...data, prompt_id: 'fake-1' } }) }))
}, list)
await fire(msgs)
const stageText = await page.textContent('#stage')
const active = await page.textContent('#stages li.active')
console.log('progress stage:', stageText, '| active:', active)
if (!stageText.includes('镜头 2')) fail(`stage text not localized: ${stageText}`)
if ((await page.textContent('#storyboard')) !== '# Tree Runner storyboard') fail('storyboard output not shown')
if (shots) await page.screenshot({ path: `${shots}/app_progress_zh.png`, fullPage: true })

// 3. Real submission without models: the server's validation error must be shown
await page.unroute('**/prompt')
await page.click('#stop').catch(() => {})
await page.evaluate(() => { document.getElementById('generate').disabled = false })
await page.click('#generate')
await page.waitForFunction(() => !document.getElementById('error').hidden, null, { timeout: 30000 })
const err = await page.textContent('#error-text')
console.log('server error shown:', err.split('\n')[0].slice(0, 100))
if (!/value not in list|Prompt outputs failed validation/i.test(err)) fail(`unexpected error text: ${err.slice(0, 200)}`)

await browser.close()
if (!process.exitCode) console.log('app test passed')
