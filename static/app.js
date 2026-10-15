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

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tone = (n) => (n >= 80 ? "good" : n >= 60 ? "fair" : "poor");
const CATS = { clarity: "Clarity", accessibility: "Accessibility", reading: "Reading level", consistency: "Consistency" };

function showError(msg) { const e = $("error"); e.textContent = msg || ""; e.hidden = !msg; }

async function analyze() {
  showError("");
  const text = $("text").value;
  if (!text.trim()) return showError("Please enter at least one UI string.");
  $("analyze").disabled = true;
  try {
    const r = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, default_element: $("default-el").value }) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Analysis failed.");
    last = data; last.page = null; render();
    const res = $("results"); res.hidden = false; res.focus(); res.scrollIntoView({ behavior: "smooth" });
  } catch (e) { showError(e.message); }
  finally { $("analyze").disabled = false; }
}

function renderPage() {
  const pg = last.page, box = $("page-info");
  if (!pg) { box.innerHTML = ""; return; }
  const order = { high: 0, medium: 1, low: 2 };
  const issues = pg.page_issues.slice().sort((x, y) => order[x.severity] - order[y.severity]);
  const li = issues.map((i) => `<li class="${i.severity}"><div class="li-head"><span class="sev ${i.severity}">${i.severity}</span> <strong>${esc(i.message)}</strong></div>
    ${i.detail ? `<p class="detail">${esc(i.detail)}</p>` : ""}<p class="fixline"><b>Fix:</b> ${esc(i.suggestion)}</p></li>`).join("");
  box.innerHTML = `${pg.warning ? `<div class="warn" role="alert"><b>Heads up:</b> ${esc(pg.warning)}</div>` : ""}
    <div class="pageinfo"><h3>${esc(pg.title || "Untitled page")}</h3><p class="url">${esc(pg.url)}${pg.lang ? " · language: " + esc(pg.lang) : ""}</p>
    <h4>Page-level checks <span class="count">${issues.length}</span></h4>${li ? `<ul>${li}</ul>` : `<p class="ok-msg">✓ No page-level problems found</p>`}
    ${pg.truncated ? `<p class="hint small">Only the first ${last.items.length} strings were reviewed.</p>` : ""}</div>`;
}

function renderTop() {
  const flat = [];
  last.items.forEach((it) => it.issues.filter((i) => i.severity === "high").forEach((i) => flat.push({ it, i })));
  const box = $("top-fixes");
  if (!flat.length) { box.innerHTML = ""; return; }
  const shown = flat.slice(0, 5);
  box.innerHTML = `<div class="topfix"><h3>Top things to fix first</h3><ol>${shown.map(({ it, i }) => `<li><strong>“${esc(it.text.length > 70 ? it.text.slice(0, 70) + "…" : it.text)}”</strong>
    <span class="tag">${it.element}</span><br>${esc(i.message)}<br><span class="fixline"><b>Fix:</b> ${esc(i.suggestion)}</span></li>`).join("")}</ol>
    ${flat.length > 5 ? `<p class="hint small">${flat.length - 5} more high-severity issue${flat.length - 5 === 1 ? "" : "s"} in the full list below.</p>` : ""}</div>`;
}

function render() {
  renderPage();
  renderTop();
  const s = last.summary;
  const cats = Object.entries(CATS).map(([k, label]) => `
    <div class="stat"><span>${label}</span><b class="${tone(s.categories[k])}">${s.categories[k]}</b>
    <div class="bar" aria-hidden="true"><i class="bg-${tone(s.categories[k])}" style="width:${s.categories[k]}%"></i></div></div>`).join("");
  $("summary").innerHTML = `
    <div class="grid">
      <div class="stat"><span>Overall score</span><b class="${tone(s.overall)}">${s.overall}/100</b></div>
      <div class="stat"><span>Strings checked</span><b>${s.total}</b><span>${s.passing} with no issues</span></div>
      <div class="stat"><span>Issues found</span><b>${s.issues.high + s.issues.medium + s.issues.low}</b>
        <span>${s.issues.high} high · ${s.issues.medium} medium · ${s.issues.low} low</span></div>
      <div class="stat"><span>Avg reading grade</span><b>${s.avg_grade ?? "—"}</b><span>${s.avg_ease != null ? "ease " + s.avg_ease : "needs 6+ word strings"}</span></div>
    </div>
    <h3>Score by dimension</h3><div class="grid">${cats}</div>`;
  renderItems();
}

