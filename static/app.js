const $ = (id) => document.getElementById(id);
const SAMPLE = `# type | text  ("Button label:" and "Error message:" prefixes work too)
button | Submit
button | Click here
button | Save Changes
button | Log in
button | Sign in
button | CANCEL
label | Pwd
label | Username
label | User name
label | E-mail
label | Enter the red button on the left to continue
message | Error 0x80070057: invalid parameter
message | Your password is too short. Use at least 8 characters.
message | The file could not be saved because the payload was malformed and the session credentials were not authenticated by the server.
Error message: Something went wrong!!
message | You entered an illegal value.
message | Your changes have been saved.
button | Delete account
button | Remove item`;
let last = null;
let shotFile = null;
let shotUrl = null;

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tone = (n) => (n >= 80 ? "good" : n >= 60 ? "fair" : "poor");
const CATS = { clarity: "Clarity", accessibility: "Accessibility", reading: "Reading level", consistency: "Consistency" };
const ORDER = { high: 0, medium: 1, low: 2 };
const cut = (t, n) => (t.length > n ? t.slice(0, n) + "…" : t);

function showError(msg, hint) {
  const e = $("error"); e.textContent = msg || ""; e.hidden = !msg;
  $("error-actions").hidden = !(msg && hint === "screenshot");
}
function busy(on) {
  $("busy").hidden = !on;
  ["scan", "analyze", "shot-go"].forEach((id) => { if ($(id)) $(id).disabled = on || (id === "shot-go" && !shotFile); });
}
function showResults() {
  const res = $("results"); res.hidden = false; res.focus(); res.scrollIntoView({ behavior: "smooth" });
}

// ------------------------------------------------------------------ tabs
const TABS = ["url", "shot", "text"];
function selectTab(which) {
  TABS.forEach((t) => {
    const on = t === which;
    $("tab-" + t).setAttribute("aria-selected", on); $("tab-" + t).tabIndex = on ? 0 : -1;
    $("panel-" + t).hidden = !on;
  });
  showError("");
}
TABS.forEach((t) => ($("tab-" + t).onclick = () => selectTab(t)));
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const cur = TABS.findIndex((t) => $("tab-" + t).getAttribute("aria-selected") === "true");
  const next = TABS[(cur + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
  selectTab(next); $("tab-" + next).focus();
});
$("to-shot").onclick = () => { selectTab("shot"); $("drop").focus(); };

