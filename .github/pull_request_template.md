## Summary

- What changed:
- Why this improves the demo agent:

## Agent Surface

- [ ] `/api/agent/turn` remains the only chat entry point
- [ ] Tools stay read-only or draft-only
- [ ] The loop keeps a bounded step limit and visible trace
- [ ] Final replies stay short and evidence-bound
- [ ] No stale intent router, skills registry, or multi-role pipeline returns

## Safety

- [ ] Action drafts record evidence, recommendation, target, and preflight
- [ ] Approval remains separate from execution
- [ ] Live execution stays disabled in the demo
- [ ] No tokens, raw provider payloads, or data URLs enter model context or traces

## Evidence

- Local checks run:
- Real LLM check, if any:
- Trace or screenshot path:

## Notes

- Follow-up needed:
