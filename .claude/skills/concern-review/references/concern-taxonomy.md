# Concern Taxonomy

## Triage classes

**A — Block before implementation**
The current spec/API/contract is ambiguous enough that implementation will likely produce
invalid or misleading work.

**B — Fix before closing this bucket**
Small local issue in the active bucket's code/tests/docs/API that should be corrected now.

**C — Park on the tech-debt shelf / later phase**
Real concern, but belongs to a later bucket or phase. Route to `docs/debt.md` (the
tech-debt shelf the dispatch sweep drains), with enough locus to act on it cold.

**D — Accept / ignore**
Technically true, but too speculative, too costly, already mitigated, or not relevant to
the current phase.

Key rule: Do not treat "real concern" as "must fix now." Classify by timing and
actionability.

---

## Concern lenses

### 1. Contract mismatch
A field/key/source-pointer/schema/version means something different to the producer than
to the consumer.

Examples:
- A timestamp field stored as a Unix epoch but parsed by the consumer as ISO-8601.
- **Type, not just value:** a producer returns a dataclass/object instance and stores it
  in a result dict; the consumer treats it as a plain dict. Ask "what type does
  `result.x[name]` actually hold — object or dict?" whenever a change adds a consumer of
  another component's emitted structure.

### 2. Evaluator / scorer validity
The system may evaluate a different thing than intended.

Examples:
- An integration test exercises a mock or stub instead of the real adapter, so it proves
  nothing about the seam it claims to cover.
- A benchmark tuned against one configuration but run against another.

**Diagnostic before flagging a "wrong-path" mismatch as evaluation-invalidating:** ask
"which code path does the evaluator *actually* exercise for this case?" A component can be
scored via a path that bypasses the suspect code entirely — in which case a mismatch
there affects production only, not the evaluation's validity. Confusing the two paths
produces a false alarm and wastes an investigation cycle.

### 3. Misleading-success states
Tests pass or artifacts load, but the result is semantically empty.

Examples:
- A test asserts the response status is 200 but never inspects the body — an empty list
  passes.
- A join "succeeds" with zero matched rows; a diff reports zero changes because both sides
  are empty.
- Metadata or defaults silently substituted for the real payload.

### 4. API seam / handoff ownership
A later caller needs data/metadata/status that the current change leaves as convention,
OR a shared function has two callers that need different behavior and a change for one
breaks the other.

Examples:
- A status/readiness field a later phase depends on is left implicit.
- A shared helper is called by both a public endpoint and a batch job; changing its
  validation for the endpoint silently breaks the job. Check: if the shared file is in the
  changed set, verify the *other* caller still gets its original behavior.

### 5. Test truthfulness
Tests do not assert the behavior their name claims.

Examples:
- `test_rejects_expired_token` only checks that the call doesn't throw.
- Weak assertions, boolean-precedence bugs, fixture artifacts, missing negative tests.

### 6. State / cache / isolation
Mutable state, lazy loading, caches, or reused fixtures can contaminate results.

Examples:
- A module-level cache aliases objects across cases so one test mutates another's input.
- Reusing a mutated state object across iterations instead of a fresh copy.

### 7. Scope / phase correctness
The concern is real but belongs elsewhere.

Examples:
- Production hardening raised during a prototype-validation phase.
- Runtime integration raised before the evaluation it depends on exists.

### 8. Metric validity
The reported metric may not measure the intended goal.

Examples:
- Code-coverage percentage cited as proof of test quality.
- A ratio interpreted without checking the sample size behind it.
- **A valid system-level result dismissed by judging it against component-level realism
  instead of the system's actual purpose.** Ask "what quantity does this system exist to
  measure?" before calling a result invalid; if a collaborator's interpretation
  contradicts yours, re-check your own frame before overriding it.

### 9. Artifact freshness / reproducibility
Generated files, build outputs, trained weights, reports, or docs may be stale or
path-sensitive.

Examples:
- A committed snapshot or lockfile not regenerated after a dependency bump.
- A report whose path or environment default differs between author and a fresh clone.

### 10. User-decision dependency
The issue is not technical; it needs owner preference or a phase-scope decision. Surface
it separately instead of guessing.

### 11. Review-loop stop condition
Decide whether more review is still high value. If the remaining concerns are C/D only,
recommend proceeding.

### 12. Unverified hypothesis
A bucket description or prior-session handoff states a root cause as established fact, but
no verification step is present. If the hypothesis is wrong, the entire effort solves the
wrong problem.

Examples:
- "Root cause: cache key collision" written before the actual keys were logged and
  compared.
- A symptom attributed to a missing field that, on a one-line grep, exists under a
  different name — so the real cause is elsewhere.

Ask: "What is the cheapest one-liner that would confirm or refute this root cause before
any code change?" Classify B or C depending on whether the verification is fast (B) or
requires a new trace/run (C).
