---
note_id: adc-output-entry
vault_kind: output
note_type: router
title: アウトプットの入口
summary: 分析結果と発表資料のカタログから必要な根拠だけを探す。
revision: 1
status: current
updated: 2026-09-24
---

# アウトプットの入口

- 結果・図表を探す：[[00-Index]] の該当行、または `python scripts/retrieve_memory.py "検索語" --vault output --summaries`。
- 結果を登録する：[[20-Workflows/register-output]] と [[90-Templates/result]]。
- 発表資料：索引の `20-Presentations/` の該当ノート。
- 実験条件・改善理由：カタログのrun IDからregistryで分析Vaultを選び、`10-Experiments/<run_id>.md`を読む。

原データを自動取り込みしない。索引には短い説明とIDを置き、必要な図表だけを参照する。
