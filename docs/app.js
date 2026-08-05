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
    seller_legal_signal: { status: "not_audited" },
    fuel_economy: { status: "unconfirmed" },
    high_mileage: false,
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

function renderTrust(deal) {
  const trust = deal.trust_score || { score: null, level: "non_audité", level_label: "Données insuffisantes", components: {}, reasons: [], sources: [] };
  const reputation = deal.seller_reputation || { status: "unconfirmed" };
  const signal = deal.seller_legal_signal || { status: "not_audited" };
  const details = document.createElement("details");
  const styleLevel = trust.level === "rouge" || signal.status === "red" ? "red" : trust.level === "jaune" || signal.status === "yellow" ? "yellow" : "pending";
  details.className = `trust trust--${styleLevel}`;
  const summary = document.createElement("summary");
  const scoreVisible = trust.score != null && trust.level !== "vigilance_homonymie";
  const googleVisible = reputation.status === "confirmed"
    && Number.isFinite(reputation.rating)
    && reputation.rating >= 0
    && reputation.rating <= 5
    && Number.isInteger(reputation.review_count)
    && reputation.review_count >= 0;
  const reputationSummary = googleVisible
    ? `${reputation.rating.toLocaleString("fr-CA")} ★ · ${formatNumber.format(reputation.review_count)} avis`
    : "Information insuffisante";
  const riskVisible = ["rouge", "jaune", "vigilance_homonymie"].includes(trust.level)
    || ["red", "yellow", "unattributed"].includes(signal.status);
  const signalOnlyRisk = ["red", "yellow", "unattributed"].includes(signal.status)
    && !["rouge", "jaune", "vigilance_homonymie"].includes(trust.level);
  const riskSummary = riskVisible ? (signalOnlyRisk ? signal.nature : trust.level_label) || signal.nature || "Signal à vérifier" : null;
  const ariaParts = [`Confiance vendeur : ${reputationSummary}`];
  if (riskSummary) ariaParts.push(riskSummary);
  ariaParts.push("Activer pour voir le détail.");
  summary.setAttribute("aria-label", ariaParts.join(". "));
  summary.append(text("span", "", "trust-dot"));
  summary.lastChild.setAttribute("aria-hidden", "true");
  const label = text("span", "", "trust-label");
  label.append(text("span", "Confiance vendeur", "trust-heading"));
  label.append(text("span", reputationSummary, "trust-rating"));
  if (riskSummary) label.append(text("span", riskSummary, "trust-risk"));
  const branchScope = signal.branch_scope;
  if (branchScope === "entity_only_branch_not_named_in_event" || branchScope === "entity_head_office_not_named_in_event") {
    label.append(text("span", "Même entité juridique; cette succursale n’est pas nommée dans l’événement.", "trust-branch-scope"));
  }
  summary.append(label);
  const chevron = text("span", "⌄", "trust-chevron");
  chevron.setAttribute("aria-hidden", "true");
  summary.append(chevron);
  details.append(summary);

  const panel = text("div", "", "trust-panel");
  const values = trust.components || {};
  const componentRows = [
    ["Score exact", scoreVisible ? `${trust.score.toLocaleString("fr-CA")} / 100` : null],
    ["Note", values.rating_points],
    ["Volume d’avis", values.volume_points],
    ["Identité", values.identity_points],
    ["Fraîcheur", values.freshness_multiplier == null ? null : `× ${values.freshness_multiplier.toLocaleString("fr-CA")}`],
    ["Âge de la preuve", values.days_elapsed == null ? null : `${values.days_elapsed} jour${values.days_elapsed === 1 ? "" : "s"}`],
    ["Base réputation ajustée", values.reputation_base],
    ["Bande juridique", values.band_applied ? `${values.band_applied[0]}–${values.band_applied[1]}` : null]
  ].filter(([, value]) => value != null && value !== "");
  const legalSourceLabel = [signal.event_type, signal.event_date].filter(Boolean).join(" · ");
  const legalIdentity = [signal.branch, signal.legal_entity, signal.permit_or_neq].filter(Boolean).join(" · ");
  const hasLegalDetail = ["red", "yellow", "unattributed"].includes(signal.status)
    || Boolean(signal.nature || signal.source_url || legalSourceLabel || legalIdentity);
  const showScoreDetails = scoreVisible || googleVisible || hasLegalDetail;
  const reasons = (trust.reasons || []).filter(Boolean);

  if (googleVisible) {
    const google = text("div", "", "trust-panel-section");
    google.append(text("h4", "Réputation Google"));
    const googleLabel = `${reputation.rating.toLocaleString("fr-CA")} / 5 · ${formatNumber.format(reputation.review_count)} avis`;
    if (reputation.source_url) {
      const source = text("a", googleLabel, "trust-google");
      source.href = reputation.source_url;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      google.append(source);
    } else {
      google.append(text("p", googleLabel, "trust-google"));
    }
    if (reputation.verified_at) google.append(text("p", `Vérifié le ${reputation.verified_at}`, "trust-caveat"));
    panel.append(google);
  }

  if (showScoreDetails && componentRows.length) {
    const components = text("div", "", "trust-panel-section");
    components.append(text("h4", "Composantes du score"));
    const list = text("ul", "", "trust-components");
    componentRows.forEach(([name, value]) => {
      const item = document.createElement("li");
      item.append(text("span", name));
      item.append(text("span", typeof value === "number" ? `${value.toLocaleString("fr-CA")} pts` : value));
      list.append(item);
    });
    components.append(list);
    panel.append(components);
  }

  if (hasLegalDetail) {
    const legalSection = text("div", "", "trust-panel-section");
    legalSection.append(text("h4", "Signaux juridiques"));
    const alertClass = signal.status === "red" ? "trust-alert--red" : signal.status === "yellow" ? "trust-alert--yellow" : "trust-alert--muted";
    const alert = text("div", "", `trust-alert ${alertClass}`);
    alert.append(text("span", signal.nature || riskSummary || "Signal juridique à vérifier"));
    if (signal.source_url) {
      const source = text("a", legalSourceLabel || "Source juridique", "meta");
      source.href = signal.source_url;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      alert.append(source);
    } else if (legalSourceLabel) {
      alert.append(text("span", legalSourceLabel, "meta"));
    }
    if (legalIdentity) alert.append(text("span", legalIdentity, "meta"));
    legalSection.append(alert);
    reasons.forEach((reason) => legalSection.append(text("p", reason, "trust-caveat")));
    panel.append(legalSection);
  } else if (showScoreDetails && reasons.length) {
    const explanation = text("div", "", "trust-panel-section");
    explanation.append(text("h4", "Explications"));
    reasons.forEach((reason) => explanation.append(text("p", reason, "trust-caveat")));
    panel.append(explanation);
  }

  if (!panel.children.length) {
    panel.append(text("p", "Information insuffisante", "trust-insufficient"));
  } else if (showScoreDetails) {
    const asOf = [trust.computed_at ? `Calculé le ${trust.computed_at}` : null, trust.formula_version ? `formule v${trust.formula_version}` : null].filter(Boolean).join(" · ");
    if (asOf) panel.append(text("p", asOf, "trust-asof"));
  }
  details.append(panel);
  return details;
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
  const mileageWarning = fragment.querySelector(".mileage-warning");
  mileageWarning.hidden = !deal.high_mileage;
  if (deal.high_mileage) mileageWarning.textContent = `Kilométrage élevé · ${formatNumber.format(deal.mileage)} km`;
  fragment.querySelector(".match-badge").textContent = deal.eligible ? "Bon match" : deal.high_mileage ? "Hors classement" : `Pertinence ${deal.score}`;
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
  fragment.querySelector(".trust-slot").append(renderTrust(deal));
  fragment.querySelector(".deal-price").textContent = deal.price ? `${formatNumber.format(deal.price)} $` : "Prix à confirmer";
  const link = fragment.querySelector(".deal-link");
  link.href = deal.url;

  const reasons = fragment.querySelector(".deal-reasons");
  deal.reasons.forEach((reason) => reasons.append(text("li", reason)));
  if (!deal.reasons.length) reasons.remove();
  card.dataset.eligible = String(deal.eligible);
  card.dataset.highMileage = String(deal.high_mileage);
  return fragment;
}

