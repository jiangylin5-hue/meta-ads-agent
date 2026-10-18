---
name: experiment_design
description: "Design or evaluate a Meta experiment with eligibility, hypothesis, sample, duration, guardrails, and a stopping rule."
---

# experiment_design

## Purpose
Design or evaluate a Meta experiment with eligibility, hypothesis, sample, duration, guardrails, and a stopping rule.

## Use when
- A/B or split test eligibility
- design a controlled test
- interpret an existing test
- incrementality or lift question

## Do not use
- calling ordinary ad variation an A/B test
- declaring a winner from insufficient data
- changing an experiment without approval

## Required inputs
- ad_account_id
- decision or hypothesis
- primary metric

## Required evidence
- eligibility
- existing tests
- randomization unit
- primary metric
- sample and duration assumptions
- stopping rule
- guardrails
- missing data

## Output
Use the output contract `experiment_plan_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Call ads_experiment_check_eligibility before proposing creation.
- Never call an ordinary ad comparison a randomized A/B test.
- Do not declare significance without a declared stopping rule and sufficient sample.
- Experiment creation and update remain drafts.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
