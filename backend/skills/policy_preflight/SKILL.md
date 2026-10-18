---
name: policy_preflight
description: "Review Meta ad copy, creative, category, and destination for policy risk; never claim policy approval."
---

# policy_preflight

## Purpose
Review Meta ad copy, creative, category, and destination for policy risk; never claim policy approval.

## Use when
- before launch
- policy-risk review
- ad disapproval analysis
- ad and landing-page message match

## Do not use
- claiming Meta approval
- replacing legal review
- using remembered policy rules as current fact

## Required inputs
- ad copy or creative ids
- advertiser and product context
- special ad category

## Required evidence
- ad copy and creative context
- special category
- target geography
- policy source or user-provided policy text
- observed_at
- missing data

## Output
Use the output contract `policy_risk_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Current MCP cannot fetch complete Meta policy pages or landing-page HTML.
- ads_get_help_article is a help lookup, not policy approval.
- Cite policy text only when it was actually supplied or retrieved.
- Meta review remains the final gate.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
