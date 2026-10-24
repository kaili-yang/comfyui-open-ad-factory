import { LANGUAGES, pickLanguage, t } from "./i18n.js";

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
};
const icon = (name) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
};
const viewUrl = (f) => `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder || "", type: f.type || "output" })}`;

const STYLES = ["ugc", "cinematic", "playful", "minimal"];
const SHOT_ROLES = ["hook", "problem", "solution", "cta"]; // planner layout for 4 shots
const STEPS = [
  { key: "read", stages: ["page"] },
  { key: "plan", stages: ["load", "plan"] }, // the loader feeds the planner and can run anywhere before it
  { key: "shots", stages: ["keyframe", "video"] },
  { key: "assemble", stages: ["assemble", "save"] },
  { key: "judge", stages: ["judge"] },
];
const CRITERIA = ["hook", "product_clarity", "message", "pacing", "audio", "cta", "visual_quality"];
const GAUGE = 2 * Math.PI * 52;
const clientId = crypto.randomUUID();

const state = {
  lang: pickLanguage(),
  route: "create",
  template: null,
  models: null, // { total, missing: [{folder, file}] }
  connected: false,
  queue: 0,
  product: { state: "empty" },
  run: null, // { promptId, project, started, stages, done:Set, current, finished }
  keyframes: {}, // shot -> url, for the current session
  data: null, // last project summary shown in results
  tab: "overview",
};

const tr = (key, vars) => t(state.lang, key, vars);

/* ---------- language ---------- */
function applyLanguage() {
  document.documentElement.lang = state.lang;
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = tr(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) node.placeholder = tr(node.dataset.i18nPlaceholder);
  renderStyles();
  renderTitle();
  renderStatus();
  renderModels();
  renderRun();
  renderResults();
  if (state.route === "projects") renderProjects(state.projects || []);
  $("generate").querySelector("span").textContent = tr(state.data?.review ? "regenerate" : "generate");
}

/* ---------- routing ---------- */
function route() {
  state.route = location.hash.startsWith("#/projects") ? "projects" : "create";
  for (const a of document.querySelectorAll("nav a[data-route]")) a.classList.toggle("active", a.dataset.route === state.route);
  $("view-create").hidden = state.route !== "create";
  $("view-projects").hidden = state.route !== "projects";
  renderTitle();
  if (state.route === "projects") loadProjects();
}

function renderTitle() {
  const projects = state.route === "projects";
  $("page-title").textContent = tr(projects ? "projects.title" : "create.title");
  $("page-sub").textContent = tr(projects ? "projects.subtitle" : "create.subtitle");
}

/* ---------- toasts ---------- */
function toast(text, kind = "ok") {
  const node = el("div", { class: `toast ${kind}` }, icon(kind === "ok" ? "check" : "alert"), el("span", { text }));
  $("toasts").append(node);
  setTimeout(() => node.remove(), 3500);
}

/* ---------- status: connection, queue, device, models ---------- */
function renderStatus() {
  $("conn-pill").className = `pill ${state.connected ? "ok" : "bad"}`;
  $("conn-text").textContent = tr(state.connected ? "status.connected" : "status.offline");
  $("queue-pill").textContent = state.queue ? tr("status.queue", { n: state.queue }) : tr("status.idle");
}

async function loadDevice() {
  const stats = await (await fetch("/system_stats")).json();
  const dev = stats.devices?.[0];
  if (!dev) return;
  const name = dev.name.replace(/^\w+:\d+\s*/, "").replace(/\s*:.*$/, "");
  $("device").textContent = `${name} · ${Math.round(dev.vram_total / 2 ** 30)} GB`;
}

async function checkModels() {
  const folders = [...new Set(state.template.models.map((m) => m.folder))];
  const lists = Object.fromEntries(await Promise.all(folders.map(async (f) => {
    const res = await fetch(`/models/${f}`);
    return [f, res.ok ? new Set(await res.json()) : new Set()];
  })));
  state.models = { total: state.template.models.length, missing: state.template.models.filter((m) => !lists[m.folder].has(m.file)) };
  renderModels();
}

