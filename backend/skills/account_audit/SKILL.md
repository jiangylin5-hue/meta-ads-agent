---
name: account_audit
description: "Run an evidence-grounded Meta account audit and report the highest-priority findings with coverage limits."
---

# account_audit

## Purpose
Run an evidence-grounded Meta account audit and report the highest-priority findings with coverage limits.

## Use when
- full account health review
- measurement, structure, creative, budget, delivery, and policy review
- find top problems

## Do not use
- single metric lookup
- execution of changes
- claims of complete coverage when tools failed

## Required inputs
- ad_account_id
- audit window
- business goal or conversion definition

## Required evidence
- requirement and check result
- evidence source
- account_id
- actual window
- observed_at
- evidence coverage
- missing data

## Output
Use the output contract `account_audit_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- pass and fail require evidence.
- unknown lowers coverage and never lowers health.
- Do not present a health score below 60 percent evidence coverage.
- Return at most three priority findings.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
