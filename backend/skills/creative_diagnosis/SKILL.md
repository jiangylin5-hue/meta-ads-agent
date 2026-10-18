---
name: creative_diagnosis
description: "Diagnose Meta creative performance, fatigue, copy structure, format coverage, and preview context."
---

# creative_diagnosis

## Purpose
Diagnose Meta creative performance, fatigue, copy structure, format coverage, and preview context.

## Use when
- which creative is weak or tired
- creative performance by ad
- copy, hook, or format review
- preview request

## Do not use
- catalog health
- policy approval
- live creative mutation

## Required inputs
- ad_account_id
- date window
- entity level

## Required evidence
- ad-level performance
- creative metadata
- preview URL when returned
- media metadata
- window
- observed_at

## Output
Use the output contract `creative_finding_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Do not claim visual understanding when only metadata or preview links were returned.
- Include preview_url verbatim when present.
- Resize is coverage, not creative diversity.
- Do not edit creative content with ads_creative_update; that tool handles name, status, and labels.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