function renderItems() {
  const sev = $("f-sev").value, cat = $("f-cat").value, only = $("f-issues").checked;
  const order = $("f-sort").value;
  const list_ = last.items.slice();
  if (order === "worst") list_.sort((a, b) => a.score - b.score);
  if (order === "best") list_.sort((a, b) => b.score - a.score);
  const html = list_.map((it) => {
    const issues = it.issues.filter((i) => (sev === "all" || i.severity === sev) && (cat === "all" || i.category === cat));
    if (only && !it.issues.length) return "";
    if ((sev !== "all" || cat !== "all") && !issues.length) return "";
    const list = issues.length
      ? `<ul class="issues">${issues.map((i) => `<li class="${i.severity}"><span class="sev ${i.severity}">${i.severity}</span>
          <span class="pill">${CATS[i.category]}</span> — ${esc(i.message)}${i.suggestion ? `<span class="fix">Suggestion: ${esc(i.suggestion)}</span>` : ""}</li>`).join("")}</ul>`
      : `<p class="ok-msg">✓ No issues found</p>`;
    const fix = it.rewrite ? `<div class="rewrite"><b>Suggested rewrite</b><span>${esc(it.rewrite)}</span>
      <button type="button" class="btn btn-ghost" data-copy="${esc(it.rewrite)}">Copy</button></div>` : "";
    const read = it.reading_ease != null && it.word_count >= 6 ? `Reading ease ${it.reading_ease} (${esc(it.reading_label)}) · grade ${it.grade}` : "";
    return `<article class="item"><div class="item-head"><span class="text">${esc(it.text)}</span>
      <span><span class="tag">${it.element}</span> <b class="${tone(it.score)}">${it.score}/100</b></span></div>
      <div class="meta">${it.where ? `<span class="where">${esc(it.where)}</span> · ` : ""}${it.word_count} word${it.word_count === 1 ? "" : "s"}${read ? " · " + read : ""}</div>${list}${fix}</article>`;
  }).join("");
  $("items").innerHTML = html || "<p>No strings match the current filters.</p>";
}

$("analyze").onclick = analyze;
$("sample").onclick = () => { $("text").value = SAMPLE; $("text").focus(); };
$("clear").onclick = () => { $("text").value = ""; $("results").hidden = true; showError(""); };
["f-sev", "f-cat", "f-issues", "f-sort"].forEach((id) => $(id).addEventListener("change", () => last && renderItems()));
$("text").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze(); });
$("export").onclick = () => {
  if (!last) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 2)], { type: "application/json" }));
  a.download = "ui-text-review.json"; a.click(); URL.revokeObjectURL(a.href);
};

// ---- extras: toast, copy, CSV, upload, print, line counter
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 1800);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); }
  catch { const a = document.createElement("textarea"); a.value = text; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); toast("Copied to clipboard"); }
}
$("items").addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) copy(b.dataset.copy); });
$("copy-fixes").onclick = () => {
  if (!last) return;
  const lines = last.items.filter((i) => i.rewrite).map((i) => `${i.text}  ->  ${i.rewrite}`);
  lines.length ? copy(lines.join("\n")) : toast("No automatic rewrites available");
};
const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
$("export-csv").onclick = () => {
  if (!last) return;
  const head = ["#", "Type", "Found in", "Text", "Score", "Clarity", "Accessibility", "Reading", "Consistency", "Reading ease", "Grade", "Issues", "Suggested rewrite"];
  const rows = last.items.map((i) => [i.id, i.element, i.where, i.text, i.score, i.scores.clarity, i.scores.accessibility, i.scores.reading,
    i.scores.consistency, i.reading_ease, i.grade, i.issues.map((x) => `[${x.severity}] ${x.message}`).join(" | "), i.rewrite]);
  const csv = "\ufeff" + [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "ui-text-review.csv"; a.click(); URL.revokeObjectURL(a.href);
};
$("print").onclick = () => window.print();
$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (f.size > 500000) { showError("File is too large (max 500 KB)."); return; }
  let text = await f.text();
  if (f.name.toLowerCase().endsWith(".csv")) {          // one string per row; keep first column, or "type,text" pairs
    text = text.replace(/^\ufeff/, "").split(/\r?\n/).map((l) => {
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
$("sample").addEventListener("click", updateCount);
$("clear").addEventListener("click", updateCount);
updateCount();

// ---- website scan + tabs
function selectTab(which) {
  const url = which === "url";
  $("tab-url").setAttribute("aria-selected", url); $("tab-text").setAttribute("aria-selected", !url);
  $("tab-url").tabIndex = url ? 0 : -1; $("tab-text").tabIndex = url ? -1 : 0;
  $("panel-url").hidden = !url; $("panel-text").hidden = url; showError("");
}
$("tab-url").onclick = () => selectTab("url");
$("tab-text").onclick = () => selectTab("text");
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") { const t = $("tab-url").getAttribute("aria-selected") === "true" ? "text" : "url"; selectTab(t); $("tab-" + t).focus(); }
});
async function scan() {
  showError("");
  const url = $("url").value.trim();
  if (!url) return showError("Please enter a website address.");
  $("scan").disabled = true; $("busy").hidden = false;
  try {
    const r = await fetch("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Scan failed.");
    last = data; $("f-issues").checked = true; render();
    const res = $("results"); res.hidden = false; res.focus(); res.scrollIntoView({ behavior: "smooth" });
  } catch (e) { showError(e.message); }
  finally { $("scan").disabled = false; $("busy").hidden = true; }
}
$("scan").onclick = scan;
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") scan(); });

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
