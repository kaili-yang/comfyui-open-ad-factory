import { LANGUAGES, pickLanguage, t } from "./i18n.js";

const $ = (id) => document.getElementById(id);
const STYLES = ["ugc", "cinematic", "playful", "minimal"];
const STAGE_ORDER = ["load", "page", "plan", "keyframe", "video", "assemble", "save", "judge"];
const clientId = crypto.randomUUID();

let lang = pickLanguage();
let template = null;
let run = null; // { promptId, started, stages: [{key, shot, ids}], current, done:Set, project }

function stageLabel(s) {
  return t(lang, `stage.${s.stage}`, { n: s.shot });
}

function applyLanguage() {
  document.documentElement.lang = lang;
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(lang, el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) el.placeholder = t(lang, el.dataset.i18nPlaceholder);
  for (const chip of $("styles").children) chip.textContent = t(lang, `style.${chip.dataset.style}`);
  if (run) renderStages();
  if (run?.finished) $("stage").textContent = t(lang, "done", { t: run.finished });
}

function setupControls() {
  for (const [code, { name }] of Object.entries(LANGUAGES)) {
    $("ui-lang").add(new Option(name, code, false, code === lang));
    $("ad-lang").add(new Option(name, code));
  }
  const saved = JSON.parse(localStorage.getItem("oaf.form") || "{}");
  $("ad-lang").value = saved.adLang || lang;
  for (const key of ["url", "notes", "audience", "project"]) if (saved[key]) $(key).value = saved[key];
  const style = saved.style || "ugc";
  for (const s of STYLES) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.dataset.style = s;
    chip.setAttribute("aria-pressed", String(s === style));
    chip.onclick = () => { for (const c of $("styles").children) c.setAttribute("aria-pressed", String(c === chip)); };
    $("styles").append(chip);
  }
  // The ad language follows the interface language until the user picks one explicitly
  let adLangChosen = Boolean(saved.adLangChosen);
  const updateHindi = () => { $("hindi-note").hidden = $("ad-lang").value !== "hi"; };
  $("ui-lang").onchange = (e) => {
    lang = e.target.value;
    localStorage.setItem("oaf.lang", lang);
    if (!adLangChosen) $("ad-lang").value = lang;
    updateHindi();
    applyLanguage();
  };
  $("ad-lang").onchange = () => {
    adLangChosen = true;
    $("ad-lang").dataset.chosen = "1";
    updateHindi();
  };
  if (adLangChosen) $("ad-lang").dataset.chosen = "1";
  updateHindi();
  $("form").onsubmit = (e) => { e.preventDefault(); generate(); };
  $("stop").onclick = () => fetch("/interrupt", { method: "POST" });
  $("copy").onclick = async () => {
    await navigator.clipboard.writeText($("post").textContent);
    $("copy").textContent = t(lang, "copied");
    setTimeout(() => ($("copy").textContent = t(lang, "copy")), 1500);
  };
}

function formValues() {
  return {
    url: $("url").value.trim(),
    notes: $("notes").value.trim(),
    audience: $("audience").value.trim(),
    project: $("project").value.trim() || "my_ad",
    adLang: $("ad-lang").value,
    adLangChosen: $("ad-lang").dataset.chosen === "1",
    style: [...$("styles").children].find((c) => c.getAttribute("aria-pressed") === "true").dataset.style,
    feedback: $("feedback").checked,
  };
}

function buildPrompt(v) {
  const prompt = structuredClone(template.prompt);
  const seed = Math.floor(Math.random() * 2 ** 32);
  for (const node of Object.values(prompt)) {
    const i = node.inputs;
    switch (node.class_type) {
      case "OpenAdProductPage":
        Object.assign(i, { url: v.url, extra_notes: v.notes });
        break;
      case "OpenAdPlanner":
        Object.assign(i, { style: v.style, language: LANGUAGES[v.adLang].adLanguage, audience: v.audience, project: v.project, use_judge_feedback: v.feedback, seed });
        break;
      case "OpenAdViralityJudge":
        Object.assign(i, { project: v.project, seed });
        break;
      case "SaveVideo":
        i.filename_prefix = `open_ad_factory/${v.project}`;
        break;
    }
  }
  return prompt;
}

function planStages() {
  const groups = new Map();
  for (const [id, s] of Object.entries(template.stages)) {
    if (s.stage === "output") continue;
    const key = `${s.stage}:${s.shot ?? 0}`;
    if (!groups.has(key)) groups.set(key, { ...s, ids: [] });
    groups.get(key).ids.push(id);
  }
  return [...groups.values()].sort((a, b) =>
    STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage) || (a.shot ?? 0) - (b.shot ?? 0));
}

function renderStages() {
  $("stages").replaceChildren(...run.stages.map((s) => {
    const li = document.createElement("li");
    li.textContent = stageLabel(s);
    if (run.done.has(s)) li.className = "done";
    else if (run.current === s) li.className = "active";
    return li;
  }));
  $("bar").style.width = `${Math.round((run.done.size / run.stages.length) * 100)}%`;
  if (run.current && !run.finished) $("stage").textContent = stageLabel(run.current);
}

