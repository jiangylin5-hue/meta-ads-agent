---
name: tracking_troubleshooting
description: "Diagnose Meta Pixel, CAPI, dataset, EMQ, attribution, delivery, and event mapping problems from current tool evidence."
---

# tracking_troubleshooting

## Purpose
Diagnose Meta Pixel, CAPI, dataset, EMQ, attribution, delivery, and event mapping problems from current tool evidence.

## Use when
- Pixel did not fire
- CAPI or EMQ issue
- conversion count mismatch
- delivery blocked by tracking or account state

## Do not use
- claiming tracking is healthy with missing data
- live Pixel rule changes without approval
- performance diagnosis without checking tracking

## Required inputs
- ad_account_id
- problem statement
- date window

## Required evidence
- dataset identity and status
- event volume
- EMQ and match keys
- freshness
- browser versus server source
- pixel rules or parameters
- delivery errors
- missing data

## Output
Use the output contract `tracking_finding_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Never write tracking normal when dataset quality or volume is missing.
- ads_get_dataset_stats accepts at most 28 days.
- ads_get_errors does not cover disabled accounts or ad rejection.
- Tracking changes require a separate draft and approval.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
