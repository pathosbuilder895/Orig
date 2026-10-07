# Research Documentation

This directory contains research briefs that inform Original + Bluebook design decisions. Each brief follows a standard header format so research results can be traced and re-checked.

## Header Convention

Every research brief should include these fields in a table at the top:

| | |
|---|---|
| **Tool** | Which tool produced the research (e.g., Perplexity, Grok Bot, Claude Code with web search) |
| **Date** | Date the research was conducted (YYYY-MM-DD format preferred) |
| **Question** | The specific question asked or research objective |
| **Decision it informs** | Which decision, feature, ADR, or doc section this research supports. Include paths and section references. |

**Optional fields** may include:
- **Proposed repo path**: Where the research brief should be saved (if not yet saved)
- **Sources**: Key citations or URLs if not listed inline

## Example Header

```markdown
# Hosting and data storage for the Original + Bluebook pilot

| | |
|---|---|
| **Tool** | Perplexity Pro |
| **Date** | 2026-10-07 |
| **Question** | What does Original + Bluebook need to host and store data for a small independent-teacher pilot? |
| **Decision it informs** | NORTH_STAR "Current phase": hosting and budget. `docs/release/VERIFICATION_AND_BLOCKERS.md` items B1, B3. |
```

## Purpose

This header convention ensures:
1. **Traceability**: Each research brief's origins and purpose are clear
2. **Re-verification**: Research can be re-run or updated with the same question
3. **Decision tracking**: It's clear which decisions rest on which research
4. **Tool attribution**: Credit and capability tracking for different AI tools

## File Naming

Research files should follow the pattern:
- Date-prefixed: `YYYY-MM-DD-topic-name.md` (e.g., `2026-10-07-hosting-and-storage.md`)
- Or topic-prefixed: `TOPIC_NAME_FINDINGS_YYYY-MM-DD.md` (existing convention)

Both patterns are acceptable. Choose the one that best fits your research.

## When to Create Research Briefs

Create a research brief when:
- Answering a specific technical or design question that affects implementation
- Evaluating options (hosting, libraries, approaches)
- Investigating literature or best practices
- Documenting decisions that need external evidence
- The user explicitly asks for research to be saved

Research is distinct from:
- **ADRs** (`docs/adr/`): decisions already made with context and consequences
- **Specs** (`docs/superpowers/specs/`): detailed implementation specifications
- **Plans** (`docs/superpowers/plans/`): execution plans for specific work efforts
