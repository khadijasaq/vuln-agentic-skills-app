# Feature: AST01 — Malicious Skills

**Derives from** `docs/PRD.md` (PRD v1.0) + `docs/TDD.md` (system-wide technical design).

**Scope.** A benign-looking skill that performs its advertised job correctly while quietly copying the user's task data to the local mock collector. Detected by the findings engine's **correlation axis** (`TDD §4.6`), severity **critical** (`TDD §14 Q-2`). This is the feature that implements `COVERT_DATA_FLOW`, reserved but unevaluated in the App Foundation.

**TBD — spec to be written, based on PRD + TDD.**
