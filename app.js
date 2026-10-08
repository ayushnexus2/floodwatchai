const $ = (id) => document.getElementById(id);

const REFRESH_MS = 10 * 60 * 1000;
const STORE_KEY = "floodwatch.place";

let current = null;
let timer = null;
let lastAlertKey = "";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(message, isError = false) {
  const s = $("status");
  s.textContent = message;
  s.className = isError ? "status error" : "status";
}

async function api(path, params) {
  const res = await fetch(`/api${path}?${new URLSearchParams(params)}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

/* ---------- search and location ---------- */

async function search() {
  const q = $("q").value.trim();
  if (q.length < 2) return setStatus("Type at least 2 letters.", true);
  setStatus("Searching...");
  try {
    const data = await api("/geocode", { q });
    renderSuggestions(data.results);
  } catch (err) {
    setStatus(err.message, true);
  }
}

function renderSuggestions(list) {
  const ul = $("suggestions");
  ul.replaceChildren();
  if (!list.length) return setStatus("No place found. Try another name.");
  setStatus("");
  list.forEach((p) => {
    const label = [p.name, p.admin1, p.country].filter(Boolean).join(", ");
    const li = el("li");
    const btn = el("button", "", label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      ul.replaceChildren();
      loadRisk(p.latitude, p.longitude, label);
    });
    li.append(btn);
    ul.append(li);
  });
}

function useMyLocation() {
  if (!navigator.geolocation) return setStatus("Location is not supported here.", true);
  setStatus("Getting your location...");
  navigator.geolocation.getCurrentPosition(
    (pos) => loadRisk(pos.coords.latitude, pos.coords.longitude, "Your location"),
    () => setStatus("Could not get location. Search for your area instead.", true),
    { timeout: 10000 }
  );
}

/* ---------- load and render ---------- */

async function loadRisk(lat, lon, name) {
  setStatus("Loading live forecast...");
  try {
    const data = await api("/risk", { lat, lon });
    current = { lat, lon, name };
    try { localStorage.setItem(STORE_KEY, JSON.stringify(current)); } catch (e) { /* storage blocked */ }
    render(data, name);
    maybeNotify(data, name);
    setStatus("");
    clearInterval(timer);
    timer = setInterval(() => loadRisk(lat, lon, name), REFRESH_MS);
  } catch (err) {
    setStatus(err.message, true);
  }
}

function render(data, name) {
  $("results").classList.remove("hidden");

  const alertBox = $("alertBox");
  alertBox.dataset.level = data.alert.level;
  const titles = { none: "No alert", watch: "Flood WATCH", warning: "Flood WARNING" };
  $("alertTitle").textContent = titles[data.alert.level];
  $("alertMsg").textContent = data.alert.message;

  $("place").textContent = name;
  $("meta").textContent =
    data.elevation_m != null ? `Elevation about ${Math.round(data.elevation_m)} m` : "";
  $("score").textContent = data.score;
  $("level").textContent = data.level;
  $("gauge").dataset.level = data.level;

  renderChart(data.hourly);
  renderStats(data.stats);
  renderFactors(data.factors);

  const advice = $("advice");
  advice.replaceChildren(...data.advice.map((t) => el("li", "", t)));

  $("updated").textContent = `Updated ${new Date(data.updated).toLocaleTimeString()}`;
}

function renderChart(hourly) {
  const chart = $("chart");
  const labels = $("chartLabels");
  chart.replaceChildren();
  labels.replaceChildren();
  const scale = Math.max(10, ...hourly.map((h) => h.mm));
  hourly.forEach((h, i) => {
    const bar = el("div", "bar");
    bar.style.height = `${(h.mm / scale) * 100}%`;
    if (h.mm >= 15) bar.classList.add("heavy");
    else if (h.mm >= 7.5) bar.classList.add("mid");
    bar.title = `${h.time.slice(11, 16)}: ${h.mm} mm`;
    chart.append(bar);
    labels.append(el("span", "", i % 4 === 0 ? h.time.slice(11, 13) : ""));
  });
}

function renderStats(s) {
  const rows = [
    ["Rain next 6 h", `${s.next6_mm} mm`],
    ["Rain next 24 h", `${s.next24_mm} mm`],
    ["Peak rate", `${s.peak_mm_h} mm/h (in ${s.peak_in_hours} h)`],
    ["Rain last 48 h", `${s.past48_mm} mm`],
    ["Chance of rain", `${s.rain_probability}%`],
    ["Soil moisture", `${s.soil_moisture} m³/m³`],
    ["River vs normal", s.river_ratio != null ? `${s.river_ratio}x` : "no data"],
  ];
  const dl = $("stats");
  dl.replaceChildren();
  rows.forEach(([k, v]) => {
    dl.append(el("dt", "", k), el("dd", "", v));
  });
}

function renderFactors(factors) {
  const ul = $("factors");
  ul.replaceChildren();
  factors.forEach((f) => {
    const li = el("li", "", `${f.name}: ${f.points} / ${f.max}`);
    const track = el("div", "track");
    const fill = el("div", "fill");
    fill.style.width = `${(f.points / f.max) * 100}%`;
    track.append(fill);
    li.append(track);
    ul.append(li);
  });
}

/* ---------- browser alerts ---------- */

function maybeNotify(data, name) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (data.alert.level === "none") return;
  const key = `${name}|${data.alert.level}`;
  if (key === lastAlertKey) return;
  lastAlertKey = key;
  new Notification(`Flood ${data.alert.level} - ${name}`, { body: data.alert.message });
}

async function enableAlerts() {
  if (!("Notification" in window)) return setStatus("Browser alerts are not supported.", true);
  const perm = await Notification.requestPermission();
  $("notifyBtn").textContent =
    perm === "granted" ? "Browser alerts on (keep this tab open)" : "Alerts blocked in browser";
}

/* ---------- start ---------- */

$("searchBtn").addEventListener("click", search);
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
$("locBtn").addEventListener("click", useMyLocation);
$("notifyBtn").addEventListener("click", enableAlerts);

try {
  const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
  if (saved && typeof saved.lat === "number" && typeof saved.lon === "number") {
    loadRisk(saved.lat, saved.lon, saved.name || "Saved place");
  }
} catch (e) { /* ignore bad saved data */ }