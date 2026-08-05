const test = require("node:test");
const assert = require("node:assert/strict");

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.textContent = "";
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  get lastChild() {
    return this.children.at(-1);
  }

  get innerText() {
    return [this.textContent, ...this.children.map((child) => child.innerText)].join("");
  }

  findAll(predicate) {
    return [this, ...this.children.flatMap((child) => child.findAll(predicate))].filter(predicate);
  }
}

global.document = {
  createElement(tagName) {
    return new FakeElement(tagName);
  },
  addEventListener() {}
};

const { renderTrust } = require("../docs/app.js");
const snapshot = require("../docs/data/deals.json");

function normalizedText(node) {
  return node.innerText.replace(/\s+/g, " ").trim();
}

function fullDeal() {
  return {
    seller_reputation: {
      status: "confirmed",
      rating: 4.7,
      review_count: 2743,
      source_url: "https://maps.example/dealer",
      verified_at: "2026-08-05"
    },
    seller_legal_signal: {
      status: "red",
      nature: "Entente confirmée",
      event_type: "Entente AMF",
      event_date: "2024-02-15",
      source_url: "https://law.example/case",
      branch: "Succursale test",
      legal_entity: "Garage Exemple inc.",
      permit_or_neq: "2100000-1"
    },
    trust_score: {
      score: 17.48,
      level: "rouge",
      level_label: "Risque élevé",
      components: {
        rating_points: 17,
        volume_points: 20,
        identity_points: 10,
        freshness_multiplier: 1,
        days_elapsed: 0,
        reputation_base: 87.4,
        band_applied: [0, 20]
      },
      reasons: ["Le signal juridique plafonne le score."],
      computed_at: "2026-08-05",
      formula_version: 1
    }
  };
}

test("complete state leads with Google rating and keeps legal risk visible", () => {
  const root = renderTrust(fullDeal());
  const summary = root.children[0];
  const panel = root.children[1];
  const summaryText = normalizedText(summary);
  const panelText = normalizedText(panel);

  assert.match(summaryText, /Confiance vendeur/);
  assert.match(summaryText, /4,7 ★ · 2 743 avis/);
  assert.match(summaryText, /Risque élevé/);
  assert.doesNotMatch(summaryText, /17,5 \/ 100/);
  assert.match(panelText, /Réputation Google/);
  assert.match(panelText, /17,48 \/ 100/);
  assert.match(panelText, /Signaux juridiques/);
  assert.doesNotMatch(panelText, /non disponible|Information insuffisante/);
  assert.equal(panel.findAll((node) => node.tagName === "A").length, 2);
});

test("partial state never invents Google numbers and renders only available legal detail", () => {
  const deal = fullDeal();
  deal.seller_reputation = {
    status: "confirmed",
    rating: 4.7,
    review_count: null,
    source_url: "https://maps.example/dealer",
    verified_at: "2026-08-05"
  };
  deal.trust_score.score = 0;
  deal.trust_score.components = {};
  const root = renderTrust(deal);
  const summaryText = normalizedText(root.children[0]);
  const panelText = normalizedText(root.children[1]);

  assert.match(summaryText, /Information insuffisante/);
  assert.match(summaryText, /Risque élevé/);
  assert.doesNotMatch(summaryText, /4,7|avis/);
  assert.doesNotMatch(panelText, /Réputation Google/);
  assert.match(panelText, /Signaux juridiques/);
  assert.doesNotMatch(panelText, /non disponible/);
});

test("available score explanation is preserved without an empty legal section", () => {
  const deal = fullDeal();
  deal.seller_legal_signal = { status: "not_audited" };
  deal.trust_score.level = "non_audité";
  deal.trust_score.level_label = "Non audité";
  const panel = renderTrust(deal).children[1];
  const panelText = normalizedText(panel);

  assert.match(panelText, /Explications/);
  assert.match(panelText, /Le signal juridique plafonne le score/);
  assert.doesNotMatch(panelText, /Signaux juridiques/);
});

test("empty state renders one information message and no empty sections", () => {
  const root = renderTrust({
    seller_reputation: { status: "unconfirmed", name: "Garage inconnu" },
    seller_legal_signal: { status: "not_audited", source_checked_at: "2026-08-05" },
    trust_score: {
      score: null,
      level: "non_audité",
      level_label: "Données insuffisantes",
      components: { rating_points: null, volume_points: null, days_elapsed: null },
      reasons: ["Réputation Google insuffisante."],
      computed_at: "2026-08-05",
      formula_version: 1
    }
  });
  const summaryText = normalizedText(root.children[0]);
  const panel = root.children[1];

  assert.match(summaryText, /Confiance vendeurInformation insuffisante/);
  assert.equal(normalizedText(panel), "Information insuffisante");
  assert.equal(panel.findAll((node) => node.tagName === "H4").length, 0);
  assert.equal(panel.findAll((node) => node.tagName === "UL").length, 0);
  assert.equal(panel.children.length, 1);
});

test("production data never renders an empty detail element or invented Google number", () => {
  for (const deal of snapshot.deals) {
    const root = renderTrust(deal);
    const summary = root.children[0];
    const panel = root.children[1];
    const rating = summary.findAll((node) => node.className === "trust-rating")[0];
    const reputation = deal.seller_reputation || {};
    const googleComplete = reputation.status === "confirmed"
      && Number.isFinite(reputation.rating)
      && Number.isInteger(reputation.review_count);

    assert.equal(Boolean(rating), true, deal.url);
    assert.equal(normalizedText(rating) === "Information insuffisante", !googleComplete, deal.url);
    if (["rouge", "jaune"].includes(deal.trust_score?.level)) {
      assert.equal(summary.findAll((node) => node.className === "trust-risk").length, 1, deal.url);
    }

    const contentNodes = panel.findAll((node) => ["H4", "LI", "A", "P"].includes(node.tagName));
    for (const node of contentNodes) assert.notEqual(normalizedText(node), "", deal.url);
    assert.equal(normalizedText(panel).includes("non disponible"), false, deal.url);
  }
});
