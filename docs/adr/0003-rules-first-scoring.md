# ADR 0003: Rule-based enrichment and an explainable score; LLM optional and off

Status: accepted, 2026-11-20

## Context
Enquiries arrive in English, Hindi and Marathi, in Devanagari or typed in Latin letters ("seelan",
"kitna rate", "majha ghar"). The father must trust the score; a number with no reason will be ignored.

## Decision
- Keyword lists per field (project type, size, budget, timeline, contractor vs homeowner, brand, price
  intent, area). Latin keywords match on word boundaries; Devanagari keywords match as substrings.
- Area/pincode is mapped to an approximate centroid (`speed_to_lead/data/pune_areas.csv`, edit freely) and
  the straight-line distance from the shop.
- Score = sum of weights in one table (`scoring.W`). Each rule that fires writes a line, for example
  `+20 timeline: now ('jaldi')`. Staff see these lines on the lead page.
- The weights are starting guesses, not fitted. After about 4 weeks of won/lost outcomes, compare conversion
  by bucket and adjust.
- An OpenAI-compatible LLM can fill fields the rules missed when `STL_LLM_API_KEY` is set. It is off by
  default (free-only budget), never overrides a rule-found value, and failures are ignored.

## Consequences
- Misses happen on unusual spellings; adding a keyword is a one-line change with a test.
- Area centroids are approximate (±1–2 km), good enough for "near / far", not for delivery pricing.