function filteredDeals() {
  if (!state.data) return [];
  const eligibleOnly = $("#eligible-only").checked;
  const includeHighMileage = $("#include-high-mileage").checked;
  const make = $("#make-filter").value;
  const model = $("#model-filter").value;
  const minYear = Number($("#year-filter").value);
  const cab = $("#cab-filter").value;
  const maxPayment = Number($("#payment-filter").value);
  return state.data.deals.filter((deal) => {
    deal = normalizedDeal(deal);
    if (deal.high_mileage && !includeHighMileage) return false;
    if (eligibleOnly && !deal.eligible && !(includeHighMileage && deal.high_mileage)) return false;
    if (make !== "all" && deal.make !== make) return false;
    if (model !== "all" && deal.model !== model) return false;
    if (!deal.year || deal.year < minYear) return false;
    if (cab !== "all" && deal.cab_class !== cab) return false;
    if (!deal.monthly_7pct || deal.monthly_7pct > maxPayment) return false;
    return true;
  }).sort((left, right) => {
    const leftTacoma = left.make === "Toyota" && left.model === "Tacoma" && left.cab_class === "double_cab";
    const rightTacoma = right.make === "Toyota" && right.model === "Tacoma" && right.cab_class === "double_cab";
    return Number(rightTacoma) - Number(leftTacoma) || Number(right.score || 0) - Number(left.score || 0);
  });
}

function populateVehicleFilters() {
  const addOptions = (selector, values) => {
    const select = $(selector);
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value === "1500" ? "Ram 1500" : value;
      select.append(option);
    });
  };
  addOptions("#make-filter", [...new Set(state.data.deals.map((deal) => deal.make).filter(Boolean))].sort());
  addOptions("#model-filter", [...new Set(state.data.deals.map((deal) => deal.model).filter(Boolean))].sort());
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
  populateVehicleFilters();
  $("#data-warning").hidden = state.data.scan_status !== "partial";
  $("#eligible-count").textContent = state.data.counts.eligible;
  $("#new-count").textContent = state.data.counts.new_eligible;
  $("#last-checked-short").textContent = formatDate.format(new Date(state.data.last_checked_at));
  renderDeals();
  renderHistory();
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", async () => {
  $("#watch-status").addEventListener("click", () => $("#control-panel").scrollIntoView({ behavior: "smooth" }));
  $("#pause-button").addEventListener("click", () => control("pause"));
  $("#resume-button").addEventListener("click", () => control("resume"));
  ["#eligible-only", "#include-high-mileage", "#make-filter", "#model-filter", "#year-filter", "#cab-filter", "#payment-filter"].forEach((selector) => {
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

if (typeof module !== "undefined") module.exports = { renderTrust };
