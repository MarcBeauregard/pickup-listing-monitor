const state = {
  data: null,
  history: [],
  control: "unknown"
};

const $ = (selector) => document.querySelector(selector);
const formatNumber = new Intl.NumberFormat("fr-CA");
const formatDate = new Intl.DateTimeFormat("fr-CA", {
  timeZone: "America/Toronto",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit"
});

function controlApiBase() {
  const fromQuery = new URLSearchParams(location.search).get("controlApi");
  return (fromQuery || window.PICKUP_CONFIG?.controlApiBase || "").replace(/\/$/, "");
}

function text(tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function setControlState(next, detail) {
  state.control = next;
  const label = next === "running" ? "active" : next === "paused" ? "arrêtée" : "à connecter";
  $("#control-state").textContent = label;
  $("#control-detail").textContent = detail;
  const pill = $("#watch-status");
  pill.classList.toggle("is-active", next === "running");
  pill.classList.toggle("is-paused", next === "paused");
  pill.querySelector("span:last-child").textContent = next === "running" ? "Veille active" : next === "paused" ? "Veille arrêtée" : "Contrôle à activer";
  $("#pause-button").disabled = next !== "running";
  $("#resume-button").disabled = next !== "paused";
}

async function refreshControl() {
  const base = controlApiBase();
  if (!base) {
    setControlState("unconfigured", "La passerelle sécurisée sera activée après le GO de déploiement.");
    return;
  }
  try {
    const response = await fetch(`${base}/api/state`, { credentials: "include" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    setControlState(result.state, result.state === "running" ? "Prochain scan automatique selon l’horaire GitHub." : "Le workflow planifié est réellement désactivé.");
  } catch (_error) {
    setControlState("unconfigured", "Connexion au contrôle impossible; les données restent consultables.");
  }
}

async function control(action) {
  const base = controlApiBase();
  if (!base) return;
  $("#pause-button").disabled = true;
  $("#resume-button").disabled = true;
  $("#control-detail").textContent = action === "pause" ? "Arrêt en cours…" : "Reprise en cours…";
  try {
    const response = await fetch(`${base}/api/control`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    setControlState(result.state, result.state === "paused" ? "Le prochain run est bloqué : workflow désactivé." : "Workflow réactivé; un scan immédiat a été demandé.");
  } catch (_error) {
    setControlState("unconfigured", "Action refusée ou passerelle inaccessible.");
  }
}

function renderCard(deal) {
  const fragment = $("#deal-card-template").content.cloneNode(true);
  const card = fragment.querySelector(".deal-card");
  const photoLink = fragment.querySelector(".deal-photo-link");
  photoLink.href = deal.url;
  const image = fragment.querySelector(".deal-photo");
  image.src = deal.image || "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";
  image.alt = `Photo de ${deal.title}`;
  fragment.querySelector(".new-badge").hidden = !deal.is_new;
  fragment.querySelector(".match-badge").textContent = deal.eligible ? "Bon match" : `Score ${deal.score}`;
  fragment.querySelector(".deal-kicker").textContent = [deal.year, deal.trim, deal.engine].filter(Boolean).join(" · ");
  fragment.querySelector(".deal-title").textContent = deal.title;
  const payment = fragment.querySelector(".deal-payment");
  payment.textContent = deal.monthly_7pct ? `${formatNumber.format(deal.monthly_7pct)} $` : "—";
  payment.append(text("small", "/ mois estimé"));

  const facts = fragment.querySelector(".deal-facts");
  [
    deal.mileage ? `${formatNumber.format(deal.mileage)} km` : "km à confirmer",
    deal.cab || "cabine à confirmer",
    deal.engine || "moteur à confirmer"
  ].forEach((value) => facts.append(text("span", value)));
  fragment.querySelector(".deal-location").textContent = deal.location || "Emplacement à confirmer";
  fragment.querySelector(".deal-price").textContent = deal.price ? `${formatNumber.format(deal.price)} $` : "Prix à confirmer";
  const link = fragment.querySelector(".deal-link");
  link.href = deal.url;

  const reasons = fragment.querySelector(".deal-reasons");
  deal.reasons.forEach((reason) => reasons.append(text("li", reason)));
  if (!deal.reasons.length) reasons.remove();
  card.dataset.eligible = String(deal.eligible);
  return fragment;
}

function filteredDeals() {
  if (!state.data) return [];
  const eligibleOnly = $("#eligible-only").checked;
  const trim = $("#trim-filter").value;
  const engine = $("#engine-filter").value;
  const maxPayment = Number($("#payment-filter").value);
  return state.data.deals.filter((deal) => {
    if (eligibleOnly && !deal.eligible) return false;
    if (trim !== "all" && deal.trim !== trim) return false;
    if (engine !== "all" && !deal.engine?.startsWith(engine)) return false;
    if (!deal.monthly_7pct || deal.monthly_7pct > maxPayment) return false;
    return true;
  });
}

function renderDeals() {
  const deals = filteredDeals();
  const grid = $("#deal-grid");
  grid.replaceChildren(...deals.map(renderCard));
  $("#result-count").textContent = `${deals.length} résultat${deals.length === 1 ? "" : "s"}`;
  $("#empty-state").hidden = deals.length !== 0;
}

function renderHistory() {
  const list = $("#history-list");
  list.replaceChildren(...state.history.slice(0, 6).map((run) => {
    const item = document.createElement("li");
    item.append(text("strong", formatDate.format(new Date(run.checked_at))));
    item.append(text("span", `${run.discovered} annonces lues · ${run.eligible} bons matchs · ${run.new_ids.length} nouvelles`));
    item.append(text("span", run.status === "ok" ? "Réussi" : "Partiel", "history-status"));
    return item;
  }));
}

async function loadData() {
  const [dealsResponse, historyResponse] = await Promise.all([
    fetch("data/deals.json", { cache: "no-store" }),
    fetch("data/history.json", { cache: "no-store" })
  ]);
  if (!dealsResponse.ok || !historyResponse.ok) throw new Error("Données indisponibles");
  state.data = await dealsResponse.json();
  state.history = await historyResponse.json();
  $("#data-warning").hidden = state.data.scan_status !== "partial";
  $("#eligible-count").textContent = state.data.counts.eligible;
  $("#new-count").textContent = state.data.counts.new_eligible;
  $("#last-checked-short").textContent = formatDate.format(new Date(state.data.last_checked_at));
  renderDeals();
  renderHistory();
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#watch-status").addEventListener("click", () => $("#control-panel").scrollIntoView({ behavior: "smooth" }));
  $("#pause-button").addEventListener("click", () => control("pause"));
  $("#resume-button").addEventListener("click", () => control("resume"));
  ["#eligible-only", "#trim-filter", "#engine-filter", "#payment-filter"].forEach((selector) => {
    $(selector).addEventListener("change", renderDeals);
  });
  try {
    await Promise.all([loadData(), refreshControl()]);
  } catch (_error) {
    $("#result-count").textContent = "Données temporairement indisponibles";
    $("#empty-state").hidden = false;
    $("#empty-state strong").textContent = "Le dernier rapport n’a pas pu être chargé.";
  }
});
