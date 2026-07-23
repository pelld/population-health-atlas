// ============================================================
// 00. DATA AND APPLICATION STATE
// ============================================================
const atlasData = window.ATLAS_DATA || null, practiceData = window.PRACTICE_DATA || null, mapAreas = window.ICB_BOUNDARIES || regions;
const conditions = atlasData?.conditions || practiceData?.conditions || ["Diabetes", "Depression", "Hypertension", "COPD"];
const firstCondition = conditions.find(condition => condition === "Diabetes") || conditions[0];
const firstArea = mapAreas.find(area => atlasData?.areas[area.id])?.id || mapAreas[0].id;
const allPractices = practiceData ? Object.entries(practiceData.practices).map(([id, practice]) => ({ id, ...practice })) : [];
let state = { geography:"icb", condition:firstCondition, pair:"None", mode:"recorded", selected:firstArea, selectedPractice:allPractices.find(practice => practice.icb === firstArea)?.id || allPractices[0]?.id };
const el = id => document.getElementById(id);

// ============================================================
// 01. START-UP
// ============================================================
conditions.forEach(condition => el("conditionSelect").add(new Option(condition, condition)));
el("conditionSelect").value = state.condition;
["None", ...conditions.filter(condition => condition !== state.condition)].forEach(condition => el("pairSelect").add(new Option(condition, condition)));
if (!practiceData) el("geographySelect").querySelector('[value="practice"]').disabled = true;
el("dataStatus").textContent = atlasData ? "Official data" : "Demonstration version";
el("dataStatusText").textContent = practiceData ? `QOF ${practiceData.year}; practice adjustment uses registered-patient age mix and patient-weighted IMD ${practiceData.deprivationYear}.` : `QOF ${atlasData?.year || ""}, adjusted using the English Indices of Deprivation ${atlasData?.deprivationYear || ""}.`;
el("methodStatus").textContent = practiceData ? `${practiceData.method} Patient-to-LSOA mapping coverage is shown for each selected practice.` : "The site uses a reproducible static-data pipeline.";

// ============================================================
// 02. VALUES, COLOURS AND MAP PROJECTION
// ============================================================
function values() {
  if (state.geography === "practice") {
    const field = state.mode === "recorded" ? "prevalence" : "adjusted";
    return allPractices.filter(practice => practice.icb === state.selected && practice[field]?.[state.condition] != null).map(practice => ({ ...practice, value:practice[field][state.condition] }));
  }
  const field = state.mode === "recorded" ? "prevalence" : "residual";
  return mapAreas.filter(area => atlasData?.areas[area.id]?.[field]?.[state.condition] != null).map(area => ({ ...area, ...atlasData.areas[area.id], value:atlasData.areas[area.id][field][state.condition] }));
}
function colour(value, extent) {
  if (state.mode === "adjusted") { const strength = Math.min(Math.abs(value) / Math.max(extent, .1), 1); return value >= 0 ? `color-mix(in srgb, #137d78 ${35 + strength * 60}%, #e7f2ef)` : `color-mix(in srgb, #c9785d ${35 + strength * 55}%, #f4ece7)`; }
  return `color-mix(in srgb, #087f78 ${28 + Math.min(value / Math.max(extent, .1), 1) * 70}%, #e3f0ed)`;
}
function project(longitude, latitude) {
  const scale = 87.76095667010043;
  return { x:35 + (longitude + 6.3779223375234) * Math.cos(53 * Math.PI / 180) * scale, y:25 + (55.8110880161144 - latitude) * scale };
}

