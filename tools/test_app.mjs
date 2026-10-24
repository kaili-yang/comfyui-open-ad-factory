// Browser test for the /open_ad_factory/ web app against a running ComfyUI with this node pack.
//   PLAYWRIGHT_DIR=../ComfyUI_frontend node tools/test_app.mjs [server] [screenshot_dir]
// Covers: complete translations in 6 languages, product preview, model readiness gate, prompt patching,
// live progress from ComfyUI websocket messages (steps, shot thumbnails), results tabs, projects library,
// and a real submission surfacing the server's validation error.
import { mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const { chromium } = createRequire(join(process.env.PLAYWRIGHT_DIR ?? process.cwd(), 'package.json'))('@playwright/test')
const [server = 'http://127.0.0.1:8188', shots = ''] = process.argv.slice(2)
const fail = (msg) => { console.error('FAIL:', msg); process.exitCode = 1 }
const shot = async (page, name) => { if (shots) { mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true }) } }

const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z/C/HgAGgwJ/lK3Q6wAAAABJRU5ErkJggg==', 'base64')
const REVIEW = {
  score: 78.5, verdict: 'Strong hook and clear product; the end card needs a sharper offer.',
  scores: { hook: 8.5, product_clarity: 8, message: 7.5, pacing: 7, audio: 6.5, cta: 5, visual_quality: 9 },
  strengths: ['Opens on motion in the first second', 'Product stays recognizable in every shot'],
  fixes: ['Shot 4: name the free-returns offer', 'Shot 2: cut the pause before the line'],
}
const BOARD = {
  product_name: "Men's Tree Runner", headline: 'Walk on clouds', cta: 'Shop now', post_caption: 'Light, breathable, made from trees.',
  hashtags: ['#allbirds', '#sneakers'], brief: 'Product: Tree Runner\nURL: https://www.allbirds.com/products/mens-tree-runners',
  shots: ['hook', 'problem', 'solution', 'cta'].map((role, i) => ({ role, caption: `CAPTION ${i + 1}`, voiceover: `Line ${i + 1}` })),
}
const SUMMARY = { name: 'ui_test', history: [{ score: 61 }, { score: 70 }, { score: 78.5 }], review: REVIEW, storyboard: BOARD, video: null, updated: Date.now() / 1000 - 3600 }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.on('pageerror', (e) => fail(`page error: ${e.message}`))
await page.addInitScript(() => {
  localStorage.clear()
  const Native = window.WebSocket
  window.__oafSockets = []
  window.WebSocket = class extends Native { constructor(...a) { super(...a); window.__oafSockets.push(this) } }
})
await page.goto(`${server}/open_ad_factory/`)
await page.waitForSelector('#styles .style')

// 1. Translations: every language has every key, and the page has no untranslated label
const keys = await page.evaluate(async () => {
  const { STRINGS } = await import('./static/i18n.js')
  const en = Object.keys(STRINGS.en)
  return Object.fromEntries(Object.entries(STRINGS).map(([l, s]) => [l, en.filter((k) => !(k in s)).concat(Object.keys(s).filter((k) => !en.includes(k)))]))
})
for (const [lang, diff] of Object.entries(keys)) if (diff.length) fail(`${lang}: key mismatch ${diff}`)
const english = await page.evaluate(() => [...document.querySelectorAll('[data-i18n]')].map((e) => e.textContent))
for (const lang of ['en', 'es', 'ja', 'ko', 'zh', 'hi']) {
  await page.selectOption('#ui-lang', lang)
  const texts = await page.evaluate(() => [...document.querySelectorAll('[data-i18n]')].map((e) => [e.dataset.i18n, e.textContent]))
  const empty = texts.filter(([k, v]) => !v || v === k)
  if (empty.length) fail(`${lang}: untranslated ${empty.map(([k]) => k)}`)
  const same = texts.filter(([, v], i) => v === english[i]).length
  if (lang !== 'en' && same > 2) fail(`${lang}: ${same} labels still English`)
  if ((await page.inputValue('#ad-lang')) !== lang) fail(`${lang}: ad language did not follow the interface`)
  if ((await page.evaluate(() => document.documentElement.lang)) !== lang) fail(`${lang}: html lang`)
  console.log(`${lang}: ${texts.length} labels ok`)
}
const hiddenBefore = await page.evaluate(() => ['stop', 'download', 'error', 'phone-live'].filter((id) => document.getElementById(id).offsetParent !== null))
if (hiddenBefore.length) fail(`visible before a run: ${hiddenBefore}`)
await shot(page, 'create_hi')

