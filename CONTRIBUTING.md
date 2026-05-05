# Contributing to inter-agent-deaddrop

## Issues welcome

- **Adoption reports** — if you deploy this protocol between two agents, open an issue with the agent pair, the use case, and any rough edges. Your reports inform v3.
- **Protocol questions** — anything unclear in PROTOCOL.md is a doc bug. Open an issue.
- **Edge cases** — invariants that don't hold, message types that need clarification, etc.

## Pull requests

### Doc-only changes
Welcome. Fix typos, clarify language, add examples. No need to ask first.

### Protocol changes
**Open an issue first.** Any change to:
- The eight invariants
- The message format
- The cadence semantics
- The conflict resolution procedure

...constitutes a protocol-level change and requires explicit version bump.

### New transport recommendations
If you've battle-tested a new cross-machine transport, contributions to TRANSPORTS.md are welcome with a brief writeup of:
- Setup procedure
- Failure modes encountered
- Performance characteristics
- Recommended hardening

## Versioning

- Patch (e.g., v2.0.1): doc fixes, example improvements, no semantic change
- Minor (e.g., v2.1): backward-compatible additions (new optional message types, new tier definitions)
- Major (e.g., v3.0): invariant changes, message-format changes, semantic breaks

Both agents in a deployment MUST run the same major.minor version. Mismatched majors → schema_drift incident.

## Hard rules

1. **No vendor-specific code.** This is a protocol spec; reference implementations are illustrative, not normative.
2. **No prescribed transport.** TRANSPORTS.md describes options; the spec itself is transport-agnostic.
3. **Examples must run.** Sample code in `examples/` is tested in CI (TODO).
4. **No emoji in PROTOCOL.md or SKILL.md.** Keep the contract docs ASCII-clean for tool compatibility.
5. **All claims about production usage must be verifiable.** "Working in production" requires log volumes + duration + scope.

## Code of conduct

Be useful, be precise, be brief. This is an engineering doc, not a manifesto.
