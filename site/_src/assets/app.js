/* Ontology method library frontend.
 * SITE = { lang, strings, methods } is baked into the page by build_site.py.
 * Browsing uses baked data/*.json (works offline / file://); the Run button
 * calls the FastAPI backend (needs `python -m backend.app`). */
"use strict";
const T = SITE.strings;
const $ = (s, r = document) => r.querySelector(s);
let current = null, cy = null, lastSteps = null;

/* ---------- tiny markdown renderer (headings/lists/tables/bold/code/quote) ---- */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
}
function md(text) {
  if (!text) return "";
  const lines = text.split("\n");
  let html = "", i = 0;
  while (i < lines.length) {
    let l = lines[i];
    if (/^#{1,6}\s/.test(l)) {
      const lvl = l.match(/^#+/)[0].length;
      html += `<h${lvl}>${inline(l.replace(/^#+\s/, ""))}</h${lvl}>`; i++; continue;
    }
    if (/^>\s?/.test(l)) {
      html += `<blockquote>${inline(l.replace(/^>\s?/, ""))}</blockquote>`; i++; continue;
    }
    if (/^\|.*\|/.test(l)) {
      const rows = []; while (i < lines.length && /^\|.*\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = r => r.split("|").slice(1, -1).map(c => c.trim());
      let t = "<table>";
      rows.forEach((r, ri) => {
        if (/^\|[\s:\-|]+\|$/.test(r)) return;
        const tag = ri === 0 ? "th" : "td";
        t += "<tr>" + cells(r).map(c => `<${tag}>${inline(c)}</${tag}>`).join("") + "</tr>";
      });
      html += t + "</table>"; continue;
    }
    if (/^\s*[-*]\s/.test(l)) {
      let u = "<ul>"; while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        u += `<li>${inline(lines[i].replace(/^\s*[-*]\s/, ""))}</li>`; i++; }
      html += u + "</ul>"; continue;
    }
    if (/^\s*\d+\.\s/.test(l)) {
      let o = "<ol>"; while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) {
        o += `<li>${inline(lines[i].replace(/^\s*\d+\.\s/, ""))}</li>`; i++; }
      html += o + "</ol>"; continue;
    }
    if (l.trim() === "") { i++; continue; }
    html += `<p>${inline(l)}</p>`; i++;
  }
  return html;
}

/* ---------- sidebar ---------- */
function statusLabel(s) { return (T.statusMap && T.statusMap[s]) || s; }
function renderList() {
  const box = $("#methods");
  box.innerHTML = "";

  // Overview pseudo-entry (comparison table)
  const ov = document.createElement("div");
  ov.className = "method-item overview-item"; ov.dataset.id = "__overview__";
  ov.innerHTML = `<div class="idx">★</div>
    <div><div class="nm">${esc(T.overview)}</div></div>`;
  ov.onclick = () => selectOverview();
  box.appendChild(ov);

  SITE.methods.forEach((m, i) => {
    const el = document.createElement("div");
    el.className = "method-item"; el.dataset.id = m.id;
    const score = m.difficulty.score;
    el.innerHTML = `<div class="idx">${String(i + 1).padStart(2, "0")}</div>
      <div>
        <div class="nm">${esc(m.name)}</div>
        <div class="meta">
          <span class="badge ${m.status}">${statusLabel(m.status)}</span>
          <span class="diff" title="${T.difficulty} ${score}"><span style="width:${Math.min(score, 10) * 10}%"></span></span>
          <span class="diff-label">${T.difficulty} ${score}</span>
        </div>
      </div>`;
    el.onclick = () => selectMethod(m.id);
    box.appendChild(el);
  });
}