// 2. Status panels: models are missing on this machine, device is shown
await page.selectOption('#ui-lang', 'en')
await page.waitForFunction(() => document.getElementById('models-badge').textContent.includes('/'))
console.log('models:', await page.textContent('#models-status'), '| device:', await page.textContent('#device'), '|', await page.textContent('#conn-text'))
if (!(await page.textContent('#conn-text')).includes('Connected')) fail('not connected to ComfyUI')

// 3. Product preview reads the real page through the plugin API
await page.fill('#url', 'https://www.allbirds.com/products/mens-tree-runners')
await page.click('#fetch')
await page.waitForFunction(() => ['ok', 'error'].includes(document.getElementById('product').dataset.state), null, { timeout: 30000 })
const productState = await page.getAttribute('#product', 'data-state')
console.log('product preview:', productState, await page.textContent('#product-name'))
if (productState !== 'ok') fail('product preview failed')

// 4. Missing models block the run with a clear message
await page.click('#generate')
await page.waitForFunction(() => !document.getElementById('error').hidden)
if (!(await page.textContent('#error-text')).includes('models')) fail('missing models did not block the run')

// 5. With models available, the submitted prompt carries the form; drive progress with websocket messages
const template = await page.evaluate(async () => (await fetch('static/prompt.json')).json())
const byFolder = {}
for (const m of template.models) (byFolder[m.folder] ??= []).push(m.file)
await page.route('**/models/*', (route) => route.fulfill({ json: byFolder[route.request().url().split('/').pop()] ?? [] }))
await page.reload()
await page.waitForFunction(() => document.getElementById('models-badge').classList.contains('ok'))
await page.selectOption('#ui-lang', 'zh')
await page.fill('#url', 'https://www.allbirds.com/products/mens-tree-runners')
await page.click('#advanced summary')
await page.fill('#project', 'ui_test')
await page.selectOption('#ad-lang', 'ja')
await page.click('.style[data-style="cinematic"]')
let submitted = null
await page.route('**/prompt', async (route) => { submitted = JSON.parse(route.request().postData()); await route.fulfill({ json: { prompt_id: 'fake-1', number: 1, node_errors: {} } }) })
await page.route('**/open_ad_factory/api/project/ui_test', (route) => route.fulfill({ json: SUMMARY }))
await page.route('**/view?*', (route) => route.fulfill({ body: PIXEL, contentType: 'image/png' }))
await page.keyboard.press('Meta+Enter')
await page.waitForFunction(() => !document.getElementById('phone-live').hidden)
await page.waitForTimeout(200)
const get = (t) => Object.values(submitted?.prompt ?? {}).find((n) => n.class_type === t)?.inputs ?? {}
const planner = get('OpenAdPlanner')
if (get('OpenAdProductPage').url !== 'https://www.allbirds.com/products/mens-tree-runners') fail('url not patched')
if (planner.language !== 'Japanese' || planner.style !== 'cinematic' || planner.project !== 'ui_test') fail(`planner not patched: ${JSON.stringify(planner)}`)
if (get('SaveVideo').filename_prefix !== 'open_ad_factory/ui_test' || get('OpenAdViralityJudge').project !== 'ui_test') fail('save/judge not patched')
if (get('OpenAdViralityJudge').language !== 'Simplified Chinese') fail(`judge should report in the interface language: ${get('OpenAdViralityJudge').language}`)