// ------------------------------------------------------------------ requests
async function post(url, opts) {
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (e) { data = { error: "The server sent an unexpected reply." }; }
  if (!r.ok) { const err = new Error(data.error || "Something went wrong."); err.hint = data.hint; throw err; }
  return data;
}
async function analyze() {
  showError("");
  const text = $("text").value;
  if (!text.trim()) return showError("Please enter at least one UI string.");
  busy(true);
  try {
    last = await post("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, default_element: $("default-el").value }) });
    last.mode = "text"; show();
  } catch (e) { showError(e.message); } finally { busy(false); }
}
async function scan() {
  showError("");
  const url = $("url").value.trim();
  if (!url) return showError("Please enter a website address.");
  busy(true);
  try {
    last = await post("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, js: $("js-always").checked ? "always" : "auto" }) });
    last.mode = "site"; $("f-issues").checked = true; show();
  } catch (e) { showError(e.message, e.hint); } finally { busy(false); }
}
async function reviewShot(file) {
  showError("");
  const f = file || shotFile;
  if (!f) return showError("Please choose a screenshot first.");
  busy(true);
  try {
    const fd = new FormData(); fd.append("image", f, f.name || "screenshot.png"); fd.append("scale", $("shot-scale").value);
    last = await post("/api/screenshot", { method: "POST", body: fd });
    last.mode = "shot"; if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = URL.createObjectURL(f); last.imageUrl = shotUrl; $("f-issues").checked = true; show();
  } catch (e) { showError(e.message); } finally { busy(false); }
}
function show() { render(); showResults(); }

// ------------------------------------------------------------------ results: verdict
function band(n) { return n >= 90 ? ["Excellent", "good"] : n >= 75 ? ["Good", "good"] : n >= 55 ? ["Needs work", "fair"] : ["Poor", "poor"]; }
function plural(n, w) { return `${n} ${w}${n === 1 ? "" : "s"}`; }

function renderVerdict() {
  const s = last.summary, pg = last.page;
  const [label, t] = band(s.overall);
  const total = s.issues.high + s.issues.medium + s.issues.low;
  const pageN = pg ? pg.page_issues.length : 0;
  const title = last.mode === "site" ? "Website review" : last.mode === "shot" ? "Screenshot review" : "Text review";
  const dims = Object.entries(CATS).map(([k, name]) => [name, s.categories[k]]);
  if (s.page_score != null) dims.push([last.mode === "shot" ? "Visual checks" : "Page checks", s.page_score]);
  const weakest = dims.slice().sort((a, b) => a[1] - b[1])[0];
  const sentence = total + pageN === 0
    ? "No problems found. Nice work."
    : `We found <b>${plural(s.issues.high, "serious problem")}</b>, ${s.issues.medium} medium and ${s.issues.low} minor issues in ${plural(s.total, "piece")} of text${pageN ? `, plus ${plural(pageN, "page-level problem")}` : ""}.`;
  $("verdict").innerHTML = `
    <div class="verdict">
      <div class="ring ${t}" style="--p:${s.overall}" role="img" aria-label="Overall score ${s.overall} out of 100"><span><b>${s.overall}</b><small>/100</small></span></div>
      <div class="v-main">
        <p class="v-kicker">${title}</p>
        <h3 class="v-label ${t}">${label}</h3>
        <p class="v-text">${sentence}</p>
        ${total + pageN ? `<p class="v-text small">Weakest area: <b>${weakest[0]}</b> (${weakest[1]}/100).</p>` : ""}
      </div>
      <ul class="v-bars" aria-label="Score by area">${dims.map(([name, v]) => `<li><span>${name}</span><div class="bar" aria-hidden="true"><i class="bg-${tone(v)}" style="width:${v}%"></i></div><b class="${tone(v)}">${v}</b></li>`).join("")}</ul>
    </div>
    <details class="legend"><summary>How is the score worked out?</summary>
      <p>Every piece of text starts at 100 and loses points for each problem: 22 for a high, 12 for a medium and 5 for a low problem. The overall score is the average${s.page_score != null ? ", blended 50/50 with the page-level checks, which also lose points the same way" : ""}. 90+ is excellent, 75–89 good, 55–74 needs work, and below 55 is poor.</p></details>`;
}

// ------------------------------------------------------------------ results: screenshot overlay
function renderShot() {
  const box = $("shot-view");
  if (last.mode !== "shot" || !last.imageUrl) { box.innerHTML = ""; return; }
  const worst = (it) => (it.issues.length ? it.issues.slice().sort((a, b) => ORDER[a.severity] - ORDER[b.severity])[0].severity : "ok");
  const boxes = last.boxes.map((b) => {
    const it = last.items[b.id - 1];
    return `<button type="button" class="box b-${worst(it)}" data-item="${b.id}" style="left:${b.x}%;top:${b.y}%;width:${b.w}%;height:${b.h}%"
      aria-label="Text ${b.id}: ${esc(cut(it.text, 50))}. ${it.issues.length} issue${it.issues.length === 1 ? "" : "s"}"></button>`;
  }).join("");
  box.innerHTML = `<div class="shot-card"><h3>Your screenshot</h3>
    <p class="hint small">Each box is a piece of text we found. <span class="key k-high"></span>serious <span class="key k-medium"></span>medium <span class="key k-low"></span>minor <span class="key k-ok"></span>no issues. Select a box to jump to its details.</p>
    <div class="shot"><img src="${last.imageUrl}" alt="The screenshot you uploaded, with boxes around the text we found">${boxes}</div></div>`;
}

// ------------------------------------------------------------------ results: page-level
function renderPage() {
  const pg = last.page, box = $("page-info");
  if (!pg) { box.innerHTML = ""; return; }
  const issues = pg.page_issues.slice().sort((x, y) => ORDER[x.severity] - ORDER[y.severity]);
  const li = issues.map((i) => `<li class="${i.severity}"><div class="li-head"><span class="sev ${i.severity}">${i.severity}</span> <strong>${esc(i.message)}</strong></div>
    ${i.detail ? `<p class="detail">${esc(i.detail)}</p>` : ""}<p class="fixline"><b>Fix:</b> ${esc(i.suggestion)}</p></li>`).join("");
  const heading = pg.screenshot ? "Visual checks" : "Page-level checks";
  box.innerHTML = `${pg.rendered ? `<div class="note"><b>Rendered with JavaScript:</b> this page was opened in a browser so text created by scripts is included.</div>` : ""}
    ${pg.warning ? `<div class="warn" role="alert"><b>Heads up:</b> ${esc(pg.warning)}</div>` : ""}
    <details class="pageinfo" open><summary><span class="sum-title">${heading}</span> <span class="count">${issues.length}</span>
      <span class="sum-sub">${esc(pg.screenshot ? "" : (pg.title || "Untitled page"))}</span></summary>
      ${pg.screenshot ? "" : `<p class="url">${esc(pg.url)}${pg.lang ? " · language: " + esc(pg.lang) : ""}</p>`}
      ${li ? `<ul>${li}</ul>` : `<p class="ok-msg">✓ No problems found</p>`}
      ${pg.truncated ? `<p class="hint small">Only the first ${last.items.length} strings were reviewed.</p>` : ""}</details>`;
}

// ------------------------------------------------------------------ results: fix first
function renderTop() {
  const flat = [];
  if (last.page) last.page.page_issues.filter((i) => i.severity === "high").forEach((i) => flat.push({ head: i.message, tag: last.page.screenshot ? "visual" : "page", i }));
  last.items.forEach((it) => it.issues.filter((i) => i.severity === "high").forEach((i) => {
    if (last.mode === "shot" && i.rule === "low-contrast") return;      // already covered by the visual-check summary
    flat.push({ head: `“${cut(it.text, 70)}”`, tag: it.element, id: it.id, i });
  }));
  const box = $("top-fixes");
  if (!flat.length) { box.innerHTML = ""; return; }
  const shown = flat.slice(0, 6);
  box.innerHTML = `<div class="topfix"><h3>Fix these first</h3><ol>${shown.map(({ head, tag, i, id }) => `<li>
    <div><strong>${esc(head)}</strong> <span class="tag">${esc(tag)}</span></div>
    <div>${esc(i.message)}</div><div class="fixline"><b>Fix:</b> ${esc(i.suggestion)}</div>
    ${id ? `<button type="button" class="linkbtn jump" data-jump="${id}">See details ↓</button>` : ""}</li>`).join("")}</ol>
    ${flat.length > 6 ? `<p class="hint small">${flat.length - 6} more serious issue${flat.length - 6 === 1 ? "" : "s"} in the list below.</p>` : ""}</div>`;
}

function render() {
  renderVerdict(); renderShot(); renderPage(); renderTop(); renderItems();
  $("to-text").hidden = last.mode !== "shot";
}

// ------------------------------------------------------------------ results: items
function renderItems() {
  const sev = $("f-sev").value, cat = $("f-cat").value, only = $("f-issues").checked, order = $("f-sort").value;
  const list_ = last.items.slice();
  if (order === "worst") list_.sort((a, b) => a.score - b.score);
  if (order === "best") list_.sort((a, b) => b.score - a.score);
  const html = list_.map((it) => {
    const issues = it.issues.filter((i) => (sev === "all" || i.severity === sev) && (cat === "all" || i.category === cat));
    if (only && !it.issues.length) return "";
    if ((sev !== "all" || cat !== "all") && !issues.length) return "";
    const counts = ["high", "medium", "low"].map((s) => [s, it.issues.filter((i) => i.severity === s).length]).filter(([, n]) => n);
    const badges = counts.length ? counts.map(([s, n]) => `<span class="cnt ${s}">${n} ${s}</span>`).join("") : `<span class="cnt ok">✓ OK</span>`;
    const list = issues.length
      ? `<ul class="issues">${issues.map((i) => `<li class="${i.severity}"><div class="li-head"><span class="sev ${i.severity}">${i.severity}</span> <span class="pill">${CATS[i.category]}</span></div>
          <div class="i-msg">${esc(i.message)}</div>${i.suggestion ? `<div class="fixline"><b>Fix:</b> ${esc(i.suggestion)}</div>` : ""}</li>`).join("")}</ul>`
      : `<p class="ok-msg">✓ No issues found</p>`;
    const fix = it.rewrite ? `<div class="rewrite"><b>Suggested rewrite</b><span>${esc(it.rewrite)}</span>
      <button type="button" class="btn btn-ghost" data-copy="${esc(it.rewrite)}">Copy</button></div>` : "";
    const read = it.reading_ease != null && it.word_count >= 6 ? ` · reading ease ${it.reading_ease} (${esc(it.reading_label)}), grade ${it.grade}` : "";
    const open = it.issues.some((i) => i.severity === "high") ? " open" : "";
    return `<details class="item" id="item-${it.id}"${open}><summary>
        <span class="s-text">${esc(cut(it.text, 110))}</span><span class="s-meta"><span class="tag">${it.element}</span>${badges}<b class="${tone(it.score)} s-score">${it.score}</b></span></summary>
      <div class="item-body"><div class="meta">${it.where ? `<span class="where">${esc(it.where)}</span> · ` : ""}${plural(it.word_count, "word")}${read}</div>${list}${fix}</div></details>`;
  }).join("");
  $("items").innerHTML = html || "<p>Nothing matches the current filters.</p>";
}

function jumpTo(id) {
  const el = $("item-" + id); if (!el) return;
  el.open = true; el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
}
document.addEventListener("click", (e) => {
  const j = e.target.closest("[data-jump]"); if (j) { $("f-sev").value = "all"; $("f-cat").value = "all"; $("f-issues").checked = false; renderItems(); jumpTo(j.dataset.jump); }
  const b = e.target.closest("[data-item]"); if (b) { $("f-sev").value = "all"; $("f-cat").value = "all"; $("f-issues").checked = false; renderItems(); jumpTo(b.dataset.item); }
  const c = e.target.closest("[data-copy]"); if (c) copy(c.dataset.copy);
});
["f-sev", "f-cat", "f-issues", "f-sort"].forEach((id) => $(id).addEventListener("change", () => last && renderItems()));
$("expand").onclick = () => document.querySelectorAll("#items details").forEach((d) => (d.open = true));
$("collapse").onclick = () => document.querySelectorAll("#items details").forEach((d) => (d.open = false));

// ------------------------------------------------------------------ inputs
$("analyze").onclick = analyze;
$("sample").onclick = () => { $("text").value = SAMPLE; $("text").focus(); updateCount(); };
$("clear").onclick = () => { $("text").value = ""; $("results").hidden = true; showError(""); updateCount(); };
$("text").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze(); });
$("scan").onclick = scan;
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") scan(); });
document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => { $("url").value = `${location.origin}/demo/${b.dataset.demo}`; scan(); }));

