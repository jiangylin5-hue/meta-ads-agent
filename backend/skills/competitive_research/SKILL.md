---
name: competitive_research
description: "Research public Meta Ad Library ads and report observed creative patterns as observations or hypotheses."
---

# competitive_research

## Purpose
Research public Meta Ad Library ads and report observed creative patterns as observations or hypotheses.

## Use when
- competitor ads
- Ad Library search
- creative themes, formats, and CTAs

## Do not use
- private account performance claims
- scraping or browser automation
- treating ad longevity as proven performance

## Required inputs
- search terms or page ids
- countries

## Required evidence
- search criteria
- countries
- active status
- observed_at
- returned ads and creative metadata

## Output
Use the output contract `competitive_observation_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Use ads_library_search only; do not install scrapers or connectors.
- Do not claim competitor spend, sales, or exact performance.
- Separate observed creative from inferred strategy.
- Ad duration is not proof of profitability.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