// ============================================================
// 03. RENDERING
// ============================================================
function renderRanking() {
  const ranked = state.geography === "practice" ? practiceData?.pairs || [] : atlasData?.pairs || [];
  el("pairRanking").innerHTML = ranked.slice(0, 5).map((pair, index) => `<li><span class="rank">${index + 1}</span><div><p>${pair.first} + ${pair.second}</p><div class="bar"><i style="width:${Math.max(0, pair.correlation) * 100}%"></i></div></div><strong>${pair.correlation.toFixed(2)}</strong></li>`).join("");
  if (ranked.length) { el("keyPair").textContent = `${ranked[0].first} and ${ranked[0].second}`; el("keyPairText").textContent = `Correlation ${ranked[0].correlation.toFixed(2)} after ${state.geography === "practice" ? "age and deprivation" : "deprivation"} adjustment.`; }
}
function renderMap(data, extent) {
  const boundaries = mapAreas.map(area => `<path data-id="${area.id}" d="${area.path}" fill="${state.geography === "icb" ? colour(data.find(item => item.id === area.id)?.value || 0, extent) : "#dce8e5"}" class="${area.id === state.selected ? "selected-region" : ""}" tabindex="0"></path>`).join("");
  const circles = state.geography === "practice" ? data.map(practice => { const point = project(practice.longitude, practice.latitude), radius = Math.max(2.4, Math.min(6, Math.sqrt(practice.listSize) / 25)); return `<circle data-id="${practice.id}" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${radius.toFixed(1)}" fill="${colour(practice.value, extent)}" class="${practice.id === state.selectedPractice ? "selected-practice" : ""}" tabindex="0"><title>${practice.name}: ${practice.value.toFixed(1)}</title></circle>`; }).join("") : "";
  el("englandMap").innerHTML = boundaries + circles;
  el("englandMap").querySelectorAll("path").forEach(path => path.addEventListener("click", () => { state.selected = path.dataset.id; state.selectedPractice = allPractices.find(practice => practice.icb === state.selected)?.id; render(); }));
  el("englandMap").querySelectorAll("circle").forEach(circle => circle.addEventListener("click", () => { state.selectedPractice = circle.dataset.id; render(); }));
}
function render() {
  const data = values(), selected = state.geography === "practice" ? data.find(item => item.id === state.selectedPractice) || data[0] : data.find(item => item.id === state.selected) || data[0];
  if (!selected || !data.length) return;
  if (state.geography === "practice") state.selectedPractice = selected.id;
  const average = data.reduce((sum, item) => sum + item.value, 0) / data.length, extent = state.mode === "recorded" ? Math.max(...data.map(item => item.value)) : Math.max(...data.map(item => Math.abs(item.value)));
  el("selectionLabel").textContent = state.condition;
  el("viewTitle").textContent = state.mode === "recorded" ? "Recorded prevalence" : state.geography === "practice" ? "Difference after age and deprivation adjustment" : "Difference after deprivation adjustment";
  el("legendTitle").textContent = state.mode === "recorded" ? "Prevalence (%)" : "Residual (pp)";
  el("legendLow").textContent = state.mode === "recorded" ? "Lower" : "Lower than expected"; el("legendHigh").textContent = state.mode === "recorded" ? "Higher" : "Higher than expected";
  el("legendRamp").className = `legend-ramp ${state.mode}`; el("nationalValue").textContent = `${average.toFixed(1)}${state.mode === "recorded" ? "%" : "pp"}`;
  el("geographyLabel").textContent = state.geography === "practice" ? `${selected.icbName} practices` : atlasData.geography;
  el("areaName").textContent = selected.name; el("areaValue").textContent = `${selected.value.toFixed(1)}${state.mode === "recorded" ? "%" : " pp"}`;
  el("areaComparison").textContent = state.mode === "recorded" ? `${(selected.value - average).toFixed(1)} pp from displayed average` : `${selected.value >= 0 ? "higher" : "lower"} than the model predicts${state.geography === "practice" ? ` · IMD coverage ${selected.imdCoverage}%` : ""}`;
  el("definitionText").textContent = state.mode === "recorded" ? "Recorded prevalence is the proportion of the relevant QOF denominator on the condition register." : state.geography === "practice" ? "Model-adjusted values account for patient-weighted deprivation and registered-population age mix. They are not formal age-standardised rates." : "ICB residuals account for deprivation only.";
  renderMap(data, extent); renderRanking();
}

// ============================================================
// 04. CONTROLS AND SEARCH
// ============================================================
el("geographySelect").addEventListener("change", event => { state.geography = event.target.value; el("searchLabel").firstChild.textContent = state.geography === "practice" ? "Search practice" : "Search area"; el("areaSearch").placeholder = state.geography === "practice" ? "Name, code or postcode…" : "Start typing an ICB…"; render(); });
el("conditionSelect").addEventListener("change", event => { state.condition = event.target.value; render(); });
el("pairSelect").addEventListener("change", event => { state.pair = event.target.value; render(); });
el("recordedButton").addEventListener("click", () => setMode("recorded")); el("adjustedButton").addEventListener("click", () => setMode("adjusted"));
function setMode(mode) { state.mode = mode; el("recordedButton").classList.toggle("active", mode === "recorded"); el("adjustedButton").classList.toggle("active", mode === "adjusted"); render(); }
el("areaSearch").addEventListener("input", event => {
  const query = event.target.value.trim().toLowerCase();
  const matches = !query ? [] : state.geography === "practice" ? allPractices.filter(practice => `${practice.name} ${practice.id} ${practice.postcode}`.toLowerCase().includes(query)).slice(0, 12) : mapAreas.filter(area => area.name.toLowerCase().includes(query) && atlasData.areas[area.id]);
  el("searchResults").hidden = !query; el("searchResults").innerHTML = matches.length ? matches.map(item => `<button data-id="${item.id}">${item.name}${state.geography === "practice" ? ` · ${item.postcode}` : ""}</button>`).join("") : "<p>No match</p>";
  el("searchResults").querySelectorAll("button").forEach(button => button.addEventListener("click", () => { if (state.geography === "practice") { const practice = practiceData.practices[button.dataset.id]; state.selectedPractice = button.dataset.id; state.selected = practice.icb; } else state.selected = button.dataset.id; el("areaSearch").value = ""; el("searchResults").hidden = true; render(); }));
});
el("downloadButton").addEventListener("click", () => { const csv = ["code,name,condition,view,value", ...values().map(item => `"${item.id}","${item.name}","${state.condition}","${state.mode}",${item.value.toFixed(2)}`)].join("\n"), url = URL.createObjectURL(new Blob([csv], { type:"text/csv" })), link = document.createElement("a"); link.href = url; link.download = `population-health-${state.geography}.csv`; link.click(); URL.revokeObjectURL(url); });
el("aboutButton").addEventListener("click", () => el("modalBackdrop").hidden = false); el("closeModal").addEventListener("click", () => el("modalBackdrop").hidden = true); el("modalBackdrop").addEventListener("click", event => { if (event.target === el("modalBackdrop")) el("modalBackdrop").hidden = true; });
render();