function renderModels() {
  const m = state.models;
  if (!m) { $("models-status").textContent = tr("models.checking"); return; }
  const ok = m.missing.length === 0;
  $("models-status").textContent = ok ? tr("models.ready", { n: m.total }) : tr("models.missing", { m: m.missing.length, n: m.total });
  $("models-badge").className = `badge ${ok ? "ok" : "warn"}`;
  $("models-badge").textContent = `${m.total - m.missing.length}/${m.total}`;
  $("models-meter").style.width = `${((m.total - m.missing.length) / m.total) * 100}%`;
  $("models-meter").parentElement.classList.toggle("warn", !ok);
  $("models-missing").hidden = ok;
  $("models-list").replaceChildren(...m.missing.map((x) => el("li", {}, el("span", { text: `${x.folder}/` }), x.file)));
}

/* ---------- composer ---------- */
function renderStyles() {
  const current = state.style;
  $("styles").replaceChildren(...STYLES.map((s) => {
    const card = el("button", { type: "button", class: "style", role: "radio", "aria-checked": String(s === current), "data-style": s },
      el("div", { class: `art ${s}` }),
      el("div", { class: "txt" }, el("b", { text: tr(`style.${s}`) }), el("span", { text: tr(`styleDesc.${s}`) })));
    card.onclick = () => { state.style = s; renderStyles(); };
    return card;
  }));
}

function renderProduct() {
  const p = state.product;
  $("product").dataset.state = p.state;
  if (p.state !== "ok") return;
  $("product-img").src = p.info.images?.[0] || "static/logo.svg";
  $("product-name").textContent = p.info.name;
  $("product-meta").textContent = [p.info.brand, p.info.price && `${p.info.price} ${p.info.currency || ""}`.trim()].filter(Boolean).join(" · ");
  $("product-desc").textContent = p.info.description;
}

async function previewProduct() {
  const url = $("url").value.trim();
  if (!/^https?:\/\/\S+\.\S+/.test(url) || url === state.product.url) return;
  state.product = { state: "loading", url };
  renderProduct();
  const res = await fetch(`/open_ad_factory/api/product?${new URLSearchParams({ url })}`);
  if ($("url").value.trim() !== url) return;
  state.product = res.ok ? { state: "ok", url, info: await res.json() } : { state: "error", url };
  renderProduct();
}

function formValues() {
  return {
    url: $("url").value.trim(),
    notes: $("notes").value.trim(),
    audience: $("audience").value.trim(),
    project: ($("project").value.trim() || "my_ad").replace(/[^A-Za-z0-9_-]+/g, "_"),
    adLang: $("ad-lang").value,
    adLangChosen: $("ad-lang").dataset.chosen === "1",
    style: state.style,
    feedback: $("feedback").checked,
  };
}

function buildPrompt(v) {
  const prompt = structuredClone(state.template.prompt);
  const seed = Math.floor(Math.random() * 2 ** 32);
  for (const node of Object.values(prompt)) {
    const i = node.inputs;
    if (node.class_type === "OpenAdProductPage") Object.assign(i, { url: v.url, extra_notes: v.notes });
    if (node.class_type === "OpenAdPlanner") Object.assign(i, { style: v.style, language: LANGUAGES[v.adLang].adLanguage, audience: v.audience, project: v.project, use_judge_feedback: v.feedback, seed });
    if (node.class_type === "OpenAdViralityJudge") Object.assign(i, { project: v.project, seed, language: LANGUAGES[state.lang].adLanguage });
    if (node.class_type === "SaveVideo") i.filename_prefix = `open_ad_factory/${v.project}`;
  }
  return prompt;
}

function showError(text) {
  $("error").hidden = !text;
  $("error-text").textContent = text || "";
}