const idOf = (pred) => Object.entries(template.stages).find(([, s]) => pred(s))[0]
const fire = (list) => page.evaluate((list) => {
  for (const ws of window.__oafSockets) for (const [type, data] of list) ws.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, data: { prompt_id: 'fake-1', ...data } }) }))
}, list)
await fire([
  ['status', { status: { exec_info: { queue_remaining: 2 } }, prompt_id: undefined }],
  ['executing', { node: idOf((s) => s.stage === 'page') }],
  ['executing', { node: idOf((s) => s.stage === 'load') }],
  ['executing', { node: idOf((s) => s.stage === 'plan') }],
  ['executing', { node: `${idOf((s) => s.stage === 'keyframe' && s.shot === 1)}:487` }],
  ['executed', { node: idOf((s) => s.output === 'keyframe' && s.shot === 1), output: { images: [{ filename: 'k1.png', subfolder: '', type: 'temp' }] } }],
  ['executing', { node: `${idOf((s) => s.stage === 'video' && s.shot === 2)}:292` }],
])
const stageText = await page.textContent('#stage')
const doneSteps = await page.$$eval('#steps li.done', (l) => l.map((x) => x.textContent))
const thumbs = await page.$$eval('#shots img', (l) => l.length)
console.log('live:', stageText, '| done steps:', doneSteps, '| thumbs:', thumbs, '| queue:', await page.textContent('#queue-pill'))
if (!stageText.includes('镜头 2')) fail(`stage not localized: ${stageText}`)
if (!doneSteps.includes('读取页面') || !doneSteps.includes('分镜脚本')) fail('steps not marked done')
if (thumbs !== 1) fail('shot thumbnail not shown')
await shot(page, 'running_zh')

await fire([['execution_success', {}]])
await page.waitForFunction(() => document.getElementById('score').textContent === '78.5')
const crit = await page.$$eval('#criteria .crit', (l) => l.length)
console.log('results: score', await page.textContent('#score'), '| grade', await page.textContent('#grade'), '| criteria', crit)
if (crit !== 7) fail('criteria bars missing')
await shot(page, 'results_zh')
await page.click('.tabs button[data-tab="storyboard"]')
if ((await page.$$eval('#board .scene', (l) => l.length)) !== 5) fail('storyboard scenes missing')
await shot(page, 'storyboard_zh')
await page.click('.tabs button[data-tab="history"]')
if ((await page.$$eval('#chart circle', (l) => l.length)) !== 3) fail('history chart points missing')

// 6. Projects library lists past ads and opens one
await page.route('**/open_ad_factory/api/projects', (route) => route.fulfill({ json: [SUMMARY, { ...SUMMARY, name: 'second', review: null, history: [], storyboard: null }] }))
await page.click('nav a[data-route="projects"]')
await page.waitForSelector('.project')
const cards = await page.$$eval('.project', (l) => l.map((c) => c.querySelector('.score-badge').textContent))
console.log('projects:', cards)
if (cards.length !== 2 || cards[0] !== '78.5') fail('projects grid wrong')
await shot(page, 'projects_zh')
await page.click('.project')
if ((await page.inputValue('#project')) !== 'ui_test' || !(location => location)(await page.url()).includes('#/create')) fail('opening a project did not return to create')

// 7. Real submission (models mocked as present, prompt not mocked): the server's validation error is shown
await page.unroute('**/prompt')
await page.evaluate(() => { document.getElementById('generate').disabled = false })
await page.click('#generate')
await page.waitForFunction(() => !document.getElementById('error').hidden && document.getElementById('error-text').textContent.length > 0, null, { timeout: 30000 })
const err = await page.textContent('#error-text')
console.log('server error shown:', err.split('\n')[0].slice(0, 80))
if (!err.includes('• ltx-2.3-22b-dev-fp8.safetensors') || /Value not in list/.test(err)) fail(`missing models not summarized: ${err.slice(0, 300)}`)

await page.selectOption('#ui-lang', 'en')
await page.goto(`${server}/open_ad_factory/#/create`)
await page.waitForSelector('#styles .style')
await shot(page, 'create_en')
await browser.close()
if (!process.exitCode) console.log('app test passed')
