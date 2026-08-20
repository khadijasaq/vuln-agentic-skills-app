# Feature: AST04 — Insecure Metadata

**Derives from** `docs/PRD.md` (PRD v1.0) + `docs/TDD.md` (system-wide technical design).

**Scope.** A skill whose manifest lies: it declares itself read-only, local and network-free, and in fact reads from the filesystem and makes a network call. Detected by the findings engine's **truthfulness axis** (`TDD §4.4`), severity **high** (`TDD §14 Q-2`).

**TBD — spec to be written, based on PRD + TDD.**