async function generate() {
  const v = formValues();
  if (!v.url && !v.notes) return showError(tr("needUrl"));
  if (state.models?.missing.length) {
    return showError(`${tr("needModels")}\n${state.models.missing.map((m) => `${m.folder}/${m.file}`).join("\n")}`);
  }
  localStorage.setItem("oaf.form", JSON.stringify(v));
  showError("");
  state.keyframes = {};
  state.run = { project: v.project, started: Date.now(), stages: planStages(), done: new Set(), current: null };
  setVideo(null);
  renderRun();

  const res = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: buildPrompt(v), client_id: clientId }) });
  const body = await res.json();
  if (!res.ok) {
    state.run = null;
    renderRun();
    const errors = Object.values(body.node_errors || {}).flatMap((ne) => ne.errors.map((e) => ({ ...e, cls: ne.class_type })));
    const isModel = (e) => e.type === "value_not_in_list" && /\.(safetensors|pt|pth|gguf)$/.test(String(e.extra_info?.received_value));
    const models = [...new Set(errors.filter(isModel).map((e) => e.extra_info.received_value))];
    const other = [...new Set(errors.filter((e) => !isModel(e)).map((e) => `${e.cls}: ${e.message} ${e.details || ""}`.trim()))];
    return showError([models.length ? `${tr("needModels")}\n${models.map((m) => `• ${m}`).join("\n")}` : body.error?.message, ...other].filter(Boolean).join("\n"));
  }
  state.run.promptId = body.prompt_id;
  toast(tr("toast.started"));
}

/* ---------- run progress ---------- */
function planStages() {
  const groups = new Map();
  for (const [id, s] of Object.entries(state.template.stages)) {
    if (s.stage === "output") continue;
    const key = `${s.stage}:${s.shot ?? 0}`;
    if (!groups.has(key)) groups.set(key, { ...s, ids: [] });
    groups.get(key).ids.push(id);
  }
  return [...groups.values()];
}

function stageFor(nodeId) {
  const id = String(nodeId).split(":")[0];
  return state.run.stages.find((s) => s.ids.includes(id));
}