/* ---------- overview / comparison table ---------- */
async function selectOverview() {
  current = "__overview__";
  document.querySelectorAll(".method-item").forEach(e =>
    e.classList.toggle("active", e.dataset.id === "__overview__"));
  let data;
  try {
    data = await (await fetch("data/overview.json")).json();
  } catch (e) {
    $("#main").innerHTML = `<p class="err">overview.json not found</p>`;
    return;
  }
  const c = data.columns || {};
  const head = ["#", T.colMethod, c.input, c.mechanism, c.output_unit,
    c.paradigm, c.distinct, T.difficulty, T.llmBackend, T.status];
  let rows = "";
  data.rows.forEach((r, i) => {
    rows += `<tr class="ov-row" data-id="${r.id}">
      <td class="ov-idx">${String(i + 1).padStart(2, "0")}</td>
      <td><b>${esc(r.name)}</b></td>
      <td>${esc(r.input || "")}</td>
      <td>${esc(r.mechanism || "")}</td>
      <td>${esc(r.output_unit || "")}</td>
      <td>${esc(r.paradigm || "")}</td>
      <td>${esc(r.distinct || "")}</td>
      <td class="ov-num">${r.difficulty ?? ""}</td>
      <td><code>${esc(r.llm || "")}</code></td>
      <td><span class="badge ${r.status}">${statusLabel(r.status)}</span></td>
    </tr>`;
  });
  $("#main").innerHTML = `<h2>${esc(T.overviewTitle)}</h2>
    <p class="hint">${esc(T.overviewIntro)}</p>
    <div class="ov-wrap"><table class="ov-table">
      <thead><tr>${head.map(h => `<th>${esc(h || "")}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  document.querySelectorAll(".ov-row").forEach(tr =>
    tr.addEventListener("click", () => selectMethod(tr.dataset.id)));
}

/* ---------- detail ---------- */
async function selectMethod(id) {
  current = id;
  document.querySelectorAll(".method-item").forEach(e =>
    e.classList.toggle("active", e.dataset.id === id));
  let data;
  try {
    const r = await fetch(`data/method-${id}.json`);
    data = await r.json();
  } catch (e) {
    const m = SITE.methods.find(x => x.id === id);
    data = { ...m, docs: {}, sample_input: null, implemented: false };
  }
  const m = SITE.methods.find(x => x.id === id) || data;
  const doc = (data.docs && data.docs[SITE.lang]) || "";
  const paper = m.paper || {};
  const paperStr = [paper.venue, paper.arxiv ? "arXiv:" + paper.arxiv : null]
    .filter(Boolean).join(" · ");

  let html = `<h2>${esc(m.name)}</h2>
    <div class="kv">
      <span><b>${T.difficulty}</b> ${m.difficulty.score} (${T.rank} ${m.difficulty.rank})</span>
      <span><b>${T.status}</b> ${statusLabel(m.status)}</span>
      <span><b>${T.llmBackend}</b> ${m.llm_dependency}</span>
      <span><b>${T.paper}</b> ${esc(paperStr)}</span>
    </div>`;

  if (data.implemented) {
    const sample = data.sample_input || "";
    html += `<div class="runbox">
      <div><b>${T.inputLabel}</b></div>
      <textarea id="input">${esc(sample)}</textarea>
      <div class="controls">
        <button id="runBtn">${T.run}</button>
        <button class="secondary" id="sampleBtn">${T.loadSample}</button>
        <select id="backend">
          <option value="mock">mock</option>
          <option value="gemini">gemini</option>
          <option value="anthropic">anthropic</option>
          <option value="hf_local">hf_local</option>
        </select>
        <span class="hint" id="runHint"></span>
      </div>
      <div class="err" id="err"></div>
    </div>
    <div id="result"></div>`;
  } else {
    html += `<div class="runbox"><span class="hint">${T.notImplemented}</span></div>`;
  }
  html += `<div class="doc">${md(doc)}</div>`;
  $("#main").innerHTML = html;
  cy = null; lastSteps = null;

  if (data.implemented) {
    const sample = data.sample_input || "";
    $("#runBtn").onclick = () => runMethod(id);
    $("#sampleBtn").onclick = () => { $("#input").value = sample; };
  }
}

