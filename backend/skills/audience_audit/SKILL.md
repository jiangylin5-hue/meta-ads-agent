---
name: audience_audit
description: "Audit existing Meta custom audiences, their usage, targeting fields, and auction overlap without claiming audience discovery."
---

# audience_audit

## Purpose
Audit existing Meta custom audiences, their usage, targeting fields, and auction overlap without claiming audience discovery.

## Use when
- list or inspect custom audiences
- which ad sets use an audience
- lookalike or exclusion review
- audience overlap

## Do not use
- interest, geography, or age/gender discovery
- live audience mutation without approval
- claims about audience size without tool evidence

## Required inputs
- ad_account_id

## Required evidence
- audience identity and subtype
- size and status when returned
- adsets using it
- targeting fields
- auction overlap evidence
- missing data

## Output
Use the output contract `audience_finding_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Current MCP has no interest, geography, or age/gender discovery tool.
- Do not infer audience composition from names.
- Before a destructive audience change, collect usage and downstream impact.
- Audience creation remains a draft path.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
