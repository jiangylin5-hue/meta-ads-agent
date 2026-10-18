---
name: performance_diagnosis
description: "Explain Meta performance changes using evaluation level, learning state, marginal efficiency, change history, and evidence."
---

# performance_diagnosis

## Purpose
Explain Meta performance changes using evaluation level, learning state, marginal efficiency, change history, and evidence.

## Use when
- CPA, ROAS, CTR, CPM, or conversion change
- which entity is dragging performance
- learning phase or creative fatigue question
- wasted spend question

## Do not use
- simple current-state lookup
- action execution
- policy approval

## Required inputs
- ad_account_id
- current date window
- entity level

## Required evidence
- current and comparison windows
- evaluation level
- learning state
- sample size
- change history
- delivery errors
- missing data

## Output
Use the output contract `performance_finding_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Inspect next_actions from ads_get_ad_entities before answering.
- ads_insights_performance_trend supports AD and ADSET only; use ads_get_ad_entities with time_increment for Campaign trends.
- Separate observations, causes, and hypotheses.
- Do not recommend a mutation without an explicit user request.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
