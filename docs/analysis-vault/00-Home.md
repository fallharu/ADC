---
note_id: adc-analysis-home
vault_kind: analysis
note_type: home
title: ADC 分析改善Vault
summary: 分析の仮説から試験・改善判断・中間発表の根拠までを保存する場所。
revision: 1
status: current
updated: 2026-09-24
---

# ADC 分析改善Vault

この `docs/analysis-vault` フォルダーをObsidianの保管庫として開く。

- [[00-AI-Entry]]：目的から最小限のノートを探す
- [[00-Index]]：実験・改善判断の索引
- [[20-Workflows/experiment-lifecycle]]：一時プログラム・画像・分析結果の保存方法
- [[30-Orchestrators/team]]：3人の担当と相談の進め方
- [[40-Presentation/interim-presentation]]：中間発表の材料と構成

新しい実験はリポジトリ直下で `python scripts/new_analysis_run.py speed-smoothing --title "速度平滑化の比較"` として作る。これは保存先・計画ノートを作るコマンドで、分析は別途実行する。

`80-Artifacts` はローカルの保管場所。Gitにも通常のAI検索にも含めないが、自動削除しない。実験ノートにあるmanifestとslide-cardのリンクから開ける。
