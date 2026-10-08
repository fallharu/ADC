---
note_id: adc-ai-development-rules
vault_kind: software
note_type: design-rule
title: AI development rules
summary: Keep agent context small, retrieve locally, send only task-specific excerpts, and keep external providers and credentials opt-in.
revision: 3
status: current
updated: 2026-09-24
---

# AI development rules

## Context

- Keep `AGENTS.md` and skill descriptions short; use them as routers rather than manuals.
- Do not require a repository map or design-book read before every edit.
- Use `scripts/retrieve_memory.py` only when the relevant note is unknown. Defaults are three summaries and 1,200 characters; `--id` / `--section` select evidence, with `--excerpts` capped at 8,000 characters by default.
- Prefer compact statistics, selected rows, and named excerpts over full JSON/CSV serialization.
- Define completion in the task: implement, inspect the affected result, fix caused failures, and rerun the smallest relevant check.

## Obsidian

`docs/program-vault` is the Software Vault and Git is its revision authority. Markdown owns explanations and decisions; code/tests own behavior; SQLite/JSON/CSV own large structured data. Use stable `note_id` values and same-Vault Wikilinks. Do not make identity depend on a title or path.

Output catalogs belong to `docs/output-vault`; experiments and presentation evidence belong to `docs/analysis-vault`. Follow [[obsidian-vault-contract]] for storage work and [[20-Workflows/context-retrieval]] for search changes. Summaries locate evidence. Retrieve the needed source before relying on a result; load only the relevant Vault and advisors.

## External AI and dev provider

Local retrieval is the default. An external provider may receive only the rendered, task-specific context packet after explicit provider configuration. The provider name, endpoint, model, retention policy, and environment variable must be documented before enabling it.

The local secret file is ignored by Git. Its contents must not be copied into Markdown, `.env`, logs, indexes, prompts, or test fixtures. Configure only a file pointer such as `ADC_DEV_KEY_FILE`; read the secret at call time and never echo it. Until the provider is identified, remote dev retrieval remains disabled.

## Existing runtime AI

`Source_code/modules/ai_insight.py` currently uses `GOOGLE_API_KEY` and Gemini. Keep its runtime prompts separate from developer-memory retrieval. When reducing those prompts, compact input structures before generation and record provider-reported usage when available.
