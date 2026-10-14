const $ = (id) => document.getElementById(id);
const SAMPLE = `# type | text
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
message | Something went wrong!!
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
    last = data; render();
    const res = $("results"); res.hidden = false; res.focus(); res.scrollIntoView({ behavior: "smooth" });
  } catch (e) { showError(e.message); }
  finally { $("analyze").disabled = false; }
}

function render() {
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
  const html = last.items.map((it) => {
    const issues = it.issues.filter((i) => (sev === "all" || i.severity === sev) && (cat === "all" || i.category === cat));
    if (only && !it.issues.length) return "";
    if ((sev !== "all" || cat !== "all") && !issues.length) return "";
    const list = issues.length
      ? `<ul class="issues">${issues.map((i) => `<li class="${i.severity}"><span class="sev ${i.severity}">${i.severity}</span>
          <span class="pill">${CATS[i.category]}</span> — ${esc(i.message)}${i.suggestion ? `<span class="fix">Suggestion: ${esc(i.suggestion)}</span>` : ""}</li>`).join("")}</ul>`
      : `<p class="ok-msg">✓ No issues found</p>`;
    const read = it.reading_ease != null ? `Reading ease ${it.reading_ease} (${esc(it.reading_label)}) · grade ${it.grade}` : "";
    return `<article class="item"><div class="item-head"><span class="text">${esc(it.text)}</span>
      <span><span class="tag">${it.element}</span> <b class="${tone(it.score)}">${it.score}/100</b></span></div>
      <div class="meta">${it.word_count} word${it.word_count === 1 ? "" : "s"} · ${read}</div>${list}</article>`;
  }).join("");
  $("items").innerHTML = html || "<p>No strings match the current filters.</p>";
}

$("analyze").onclick = analyze;
$("sample").onclick = () => { $("text").value = SAMPLE; $("text").focus(); };
$("clear").onclick = () => { $("text").value = ""; $("results").hidden = true; showError(""); };
["f-sev", "f-cat", "f-issues"].forEach((id) => $(id).addEventListener("change", () => last && renderItems()));
$("text").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze(); });
$("export").onclick = () => {
  if (!last) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 2)], { type: "application/json" }));
  a.download = "ui-text-review.json"; a.click(); URL.revokeObjectURL(a.href);
};