// screenshot input: choose, drop, paste
function setShot(file) {
  if (!file || !file.type.startsWith("image/")) return showError("That file isn’t an image.");
  if (file.size > 10 * 1024 * 1024) return showError("That image is larger than 10 MB.");
  showError(""); shotFile = file;
  const p = $("shot-preview"); p.src = URL.createObjectURL(file); p.hidden = false;
  $("shot-name").textContent = `${file.name || "Pasted screenshot"} · ${(file.size / 1024).toFixed(0)} KB`; $("shot-name").hidden = false;
  $("shot-go").disabled = false;
}
$("drop").addEventListener("click", (e) => { if (e.target.id !== "shot-file") $("shot-file").click(); });
$("drop").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("shot-file").click(); } });
$("shot-file").addEventListener("change", (e) => { if (e.target.files[0]) setShot(e.target.files[0]); });
["dragenter", "dragover"].forEach((ev) => $("drop").addEventListener(ev, (e) => { e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => $("drop").addEventListener(ev, (e) => { e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) setShot(f); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  selectTab("shot"); setShot(item.getAsFile()); $("shot-go").scrollIntoView({ block: "center" });
});
$("shot-go").onclick = () => reviewShot();
$("shot-demo").onclick = async () => {
  showError(""); busy(true);
  try {
    const r = await fetch("/demo/sample-screenshot.png"); if (!r.ok) throw new Error("Sample not available.");
    const blob = await r.blob(); const f = new File([blob], "sample-screenshot.png", { type: "image/png" });
    setShot(f); await reviewShot(f);
  } catch (e) { showError(e.message); } finally { busy(false); }
};
$("to-text").onclick = () => {
  const el = { heading: "label", other: "other" };
  $("text").value = last.items.map((i) => `${el[i.element] || i.element} | ${i.text}`).join("\n");
  selectTab("text"); updateCount(); $("text").focus(); $("analyzer").scrollIntoView({ behavior: "smooth" });
  toast("Edit the text if OCR made mistakes, then press Analyze text");
};

// ------------------------------------------------------------------ exports & helpers
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 2400);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); }
  catch { const a = document.createElement("textarea"); a.value = text; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); toast("Copied to clipboard"); }
}
$("copy-fixes").onclick = () => {
  if (!last) return;
  const lines = last.items.filter((i) => i.rewrite).map((i) => `${i.text}  ->  ${i.rewrite}`);
  lines.length ? copy(lines.join("\n")) : toast("No automatic rewrites available");
};
const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
function download(name, blob) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); URL.revokeObjectURL(a.href); }
$("export-csv").onclick = () => {
  if (!last) return;
  const head = ["#", "Type", "Found in", "Text", "Score", "Clarity", "Accessibility", "Reading", "Consistency", "Reading ease", "Grade", "Issues", "Suggested rewrite"];
  const rows = last.items.map((i) => [i.id, i.element, i.where, i.text, i.score, i.scores.clarity, i.scores.accessibility, i.scores.reading,
    i.scores.consistency, i.reading_ease, i.grade, i.issues.map((x) => `[${x.severity}] ${x.message}`).join(" | "), i.rewrite]);
  download("ui-text-review.csv", new Blob(["﻿" + [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n")], { type: "text/csv" }));
};
$("export").onclick = () => { if (last) { const { imageUrl, ...data } = last; download("ui-text-review.json", new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })); } };
$("print").onclick = () => { document.querySelectorAll("#items details").forEach((d) => (d.open = true)); window.print(); };
$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (f.size > 500000) { showError("File is too large (max 500 KB)."); return; }
  let text = await f.text();
  if (f.name.toLowerCase().endsWith(".csv")) {          // one string per row; keep first column, or "type,text" pairs
    text = text.replace(/^﻿/, "").split(/\r?\n/).map((l) => {
      const c = l.split(",").map((x) => x.trim().replace(/^"|"$/g, ""));
      return /^(button|label|message|other)$/i.test(c[0]) && c[1] ? `${c[0]} | ${c.slice(1).join(", ")}` : c[0];
    }).filter((l) => l && !/^(text|string|type)$/i.test(l)).join("\n");
  }
  $("text").value = text; showError(""); updateCount(); toast(`Loaded ${f.name}`); e.target.value = "";
});
function updateCount() {
  const n = $("text").value.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  $("line-count").textContent = `${n} string${n === 1 ? "" : "s"}`;
}
$("text").addEventListener("input", updateCount);
updateCount();

// ---- text size control (remembered between visits)
const SIZES = [100, 115, 130, 150];
let sizeIdx = 0;
try { sizeIdx = Math.min(SIZES.length - 1, Math.max(0, parseInt(localStorage.getItem("uitr-size") || "0", 10) || 0)); } catch (e) {}
function applySize() {
  document.documentElement.style.fontSize = SIZES[sizeIdx] + "%";
  $("size-down").disabled = sizeIdx === 0; $("size-up").disabled = sizeIdx === SIZES.length - 1;
  try { localStorage.setItem("uitr-size", sizeIdx); } catch (e) {}
}
$("size-down").onclick = () => { sizeIdx = Math.max(0, sizeIdx - 1); applySize(); };
$("size-up").onclick = () => { sizeIdx = Math.min(SIZES.length - 1, sizeIdx + 1); applySize(); };
applySize();