function formatTime(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function renderRun() {
  const run = state.run;
  const busy = Boolean(run && !run.finished);
  $("generate").disabled = busy;
  $("stop").hidden = !busy;
  $("phone-live").hidden = !busy;
  $("phone-idle").hidden = busy || !$("video").hidden;
  $("studio-badge").className = `badge ${busy ? "run" : run?.finished ? "ok" : ""}`;
  $("studio-badge").textContent = tr(busy ? "studio.running" : run?.finished ? "studio.done" : "studio.idle");
  $("elapsed").textContent = run ? tr("elapsed", { t: formatTime((run.finishedAt || Date.now()) - run.started) }) : "";
  if (busy) $("stage").textContent = run.current ? tr(`stage.${run.current.stage}`, { n: run.current.shot }) : tr("queued");

  const shotStages = run ? run.stages.filter((s) => s.stage === "keyframe" || s.stage === "video") : [];
  $("steps").replaceChildren(...STEPS.map((step) => {
    const stages = run ? run.stages.filter((s) => step.stages.includes(s.stage)) : [];
    const done = run && stages.length > 0 && stages.every((s) => run.done.has(s));
    const active = busy && stages.includes(run.current);
    const label = step.key === "shots"
      ? tr("step.shots", { d: shotStages.filter((s) => run?.done.has(s)).length / 2 | 0, n: SHOT_ROLES.length })
      : tr(`step.${step.key}`);
    return el("li", { class: done ? "done" : active ? "active" : "", text: label });
  }));

  $("shots").replaceChildren(...SHOT_ROLES.map((role, i) => {
    const n = i + 1;
    const active = busy && run.current?.shot === n;
    const url = state.keyframes[n];
    return el("div", { class: `shot${active ? " active" : ""}` },
      el("div", { class: "thumb" }, url ? el("img", { src: url, alt: "" }) : el("span", { text: String(n) })),
      el("span", { text: tr(`role.${role}`) }));
  }));
}

function setVideo(file) {
  $("video").hidden = !file;
  $("download").hidden = !file;
  if (file) {
    const url = viewUrl(file);
    if (!$("video").src.endsWith(url)) $("video").src = url;
    $("download").href = url;
  } else {
    $("video").removeAttribute("src");
  }
  $("phone-idle").hidden = Boolean(file) || Boolean(state.run && !state.run.finished);
}

function onExecuted(nodeId, output) {
  const s = state.template.stages[String(nodeId).split(":")[0]];
  if (!s) return;
  if (s.output === "keyframe" && output.images?.length) {
    state.keyframes[s.shot] = viewUrl(output.images[0]);
    renderRun();
  }
  if (s.stage === "save" && output.images?.length) setVideo(output.images[0]);
}

async function onSuccess() {
  const run = state.run;
  run.finished = true;
  run.finishedAt = Date.now();
  run.done = new Set(run.stages);
  run.current = null;
  renderRun();
  toast(tr("toast.done"));
  await loadProject(run.project);
}

/* ---------- results ---------- */
async function loadProject(name) {
  state.data = await (await fetch(`/open_ad_factory/api/project/${encodeURIComponent(name)}`)).json();
  if (state.data.video) setVideo(state.data.video);
  renderResults();
  $("generate").querySelector("span").textContent = tr(state.data.review ? "regenerate" : "generate");
}

function gradeKey(score) {
  return score >= 85 ? "A" : score >= 70 ? "B" : score >= 55 ? "C" : "D";
}

function renderResults() {
  const d = state.data;
  const has = Boolean(d && (d.review || d.storyboard));
  $("results-empty").hidden = has;
  for (const tab of document.querySelectorAll(".tabs button")) tab.setAttribute("aria-selected", String(tab.dataset.tab === state.tab));
  for (const panel of document.querySelectorAll(".tab-panel")) panel.hidden = !has || panel.dataset.panel !== state.tab;
  if (!has) return;

  const r = d.review;
  const score = r?.score ?? null;
  $("score").textContent = score ?? "–";
  $("gauge").style.strokeDashoffset = String(GAUGE * (1 - (score ?? 0) / 100));
  $("grade").textContent = score == null ? tr("projects.noScore") : tr(`grade.${gradeKey(score)}`);
  $("grade").hidden = false;
  $("criteria").replaceChildren(...CRITERIA.filter((c) => r?.scores?.[c] != null).map((c) => {
    const v = r.scores[c];
    return el("div", { class: `crit ${v >= 7 ? "" : v >= 5 ? "mid" : "low"}` },
      el("span", { text: tr(`crit.${c}`) }), el("b", { class: "tabnum", text: v.toFixed(1) }),
      el("div", { class: "bar" }, el("i", { style: `width:${v * 10}%` })));
  }));
  $("verdict").textContent = r?.verdict || "";
  $("strengths").replaceChildren(...(r?.strengths || []).map((s) => el("li", { text: s })));
  $("fixes").replaceChildren(...(r?.fixes || []).map((s) => el("li", { text: s })));

  const sb = d.storyboard;
  const scenes = (sb?.shots || []).map((shot, i) => el("article", { class: "scene" },
    el("div", { class: "thumb" }, state.keyframes[i + 1] ? el("img", { src: state.keyframes[i + 1], alt: "" }) : icon("film")),
    el("div", { class: "body" },
      el("div", { class: "role" }, tr(`role.${shot.role}`), el("span", { text: tr("shot", { n: i + 1 }) })),
      el("dl", {}, el("dt", { text: tr("caption") }), el("dd", { text: shot.caption }), el("dt", { text: tr("voiceover") }), el("dd", { text: `“${shot.voiceover}”` })))));
  if (sb) scenes.push(el("article", { class: "scene" }, el("div", { class: "thumb" }, el("img", { src: "static/logo.svg", alt: "", style: "width:40px;height:40px;object-fit:contain" })),
    el("div", { class: "body" }, el("div", { class: "role" }, tr("endCard")), el("dl", {}, el("dt", { text: sb.headline }), el("dd", { text: sb.cta })))));
  $("board").replaceChildren(...scenes);

  $("post-text").textContent = sb?.post_caption || "";
  $("post-tags").replaceChildren(...(sb?.hashtags || []).map((h) => el("span", { text: h })));
  renderChart(d.history || []);
}

function renderChart(history) {
  const scores = history.map((h) => h.score);
  $("history-empty").hidden = scores.length > 0;
  const ns = "http://www.w3.org/2000/svg";
  const svg = $("chart");
  if (!scores.length) return svg.replaceChildren();
  const x = (i) => (scores.length === 1 ? 300 : 40 + (i * 540) / (scores.length - 1));
  const y = (s) => 140 - (s / 100) * 120;
  const mk = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const grid = [0, 50, 100].flatMap((v) => [mk("line", { x1: 30, x2: 590, y1: y(v), y2: y(v), stroke: "#262233" }), Object.assign(mk("text", { x: 4, y: y(v) + 4 }), { textContent: v })]);
  const pts = scores.map((s, i) => `${x(i)},${y(s)}`).join(" ");
  const area = mk("polygon", { points: `${x(0)},140 ${pts} ${x(scores.length - 1)},140`, fill: "rgba(240,255,79,.08)" });
  const line = mk("polyline", { points: pts, fill: "none", stroke: "#f0ff4f", "stroke-width": 2.5, "stroke-linejoin": "round" });
  const dots = scores.map((s, i) => {
    const g = mk("g", {});
    g.append(mk("circle", { cx: x(i), cy: y(s), r: 4.5, fill: "#f0ff4f" }), Object.assign(mk("text", { x: x(i) - 10, y: y(s) - 10 }), { textContent: s }));
    const title = mk("title", {});
    title.textContent = tr("run", { n: i + 1 });
    g.append(title);
    return g;
  });
  svg.replaceChildren(...grid, area, line, ...dots);
}

/* ---------- projects ---------- */
async function loadProjects() {
  state.projects = await (await fetch("/open_ad_factory/api/projects")).json();
  renderProjects(state.projects);
}

function renderProjects(items) {
  $("projects-empty").hidden = items.length > 0;
  const rtf = new Intl.RelativeTimeFormat(state.lang, { numeric: "auto" });
  const ago = (ts) => {
    const mins = Math.round((ts * 1000 - Date.now()) / 60000);
    return Math.abs(mins) < 60 ? rtf.format(mins, "minute") : Math.abs(mins) < 1440 ? rtf.format(Math.round(mins / 60), "hour") : rtf.format(Math.round(mins / 1440), "day");
  };
  $("projects").replaceChildren(...items.map((p) => {
    const score = p.review?.score;
    const media = p.video
      ? el("video", { src: viewUrl(p.video), muted: "", preload: "metadata", playsinline: "" })
      : el("img", { src: "static/logo.svg", alt: "" });
    const card = el("a", { class: "project", href: "#/create" },
      el("div", { class: "media" }, media, el("span", { class: `score-badge${score == null ? " none" : ""}`, text: score == null ? tr("projects.noScore") : String(score) })),
      el("div", { class: "info" }, el("b", { text: p.storyboard?.product_name || p.name }),
        el("span", { class: "muted small", text: `${p.name} · ${tr("projects.runs", { n: p.history.length })}` }),
        p.updated ? el("span", { class: "muted tiny", text: ago(p.updated) }) : null));
    card.onmouseenter = () => card.querySelector("video")?.play();
    card.onmouseleave = () => card.querySelector("video")?.pause();
    card.onclick = () => openProject(p);
    return card;
  }));
}

function openProject(p) {
  $("project").value = p.name;
  const url = /URL: (\S+)/.exec(p.storyboard?.brief || "")?.[1];
  if (url) { $("url").value = url; previewProduct(); }
  state.keyframes = {};
  state.run = null;
  state.data = p;
  setVideo(p.video);
  renderRun();
  renderResults();
}

/* ---------- websocket ---------- */
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?clientId=${clientId}`);
  ws.onopen = () => { state.connected = true; renderStatus(); };
  ws.onclose = () => {
    state.connected = false;
    renderStatus();
    if (state.run && !state.run.finished) showError(tr("disconnected"));
    setTimeout(connect, 2000);
  };
  ws.onmessage = (event) => {
    if (typeof event.data !== "string") return;
    const { type, data } = JSON.parse(event.data);
    if (type === "status") {
      state.queue = data?.status?.exec_info?.queue_remaining ?? 0;
      return renderStatus();
    }
    const run = state.run;
    if (!run || !data || data.prompt_id !== run.promptId) return;
    if (type === "execution_cached") {
      for (const id of data.nodes) { const s = stageFor(id); if (s) run.done.add(s); }
      renderRun();
    } else if (type === "executing" && data.node) {
      const s = stageFor(data.node);
      if (s && s !== run.current) {
        if (run.current) run.done.add(run.current);
        run.current = s;
        renderRun();
      }
    } else if (type === "executed") {
      onExecuted(data.node, data.output || {});
    } else if (type === "execution_success") {
      onSuccess();
    } else if (type === "execution_error") {
      run.finished = true;
      run.finishedAt = Date.now();
      renderRun();
      showError(`${data.node_type}: ${data.exception_message}`);
    } else if (type === "execution_interrupted") {
      run.finished = true;
      run.finishedAt = Date.now();
      renderRun();
      toast(tr("toast.stopped"), "warn");
    }
  };
}

/* ---------- setup ---------- */
function setup() {
  for (const [code, { name }] of Object.entries(LANGUAGES)) {
    $("ui-lang").add(new Option(name, code, false, code === state.lang));
    $("ad-lang").add(new Option(name, code));
  }
  const saved = JSON.parse(localStorage.getItem("oaf.form") || "{}");
  state.style = saved.style || "ugc";
  $("ad-lang").value = saved.adLangChosen ? saved.adLang : state.lang;
  if (saved.adLangChosen) $("ad-lang").dataset.chosen = "1";
  for (const key of ["url", "notes", "audience", "project"]) if (saved[key]) $(key).value = saved[key];
  if (saved.feedback === false) $("feedback").checked = false;

  if (!/Mac|iPhone|iPad/.test(navigator.platform)) $("generate").querySelector("kbd").textContent = "Ctrl ↵";
  const updateHindi = () => { $("hindi-note").hidden = $("ad-lang").value !== "hi"; };
  $("ui-lang").onchange = (e) => {
    state.lang = e.target.value;
    localStorage.setItem("oaf.lang", state.lang);
    if ($("ad-lang").dataset.chosen !== "1") $("ad-lang").value = state.lang;
    updateHindi();
    applyLanguage();
  };
  $("ad-lang").onchange = () => { $("ad-lang").dataset.chosen = "1"; updateHindi(); };
  updateHindi();

  $("fetch").onclick = () => { state.product.url = null; previewProduct(); };
  $("url").addEventListener("change", previewProduct);
  $("url").addEventListener("paste", () => setTimeout(previewProduct, 0));
  $("form").onsubmit = (e) => { e.preventDefault(); generate(); };
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && state.route === "create" && !$("generate").disabled) generate();
  });
  $("stop").onclick = () => fetch("/interrupt", { method: "POST" });
  $("copy").onclick = async () => {
    const sb = state.data?.storyboard;
    await navigator.clipboard.writeText(`${sb?.post_caption || ""}\n${(sb?.hashtags || []).join(" ")}`.trim());
    toast(tr("copied"));
  };
  for (const tab of document.querySelectorAll(".tabs button")) tab.onclick = () => { state.tab = tab.dataset.tab; renderResults(); };
  setInterval(() => { if (state.run && !state.run.finished) $("elapsed").textContent = tr("elapsed", { t: formatTime(Date.now() - state.run.started) }); }, 1000);
  window.addEventListener("hashchange", route);
}

async function main() {
  state.template = await (await fetch("static/prompt.json")).json();
  setup();
  applyLanguage();
  route();
  connect();
  loadDevice();
  checkModels();
  previewProduct();
  const project = $("project").value.trim();
  if (project) loadProject(project);
}

main();