function stageFor(nodeId) {
  const id = String(nodeId).split(":")[0];
  return run.stages.find((s) => s.ids.includes(id));
}

function showError(text) {
  $("error").hidden = false;
  $("error-text").textContent = text;
  setBusy(false);
}

function setBusy(busy) {
  $("generate").disabled = busy;
  $("stop").hidden = !busy;
}

async function generate() {
  const v = formValues();
  if (!v.url && !v.notes) return showError(t(lang, "needUrl"));
  localStorage.setItem("oaf.form", JSON.stringify(v));
  $("error").hidden = true;
  run = { stages: planStages(), done: new Set(), current: null, project: v.project, started: Date.now() };
  $("progress").hidden = false;
  $("stage").textContent = t(lang, "queued");
  renderStages();
  setBusy(true);

  const res = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: buildPrompt(v), client_id: clientId }) });
  const body = await res.json();
  if (!res.ok) {
    const details = Object.values(body.node_errors || {}).flatMap((ne) => ne.errors.map((e) => `${ne.class_type}: ${e.message} ${e.details || ""}`));
    return showError([body.error?.message, ...details].filter(Boolean).join("\n"));
  }
  run.promptId = body.prompt_id;
}

function onExecuted(nodeId, output) {
  const s = template.stages[String(nodeId).split(":")[0]];
  if (!s) return;
  if (s.stage === "output" && output.text) {
    $(s.output).textContent = output.text.join("\n");
    $("results").hidden = false;
  }
  if (s.stage === "save" && output.images?.length) {
    const f = output.images[0];
    const url = `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder, type: f.type })}`;
    $("video").src = url;
    $("video").hidden = false;
    $("placeholder").hidden = true;
    $("download").href = url;
    $("download").hidden = false;
  }
}

async function onSuccess() {
  const secs = Math.round((Date.now() - run.started) / 1000);
  run.finished = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  run.done = new Set(run.stages);
  run.current = null;
  renderStages();
  $("stage").textContent = t(lang, "done", { t: run.finished });
  setBusy(false);
  $("generate").textContent = t(lang, "regenerate");
  $("generate").dataset.i18n = "regenerate";
  await loadProject(run.project);
}

async function loadProject(project) {
  const data = await (await fetch(`/open_ad_factory/api/project/${encodeURIComponent(project)}`)).json();
  if (data.review) {
    $("score").textContent = data.review.score;
    $("results").hidden = false;
  }
  const scores = data.history.map((h) => h.score);
  $("history-empty").hidden = scores.length > 0;
  if (!scores.length) return $("chart").replaceChildren();
  const x = (i) => (scores.length === 1 ? 150 : 10 + (i * 280) / (scores.length - 1));
  const y = (s) => 82 - (s / 100) * 74;
  const ns = "http://www.w3.org/2000/svg";
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", scores.map((s, i) => `${x(i)},${y(s)}`).join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "#f0ff4f");
  line.setAttribute("stroke-width", "2.5");
  const dots = scores.map((s, i) => {
    const c = document.createElementNS(ns, "circle");
    Object.entries({ cx: x(i), cy: y(s), r: 4, fill: "#f0ff4f" }).forEach(([k, val]) => c.setAttribute(k, val));
    const title = document.createElementNS(ns, "title");
    title.textContent = `${t(lang, "run", { n: i + 1 })}: ${s}`;
    c.append(title);
    return c;
  });
  $("chart").replaceChildren(line, ...dots);
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?clientId=${clientId}`);
  ws.onopen = () => { if ($("error-text").textContent === t(lang, "disconnected")) $("error").hidden = true; };
  ws.onclose = () => {
    if (run && !run.finished) showError(t(lang, "disconnected"));
    setTimeout(connect, 2000);
  };
  ws.onmessage = (event) => {
    if (typeof event.data !== "string") return;
    const { type, data } = JSON.parse(event.data);
    if (!run || !data || data.prompt_id !== run.promptId) return;
    if (type === "execution_cached") {
      for (const id of data.nodes) { const s = stageFor(id); if (s) run.done.add(s); }
      renderStages();
    } else if (type === "executing" && data.node) {
      const s = stageFor(data.node);
      if (s && s !== run.current) {
        if (run.current) run.done.add(run.current);
        run.current = s;
        renderStages();
      }
    } else if (type === "executed") {
      onExecuted(data.node, data.output || {});
    } else if (type === "execution_success") {
      onSuccess();
    } else if (type === "execution_error") {
      showError(`${data.node_type}: ${data.exception_message}`);
    } else if (type === "execution_interrupted") {
      setBusy(false);
    }
  };
}

async function main() {
  template = await (await fetch("static/prompt.json")).json();
  setupControls();
  applyLanguage();
  connect();
  loadProject($("project").value.trim() || "my_ad");
}

main();
