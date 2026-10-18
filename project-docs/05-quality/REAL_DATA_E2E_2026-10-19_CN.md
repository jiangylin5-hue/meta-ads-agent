# Real-Data E2E: Account Audit And Performance Diagnosis

## Status

- Document status: evidence record
- Date: 2026-10-19
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Summary evidence: [QUALITY_EVIDENCE.md](QUALITY_EVIDENCE.md)
- Account and business identifiers are redacted in this public-safe record.

## Why This Record Exists

Earlier E2E evidence covered an account with no recent performance data and a Campaign that lacked the latest seven-day metrics. Those runs proved missing-data handling but did not prove that the agent could analyze a populated account and produce an evidence-backed optimization decision.

A later read-only account discovery found six readable accounts, including two not present in the previous four-account baseline. Both newly detected accounts were disabled, but each contained substantial historical delivery data. They were used to close the audit and performance-diagnosis evidence gap.

## Environment

- Provider: DeepSeek `deepseek-flash`
- Reasoning effort: `high`
- OpenAI disabled in the child process with an empty API key
- Meta Ads MCP: official endpoint
- Live writes and Draft creation disabled for these runs
- Entry point: `POST /api/agent/turn`
- Turn timeout: 600 seconds

## Account Discovery

- Skill: `account_brief`
- MCP source: `ads_get_ad_accounts`
- Forced refresh used
- Pagination complete: `truncated=false`, no next cursor
- Returns: six readable accounts; two new relative to the prior baseline
- Result: five steps, 29.4 seconds, 12,207 input / 1,979 output tokens, zero Drafts
- Both new accounts returned `DISABLED` with a suspicious-activity reason and `is_queryable=false`

## Run Matrix

| Run | Skill | Model steps | Elapsed | Input / output tokens | Drafts |
| --- | --- | ---: | ---: | ---: | ---: |
| Account discovery | `account_brief` | 5 | 29.4s | 12,207 / 1,979 | 0 |
| New Account A audit | `account_audit` | 9 | 96.4s | 62,560 / 2,559 | 0 |
| New Account B diagnosis | `performance_diagnosis` | 9 | 98.8s | 64,923 / 5,031 | 0 |

Each model step corresponds to one provider request. The performance-diagnosis run executed 20 tool calls across the nine ReAct iterations and stopped with `stopped_reason=final`.

## New Account A: Account Audit

- Account state: `DISABLED`, suspicious activity, all ads paused
- Lifetime observed spend: $5,137.80
- Observed impressions: 595,766
- Rejected ads: 32 `DISAPPROVED` ads with $4,820.22 historical spend, about 93.8% of the observed account spend
- Two Campaigns remained `ACTIVE` but had no delivery in the latest seven-day window
- Account-level delivery error confirmed that the account could not create ads
- Structured decision: `fail`
- Evidence coverage: approximately 50%, so no health score was emitted
- Drafts: zero; execution records: zero

MCP reads included account discovery, account errors, account/campaign/ad entities, performance trend, opportunity score, anomaly signal, activity logs, and Dataset existence.

## New Account B: Performance Diagnosis

- Latest 30-day window: $0 spend and zero delivery because the account was `DISABLED`
- Only `ACTIVE` Campaign had a $600 daily budget but no delivery after the account-level block
- Most recent populated 30-day window: 2026-07-16 through 2026-08-14
- Spend in that window: $5,669.84
- Impressions: 376,405
- The prior equal-length window had no data, so it was not used as a false period-over-period baseline
- Main App Campaign CPA: $69.80 in the first sub-window and $77.98 in the second, about 11.7% worse
- Web Campaign: 31 Pixel purchases and $57.16 CPA in its observed sub-window
- Small App campaigns without reported purchases: $165.02 spend
- Highest-spend rejected ads were concentrated in the historical App delivery structure
- Batch review changes occurred around 2026-08-11 and 2026-08-13
- Structured decision: `FIX`
- Recommendations covered account appeal, rejected creative correction, staged budget restart, and one attribution definition per funnel
- Drafts: zero; execution records: zero

MCP reads included account discovery, account/campaign/ad-set/ad entities at multiple windows, delivery errors, activity logs, creative metadata, field context, and daily account delivery.

## Accuracy Checks

The final numbers were checked against the bounded raw MCP result cache:

- Account A: 32 rejected ads, $4,820.22 rejected-ad spend, $5,137.80 total spend, and two active Campaigns matched the raw rows.
- Account B: $5,669.84 historical-window spend, 376,405 impressions, App CPAs of $69.80 and $77.98, Web CPA of $57.16, and $1,502 daily configured budget matched the raw rows.
- Five Campaigns were initially visible in one compact trace preview; the cached MCP call had requested all seven Campaign IDs and returned no delivery errors, so the final claim was verified against the complete cached result.
- The phrase "five highest-spend rejected ads" was corrected to mean the five highest-spend ads within the rejected set; some active ads had higher spend.
- Web CPA used the 31 purchases present in the comparison window. The lifetime count of 32 was not mixed with window spend.

## Limitations

- Both newly detected accounts were disabled, so current delivery and post-recovery performance were not observable.
- Optimization recommendations are conditional on account reinstatement and were not executed.
- Performance diagnosis used historical data and did not establish live learning-phase behavior.
- `creative_diagnosis` and `tracking_troubleshooting` remain separate E2E gaps.
- Live activation, publication, budget changes, and other Meta writes were not performed.

## Conclusion

This follow-up validates real account discovery plus evidence-backed account audit and performance diagnosis on populated Meta data. It closes the earlier "no data" evidence gap for those two Skills without overstating live optimization or execution capability.
