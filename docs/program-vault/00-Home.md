---
note_id: adc-software-home
vault_kind: software
note_type: home
title: ADC_08 Software Vault
summary: Human entry point for the ADC_08 architecture, decisions, and AI development context.
revision: 3
status: current
updated: 2026-09-26
---

# ADC_08 Software Vault

This folder is the Obsidian Vault for human-readable project knowledge. Source code, tests, Git history, SQLite databases, generated reports, and large data files remain authoritative in their existing locations.

## Start here

- AI or coding agent: [[00-AI-Entry]]
- Note catalog: [[00-Index]]
- Current workspace changes: [[30-Development/2026-09-26-worktree-change-record]]
- Context and token policy: [[40-Design/ai-development-rules]]
- Retrieval workflow: [[20-Workflows/context-retrieval]]
- Three-Vault storage rules: [[40-Design/obsidian-vault-contract]]

Open `docs/program-vault` as its own Obsidian Vault. Personal `.obsidian` settings are ignored by Git.

## Boundaries

- Store durable decisions and compact explanations here.
- Link to code and artifacts; do not copy large JSON, CSV, logs, databases, or generated HTML into notes.
- Never store credentials, personal information, raw uploads, or the contents of `.env` and `key/`.
