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

function normalizedDeal(deal) {
  return {
    cab_class: "unknown",
    make: null,
    model: null,
    transmission: null,
    drivetrain: null,
    seller_reputation: { status: "unconfirmed" },
    seller_legal_signal: { status: "none_confirmed" },
    fuel_economy: { status: "unconfirmed" },
    ...deal
  };
}

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
    setControlState(result.state, result.state === "running" ? "Prochain scan automatique selon l’horaire GitHub." : "Le prochain scan est bloqué. Un scan déjà lancé peut toutefois se terminer.");
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
    const result = await response.json();
    if (result.state === "running" && result.dispatch === "failed") {
      setControlState("running", "Veille réactivée, mais le scan immédiat a échoué. Le prochain scan planifié reste actif.");
      return;
    }
    if (result.state === "running" && result.dispatch === "cooldown") {
      const minutes = Math.max(1, Math.ceil(result.retry_after_seconds / 60));
      setControlState("running", `Veille réactivée. Nouveau scan immédiat limité; réessaie dans environ ${minutes} min.`);
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setControlState(result.state, result.state === "paused" ? "Le prochain scan est bloqué. Un scan déjà lancé peut toutefois se terminer." : result.changed === false ? "La veille était déjà active; aucun scan supplémentaire n’a été lancé." : "Workflow réactivé; un scan immédiat a été demandé.");
  } catch (_error) {
    setControlState("unconfigured", "Action refusée ou passerelle inaccessible.");
  }
}

function renderCard(deal) {
  deal = normalizedDeal(deal);
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

  const seller = fragment.querySelector(".seller-reputation");
  seller.append(text("strong", "Vendeur"));
  if (deal.seller_reputation.status === "confirmed") {
    const source = document.createElement("a");
    source.href = deal.seller_reputation.source_url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = `${deal.seller_reputation.name} · ${deal.seller_reputation.rating.toLocaleString("fr-CA")} ★ (${formatNumber.format(deal.seller_reputation.review_count)} avis)`;
    seller.append(source);
    seller.append(text("small", `Vérifié le ${deal.seller_reputation.verified_at}`));
  } else {
    seller.append(text("span", `${deal.seller_reputation.name ? `${deal.seller_reputation.name} · ` : ""}Réputation Google non confirmée`));
    if (deal.seller_reputation.reason) seller.append(text("small", deal.seller_reputation.reason));
  }

  const legal = fragment.querySelector(".seller-legal-signal");
  const signal = deal.seller_legal_signal;
  legal.dataset.severity = signal.status;
  if (["red", "yellow", "unattributed"].includes(signal.status)) {
    const label = signal.status === "red" ? "Alerte rouge" : signal.status === "yellow" ? "Vigilance" : "Non attribué";
    legal.append(text("strong", label));
    legal.append(text("span", signal.nature));
    const source = text("a", `${signal.event_type} · ${signal.event_date}`);
    source.href = signal.source_url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    legal.append(source);
    legal.append(text("small", `${signal.branch} · ${signal.legal_entity} · ${signal.permit_or_neq}`));
  } else {
    legal.append(text("strong", "Risque vendeur"));
    legal.append(text("span", "Aucun signal confirmé"));
    if (signal.source_checked_at) legal.append(text("small", `Sources vérifiées le ${signal.source_checked_at}`));
  }

  const fuel = fragment.querySelector(".fuel-economy");
  fuel.append(text("strong", "Consommation"));
  if (deal.fuel_economy.status === "confirmed") {
    const source = document.createElement("a");
    source.href = deal.fuel_economy.source_url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = `${deal.fuel_economy.city_l_per_100km.toLocaleString("fr-CA")} ville · ${deal.fuel_economy.highway_l_per_100km.toLocaleString("fr-CA")} route L/100 km`;
    fuel.append(source);
    const match = deal.fuel_economy.match;
    fuel.append(text("small", `${match.year} · ${match.engine} · ${match.transmission} · ${match.drivetrain}`));
  } else {
    fuel.append(text("span", "Ville / route non confirmées"));
    if (deal.fuel_economy.reason) fuel.append(text("small", deal.fuel_economy.reason));
  }
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
  const model = $("#model-filter").value;
  const cab = $("#cab-filter").value;
  const maxPayment = Number($("#payment-filter").value);
  return state.data.deals.filter((deal) => {
    if (eligibleOnly && !deal.eligible) return false;
    deal = normalizedDeal(deal);
    if (model !== "all" && deal.model !== model) return false;
    if (cab !== "all" && deal.cab_class !== cab) return false;
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
  const previewFile = new URLSearchParams(location.search).get("preview") === "enriched"
    ? "data/deals.preview.json"
    : "data/deals.json";
  const [dealsResponse, historyResponse] = await Promise.all([
    fetch(previewFile, { cache: "no-store" }),
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
  ["#eligible-only", "#model-filter", "#cab-filter", "#payment-filter"].forEach((selector) => {
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
