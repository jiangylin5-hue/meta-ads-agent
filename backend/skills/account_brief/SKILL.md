---
name: account_brief
description: "Summarize current Meta account or entity performance with a named window and missing data."
---

# account_brief

## Purpose
Summarize current Meta account or entity performance with a named window and missing data.

## Use when
- current spend, results, or best/worst entity
- short account brief
- plain lookup

## Do not use
- causal diagnosis
- budget/status changes
- audit health score

## Required inputs
- ad_account_id or selected account
- date window
- entity level

## Required evidence
- source tool
- account_id
- actual date window
- observed_at
- entity level
- missing data

## Output
Use the output contract `account_brief_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Use tool results for every account-specific number.
- Keep facts, assumptions, and missing data separate.
- Do not explain causes in a brief.
- Do not create drafts.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
