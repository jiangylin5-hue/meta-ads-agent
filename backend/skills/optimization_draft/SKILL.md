---
name: optimization_draft
description: "Convert an evidence-backed Meta diagnosis into a local draft for pause, budget, bid, targeting, creative, or activation review."
---

# optimization_draft

## Purpose
Convert an evidence-backed Meta diagnosis into a local draft for pause, budget, bid, targeting, creative, or activation review.

## Use when
- pause or resume
- change budget or bid
- replace creative
- create a test action draft

## Do not use
- diagnosis-only requests
- live execution
- destructive deletion

## Required inputs
- ad_account_id
- entity id and type
- current value and state
- business target
- evidence

## Required evidence
- current value
- current status
- comparison evidence
- sample size
- learning state
- proposed value
- risk level
- rollback condition

## Output
Use the output contract `optimization_draft_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Read current entity state before a write-like call.
- Draft tools never reach MCP. Approval is not execution.
- Without enough evidence return INVESTIGATE and no draft.
- Do not use a fixed CPA multiple as sole authorization.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.
