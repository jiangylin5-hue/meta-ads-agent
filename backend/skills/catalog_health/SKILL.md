---
name: catalog_health
description: "Inspect Meta catalog, feed, product set, event source, DPA eligibility, and delivery diagnostics with explicit missing data."
---

# catalog_health

## Purpose
Inspect Meta catalog, feed, product set, event source, DPA eligibility, and delivery diagnostics with explicit missing data.

## Use when
- products missing from ads
- catalog warning or feed issue
- DPA or Advantage+ readiness
- product match rate

## Do not use
- inventing health thresholds
- automatic product or feed deletion
- claiming catalog health without catalog_id and evidence

## Required inputs
- catalog_id or ad_account_id
- business context

## Required evidence
- catalog identity
- feed and product set status
- diagnostics
- DPA health checks
- event source match rate
- source timestamps
- missing data

## Output
Use the output contract `catalog_finding_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- No dedicated catalog health Skill exists in the three upstream projects; use only setup, feed-gate, product-reference rules and live MCP schema.
- ads_catalog_get_businesses is identity-scoped; do not attribute a business to an account without account-scoped evidence.
- Preview product filters with ads_catalog_list_products before set creation.
- Deletes, feed removal, and event-source disconnection are high-risk.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
