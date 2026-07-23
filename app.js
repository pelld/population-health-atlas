// ============================================================
// 00. DEMONSTRATION DATA
// Values are fabricated and exist only to test the interface.
// ============================================================
const conditions = ["Diabetes", "Depression", "Hypertension", "COPD", "CHD", "Atrial fibrillation", "CKD", "Asthma"];
const factors = { Diabetes: 1, Depression: 1.18, Hypertension: 1.55, COPD: 0.42, CHD: 0.36, "Atrial fibrillation": 0.24, CKD: 0.48, Asthma: 0.75 };
const pairs = [["Diabetes","Hypertension",0.74],["CHD","Atrial fibrillation",0.67],["COPD","Depression",0.61],["Diabetes","CHD",0.56],["Hypertension","CKD",0.51]];
let state = { condition:"Diabetes", pair:"Depression", mode:"recorded", selected:"E12000002" };

// ============================================================
// 01. START-UP
// ============================================================
const el = id => document.getElementById(id);
conditions.forEach(condition => el("conditionSelect").add(new Option(condition, condition)));
["None", ...conditions.filter(condition => condition !== state.condition)].forEach(condition => el("pairSelect").add(new Option(condition, condition)));
el("pairSelect").value = state.pair;
el("pairRanking").innerHTML = pairs.map(([a,b,score], i) => `<li><span class="rank">${i+1}</span><div><p>${a} + ${b}</p><div class="bar"><i style="width:${score*100}%"></i></div></div><strong>${score.toFixed(2)}</strong></li>`).join("");

// ============================================================
// 02. MAP CALCULATIONS AND RENDERING
// ============================================================
function values() { return regions.map(region => ({ ...region, value: state.mode === "recorded" ? region.base * factors[state.condition] : (region.base * factors[state.condition] - 8.8 * factors[state.condition]) - region.imd })); }
function colour(value, extent) {
  if (state.mode === "adjusted") { const strength = Math.min(Math.abs(value) / Math.max(extent, 0.1), 1); return value >= 0 ? `color-mix(in srgb, #137d78 ${35 + strength * 60}%, #e7f2ef)` : `color-mix(in srgb, #c9785d ${35 + strength * 55}%, #f4ece7)`; }
  return `color-mix(in srgb, #087f78 ${28 + Math.min(value / Math.max(extent, 0.1), 1) * 70}%, #e3f0ed)`;
}
function render() {
  const data = values(), national = data.reduce((sum, region) => sum + region.value, 0) / data.length, selected = data.find(region => region.id === state.selected), extent = state.mode === "recorded" ? Math.max(...data.map(region => region.value)) : Math.max(...data.map(region => Math.abs(region.value)));
  el("selectionLabel").textContent = `${state.condition}${state.pair === "None" ? "" : ` + ${state.pair}`}`;
  el("viewTitle").textContent = state.mode === "recorded" ? "Recorded prevalence" : "Difference after deprivation adjustment";
  el("legendTitle").textContent = state.mode === "recorded" ? "Prevalence (%)" : "Residual (pp)";
  el("legendLow").textContent = state.mode === "recorded" ? "Lower" : "Lower than expected"; el("legendHigh").textContent = state.mode === "recorded" ? "Higher" : "Higher than expected";
  el("legendRamp").className = `legend-ramp ${state.mode}`; el("nationalValue").textContent = `${national.toFixed(1)}${state.mode === "recorded" ? "%" : "pp"}`;
  el("areaName").textContent = selected.name; el("areaValue").textContent = `${selected.value.toFixed(1)}${state.mode === "recorded" ? "%" : " pp"}`;
  el("areaComparison").textContent = state.mode === "recorded" ? `${(selected.value-national).toFixed(1)} pp from England average` : selected.value >= 0 ? "higher than deprivation predicts" : "lower than deprivation predicts";
  el("definitionText").textContent = state.mode === "recorded" ? "Recorded prevalence is the proportion of patients on the relevant QOF register." : "Adjusted values show the difference remaining after accounting for deprivation in the demonstration model.";
  el("englandMap").innerHTML = data.map(region => `<path data-id="${region.id}" d="${region.path}" fill="${colour(region.value, extent)}" class="${region.id === state.selected ? "selected-region" : ""}" tabindex="0" aria-label="${region.name}: ${region.value.toFixed(1)}"></path>`).join("");
  el("englandMap").querySelectorAll("path").forEach(path => { path.addEventListener("click", () => { state.selected = path.dataset.id; render(); }); path.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { state.selected = path.dataset.id; render(); } }); });
}

// ============================================================
// 03. CONTROLS
// ============================================================
el("conditionSelect").addEventListener("change", event => { state.condition = event.target.value; state.pair = state.pair === state.condition ? "None" : state.pair; render(); });
el("pairSelect").addEventListener("change", event => { state.pair = event.target.value; render(); });
el("recordedButton").addEventListener("click", () => setMode("recorded")); el("adjustedButton").addEventListener("click", () => setMode("adjusted"));
function setMode(mode) { state.mode = mode; el("recordedButton").classList.toggle("active", mode === "recorded"); el("adjustedButton").classList.toggle("active", mode === "adjusted"); render(); }
el("areaSearch").addEventListener("input", event => {
  const query = event.target.value.toLowerCase(), matches = query ? regions.filter(region => region.name.toLowerCase().includes(query)) : [];
  el("searchResults").hidden = !query; el("searchResults").innerHTML = matches.length ? matches.map(region => `<button data-id="${region.id}">${region.name}</button>`).join("") : "<p>No matching region</p>";
  el("searchResults").querySelectorAll("button").forEach(button => button.addEventListener("click", () => { state.selected = button.dataset.id; el("areaSearch").value = ""; el("searchResults").hidden = true; render(); }));
});
el("downloadButton").addEventListener("click", () => {
  const csv = ["area,condition,view,value", ...values().map(region => `"${region.name}","${state.condition}","${state.mode}",${region.value.toFixed(2)}`)].join("\n"), url = URL.createObjectURL(new Blob([csv], { type:"text/csv" })), link = document.createElement("a");
  link.href = url; link.download = "population-health-atlas-demo.csv"; link.click(); URL.revokeObjectURL(url);
});
el("aboutButton").addEventListener("click", () => el("modalBackdrop").hidden = false); el("closeModal").addEventListener("click", () => el("modalBackdrop").hidden = true); el("modalBackdrop").addEventListener("click", event => { if (event.target === el("modalBackdrop")) el("modalBackdrop").hidden = true; });
render();