/* ---------- run + graph ---------- */
async function runMethod(id) {
  const btn = $("#runBtn"), err = $("#err");
  err.textContent = ""; btn.disabled = true; btn.textContent = T.running;
  try {
    const r = await fetch(`/api/methods/${id}/run`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_text: $("#input").value, backend: $("#backend").value }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const data = await r.json();
    lastSteps = data.steps;
    renderResult(data);
  } catch (e) {
    err.textContent = `${T.error}: ${e.message}\n${T.apiHint}`;
  } finally {
    btn.disabled = false; btn.textContent = T.run;
  }
}

function renderResult(data) {
  const c = data.manifest.counts;
  const ttl = encodeURIComponent(data.ttl || "");
  let html = `<h3>${T.processSteps}</h3>
    <div class="stepbar">
      <span id="stepLbl"></span>
      <input type="range" id="stepRange" min="1" max="${data.steps.length}" value="${data.steps.length}">
    </div>
    <div id="cqLine"></div>
    <div class="added-list" id="addedLine"></div>
    <div id="graph"></div>
    <h3>${T.finalOntology}</h3>
    <div class="counts"><span>${T.classes}: <b>${c.classes}</b></span>
      <span>${T.objectProperties}: <b>${c.object_properties}</b></span>
      <span>${T.dataProperties}: <b>${c.data_properties}</b></span></div>
    <p><a class="dl" download="ontology.ttl" href="data:text/turtle;charset=utf-8,${ttl}">${T.downloadTtl}</a></p>`;
  $("#result").innerHTML = html;
  const range = $("#stepRange");
  range.oninput = () => showStep(+range.value);
  showStep(data.steps.length);
}

function labelOf(x) {
  if (x == null) return "";
  if (typeof x === "string") return x;
  return x.name || x.label || x.id ||
    [x.entity_1 || x.source, x.relationship || x.label, x.entity_2 || x.target]
      .filter(Boolean).join("→") || JSON.stringify(x);
}

function showStep(n) {
  const step = lastSteps[n - 1] || {};
  $("#stepLbl").textContent = `${T.step} ${n} ${T.of} ${lastSteps.length}`;
  const cq = step.cq || step.label || step.entity || "";
  $("#cqLine").innerHTML = cq ? `<span class="cq">${T.stepInput}: ${esc(cq)}</span>` : "";
  // Generic: render any array-valued field under `added` (classes, object_properties,
  // entities, relations, candidates, …) so every method's step shape is supported.
  const a = step.added || {};
  const parts = [];
  for (const [k, v] of Object.entries(a)) {
    if (Array.isArray(v) && v.length)
      parts.push(`${k}: ${v.map(labelOf).filter(Boolean).join(", ")}`);
  }
  $("#addedLine").textContent = parts.length ? `${T.added} — ${parts.join(" | ")}` : "";
  drawGraph(step.graph || { nodes: [], edges: [] });
}

function drawGraph(graph) {
  if (typeof cytoscape === "undefined") {
    $("#graph").innerHTML = `<p class="hint" style="padding:16px">cytoscape.js not loaded (offline?)</p>`;
    return;
  }
  const nodes = graph.nodes || [];
  const ids = new Set(nodes.map(n => n.data.id));
  // drop dangling edges (source/target not in this snapshot) so cytoscape won't throw
  const edges = (graph.edges || []).filter(
    e => ids.has(e.data.source) && ids.has(e.data.target));
  const elements = [...nodes, ...edges];
  if (!cy) {
    cy = cytoscape({
      container: $("#graph"), elements,
      style: [
        { selector: "node", style: {
          "background-color": "#5b9dff", "label": "data(label)", "color": "#fff",
          "font-size": "11px", "text-valign": "center", "text-halign": "center",
          "width": "label", "height": "26px", "padding": "8px", "shape": "round-rectangle" } },
        { selector: "edge", style: {
          "width": 1.5, "line-color": "#43d39e", "target-arrow-color": "#43d39e",
          "target-arrow-shape": "triangle", "curve-style": "bezier",
          "label": "data(label)", "font-size": "9px", "color": "#9aa3b2" } },
      ],
      layout: { name: "cose", animate: false },
    });
  } else {
    cy.elements().remove(); cy.add(elements);
    cy.layout({ name: "cose", animate: false }).run();
  }
}

renderList();
selectOverview();  // land on the comparison table
