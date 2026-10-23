// Load the raw workflow into the real ComfyUI frontend, convert it to an API prompt,
// check the values that matter, submit it for server-side validation, and save the
// frontend-normalized workflow.
//
//   node tools/validate_workflow.mjs build/raw_workflow.json example_workflows/open_ad_factory.json
//
// Needs @playwright/test installed in PLAYWRIGHT_DIR (e.g. a ComfyUI_frontend checkout) and a running ComfyUI.
import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const { chromium } = createRequire(join(process.env.PLAYWRIGHT_DIR ?? process.cwd(), 'package.json'))('@playwright/test')

const [rawPath, outPath, server = 'http://127.0.0.1:8188'] = process.argv.slice(2)
const raw = JSON.parse(readFileSync(rawPath, 'utf8'))

const browser = await chromium.launch()
const page = await browser.newPage()
page.on('pageerror', (e) => console.error('pageerror:', e.message))
await page.goto(server)
await page.waitForFunction(() => window.app?.graph, null, { timeout: 120000 })

const result = await page.evaluate(async (wf) => {
  await window.app.loadGraphData(wf)
  const { output } = await window.app.graphToPrompt()
  const res = await fetch('/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: output, client_id: 'validate' })
  })
  return { output, status: res.status, body: await res.json(), workflow: window.app.graph.serialize() }
}, raw)
await browser.close()

const byType = (t) => Object.entries(result.output).filter(([, n]) => n.class_type === t)
const fail = (msg) => { console.error('FAIL:', msg); process.exitCode = 1 }

// The planner, shots, assembler and judge must keep their widget values by name
const planner = byType('OpenAdPlanner')[0]?.[1]
if (!planner || planner.inputs.num_shots !== '4' || planner.inputs.seconds_per_shot !== 5 || planner.inputs.style !== 'ugc') fail(`planner inputs ${JSON.stringify(planner?.inputs)}`)
const shots = byType('OpenAdShot').map(([, n]) => n.inputs.shot).sort()
if (JSON.stringify(shots) !== '[1,2,3,4]') fail(`shots ${shots}`)
const page0 = byType('OpenAdProductPage')[0]?.[1]
if (!page0 || page0.inputs.width !== 768 || page0.inputs.height !== 1344) fail(`page inputs ${JSON.stringify(page0?.inputs)}`)
const judge = byType('OpenAdViralityJudge')[0]?.[1]
if (!judge || !Array.isArray(judge.inputs.video) || !Array.isArray(judge.inputs.clip)) fail('judge not wired')
const asm = byType('OpenAdAssemble')[0]?.[1]
for (let i = 1; i <= 4; i++) if (!Array.isArray(asm?.inputs[`video_${i}`])) fail(`assemble video_${i} not wired`)

// The LTX stage inside each subgraph must get the shot's video prompt and our size and duration
const enc = byType('CLIPTextEncode').filter(([, n]) => Array.isArray(n.inputs.text))
console.log('api nodes:', Object.keys(result.output).length, 'CLIPTextEncode linked:', enc.length)
const empty = byType('EmptyLTXVLatentVideo').map(([, n]) => n.inputs)
console.log('EmptyLTXVLatentVideo inputs:', JSON.stringify(empty[0]))

// Server validation: only missing model files are acceptable on a machine without the models
const errors = []
for (const [id, ne] of Object.entries(result.body.node_errors ?? {})) {
  for (const e of ne.errors) errors.push({ id, cls: ne.class_type, type: e.type, input: e.extra_info?.input_name, msg: e.details })
}
const unexpected = errors.filter((e) => !(e.type === 'value_not_in_list' && /(name|encoder|model|lora|ckpt|unet|vae|clip)/i.test(e.input ?? '')))
console.log('server status', result.status, 'error:', result.body.error?.type ?? 'none')
console.log('missing-model errors:', errors.length - unexpected.length)
for (const e of unexpected) fail(`unexpected validation error ${JSON.stringify(e)}`)

writeFileSync(rawPath.replace(/\.json$/, '.api.json'), JSON.stringify(result.output, null, 2))

if (outPath && !process.exitCode) {
  writeFileSync(outPath, JSON.stringify(result.workflow, null, 2))
  console.log('wrote', outPath)
}
