# Herd AI — LLM Autonomous Agency

## Project Overview

Herd is a research project testing the thesis: **"Can LLMs operate as a fully autonomous agency with real departments, decision-making, and execution?"**

The system models a freelancing agency with 7 departments (CEO, Recon, Analyst, BizDev, Content, Execution, Learning) orchestrated by CrewAI. The initial testbed is Upwork, but the architecture is platform-agnostic via adapters.

## Tech Stack

- **Language:** Python 3.12+ (backend/agents), TypeScript (dashboard)
- **Orchestration:** CrewAI (role-based agents, flows)
- **Scraping:** Playwright + Camoufox (stealth browser)
- **Scoring:** Two-stage (rule-based fast filter + LLM deep score)
- **Proposals:** RAG (ChromaDB) + fine-tuned model on user's past proposals
- **Dashboard:** Mission Control (Next.js) + Langfuse (tracing)
- **A/B Testing:** GrowthBook
- **DB:** SQLite (dev), PostgreSQL (prod)
- **Event Bus:** In-process async (swappable to Redis via Protocol)

---

## Programming Rules (MANDATORY)

### Architecture

- **Strict layering:** `core/ -> models/ -> platform/ | repositories/ -> departments/ -> api/`
- **No circular dependencies.** No department imports another department. Communication is events only.
- **No shared mutable state.** Each department owns its state.
- **Constructor injection** for all dependencies. No DI frameworks. No singletons.
- **Protocols (`typing.Protocol`)** for all interfaces. Never use ABC.
- **Pydantic** for all data models. Use `frozen=True` for immutable models.
- **Async/await** throughout. No blocking calls in async code.

### Code Quality

- **No `utils/`, `helpers/`, or `common/` dumping grounds.** If shared, it goes in `core/` or `models/`.
- **No inheritance hierarchies deeper than 2.**
- **No God classes.** Each class has one responsibility.
- **No ORMs.** Use raw SQL with the thin repository layer in `src/repositories/`.
- **No premature abstractions.** Only abstract what has 2+ implementations TODAY.
- **No magic.** No metaclasses, no decorators that hide control flow, no implicit registration.
- **No `Any` type.** Be explicit with types. Use `dict[str, ...]` not `dict`.

### Naming Conventions

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: `_single_underscore` prefix
- Type aliases: `PascalCase` via `NewType`

### File Rules

- One public class per file (helpers/private classes are fine in the same file).
- Maximum ~300 lines per file. Split if larger.
- Imports: stdlib first, then third-party, then local. Sorted alphabetically within groups.
- Use `from __future__ import annotations` in every file.

### Testing

- Tests mirror `src/` structure under `tests/unit/` and `tests/integration/`.
- Unit tests mock via Protocol injection — no monkeypatching.
- Integration tests use real SQLite database.
- Every public function must be testable without network calls.

### Git Workflow

- `main` branch is always deployable.
- Feature branches: `feature/<issue-number>-<short-description>`
- Each feature maps to a GitHub issue.
- PR required for each feature. User reviews and approves before merge.
- Commit messages: imperative mood, concise. Reference issue number.

### Platform Adapters

- Every new platform = one new directory under `src/platform/`.
- Must implement `PlatformAdapter` protocol (or relevant sub-protocols).
- Platform-specific code NEVER leaks outside its adapter directory.
- All platform adapters produce/consume the same `src/models/` types.

### Event System

- Events are the ONLY cross-department communication mechanism.
- All events inherit from the base `Event` model.
- Event names: `snake_case` (e.g., `job_discovered`, `proposal_drafted`).
- Handlers must be async and idempotent.
- Never block the event bus — long tasks should be spawned as background tasks.

### Config

- All config via `config.yaml` + environment variable overrides.
- Secrets ALWAYS via environment variables, NEVER in config files.
- Use `${VAR_NAME}` syntax in config.yaml for env var substitution.

### Dependencies

- Minimize dependencies. Prefer stdlib when possible.
- Pin exact versions in `pyproject.toml`.
- No dependency should pull in more than it gives.

---

## Project Structure

```
src/
├── core/           # Shared kernel (config, events, db, logging)
├── models/         # Pydantic domain models
├── platform/       # Platform adapters (upwork/, freelancer/, etc.)
├── departments/    # 7 CrewAI departments (ceo/, recon/, analyst/, etc.)
├── repositories/   # Thin SQL data access layer
└── api/            # FastAPI internal API for dashboard
```

## Department Communication

Departments communicate ONLY via the event bus:
```
Recon -> job_discovered -> Analyst
Analyst -> job_scored -> BizDev
BizDev -> bid_decided -> Content
Content -> proposal_drafted -> Execution
Execution -> proposal_submitted -> Learning
Learning -> insight_generated -> [Analyst, BizDev, Content]
CEO subscribes to ALL events
```
