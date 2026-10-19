---
name: campaign_plan
description: "Build a Meta campaign plan and create non-live Meta Draft objects from offer, goal, budget, audience, destination, tracking, and business context."
---

# campaign_plan

## Purpose
Build a Meta campaign plan and create non-live Meta Draft objects from offer, goal, budget, audience, destination, tracking, and business context.

## Use when
- new campaign
- budget and structure plan
- audience and creative matrix
- launch readiness

## Do not use
- live launch
- unrequested campaign creation
- product release outside Meta ads

## Required inputs
- offer
- business goal
- budget and duration
- geography
- audience or ICP
- destination
- tracking status

## Required evidence
- offer and destination
- account and page access
- audience details
- budget inputs
- tracking state
- catalog eligibility when relevant
- missing data

## Output
Use the output contract `campaign_plan_v1`. Keep facts, hypotheses, missing data, and the decision separate.

## Hard rules
- Do not invent targeting attributes or catalog products.
- Do not claim that a draft is live or published. Report the returned Draft object id and its Draft Mode state.
- Create campaign, ad set, ad, and creative objects only through the permitted create tools, which return Draft Mode objects.
- Never call activation or publish tools. Update or delete only existing Drafts through ads_update_entity with draft_only=true and a fresh object_state=draft read.
- Do not use a landing page audit result without a page-reading tool.

## References
Use the reference index returned by load_skill. Read only the reference needed for the current decision; do not load every reference.


## Confirmation Gate

On a first request to create a campaign or ad, produce the plan first and do not call any create tool. End the turn with this question:

`是否要根据这个方案创建非发布草稿？请回复“确认创建草稿”。`

Only after a later user message explicitly confirms with `确认创建草稿` may you call the permitted create tools. Mutation or deletion of an existing draft requires the user's explicit target id and a fresh `object_state=draft` read; it does not need the plan-confirmation phrase.
