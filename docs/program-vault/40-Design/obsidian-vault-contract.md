---
note_id: adc-vault-contract
vault_kind: software
note_type: design-rule
title: ADCのObsidian保存ルール
summary: 3つのVaultの役割、トークン節約、実験成果物と中間発表資料の保存契約。
revision: 3
status: current
updated: 2026-09-24
---

# ADCのObsidian保存ルール

ADCの保存・索引・実験記録には `adc-obsidian-memory` を使う。`gurumoji-obsidian-memory` はGurumoji専用。この文書とADCの実装が保存契約の正本であり、スキルは必要な文書への案内と適用判断を担う。

## 保存先と正本

配置の機械可読な正本はリポジトリ直下を基準とする `docs/vault-registry.json`。各フォルダーをObsidianで「保管庫として開く」。入れ子のVaultは作らない。

| Vault | フォルダー | 保存する知識 | 実データの正本 |
| --- | --- | --- | --- |
| プログラム | `docs/program-vault` | ADC索引、入口、仕様差分、設計判断、開発ルール | `Source_code/`、直接のテスト、Git |
| アウトプット | `docs/output-vault` | 結果カタログ、指標の意味、図表の説明、検証状態、発表資料への参照 | 既存の出力先、または各Vaultの `80-Artifacts/` |
| 分析改善 | `docs/analysis-vault` | 仮説、実験記録、改善案、失敗理由、担当者の相談、スライド構成 | `80-Artifacts/<run_id>/` の試験コード・条件・集計結果・図表・manifest |

Flaskの `db/`・`uploads/`・`output/`、既存分析スクリプトと成果物は移動しない。新しいルールは今後の実験から適用する。既存成果物は必要な実験だけ、元の保存場所を参照して登録する。GurumojiのVaultRegistryやAnalysisStoreをADCの実装済み機能として扱わない。

## トークンを節約する索引

入口 → 目的別の索引行 → 該当ノートの要約 → 必要な本文・コードの順に読む。全Vault・設計書・実データの一括読込みを避ける。

- 索引行は `note_id / 1文のsummary / status / 同じVaultのリンク`。
- 検索は1つのVaultに限定し、既定は要約3件・1,200文字。根拠は `--id`・`--type`・`--section` で絞り、`--excerpts`（既定8,000文字）で取得する。詳細は [[20-Workflows/context-retrieval]]。
- `80-Artifacts`、`90-Templates`、`.obsidian`、生データ、秘密情報は通常検索から除外する。古い判断は `stale` / `superseded` または `99-Archive` へ。
- メモには必要な集計・判断と根拠IDを置く。CSV/JSON全体、DB、ログ、画像の内容を索引に複製しない。

## IDと成果物

ノート共通属性は `note_id, vault_kind, note_type, title, summary, revision, status, updated`。実験は `run_id`、結果は `source_ids, artifact_ids` も持つ。

- `run_id` は作成日時（UTC）・短い用途名・ランダムIDから生成し、実行後に改名しない。
- 実験ノートは分析Vaultの `10-Experiments/<run_id>.md`、manifestは `80-Artifacts/<run_id>/manifest.json`。この対応でrun IDを解決する。
- `artifact_id` は `<run_id>:<役割名>`。manifestの `artifacts` にID、実験フォルダー相対path、種類、SHA-256、生成コマンド、元データIDを記録する。既存成果物を参照する場合は別フィールド `external_repo_path`（リポジトリ相対）を使う。
- Vault間は `run_id`・`note_id`・`artifact_id` とregistryで結ぶ。Vaultを跨ぐWikilinkを使わない。Vault内の画像は相対Markdownリンクで表示できる。
- 条件や元データが変わった再実験は新IDにし、`parent_run_id` を記録する。過去結果を上書きしない。依存する出力・スライドの状態を `stale` にする。

## 保持と編集

`80-Artifacts/` はGit・検索から除外するが、掃除対象の一時領域ではない。試験コード・図表・集計・スライド原稿は中間発表が終わっても明示的な削除指示まで保持する。Gitには一般化したルール・テンプレート・個人情報を除いた要約を置く。Gitに入らない成果物は、利用者が管理するローカルバックアップにも含める。自動クラウド送信は設定しない。

秘密、原動画、アップロード、DB、未加工exportは既存の管理場所に保持する。今後生成する匿名化した分析図表や試験成果物は実験フォルダーへ直接保存する。既存の生データを収集・複製する理由にはしない。

人の本文・タグ・別名を維持し、ノート更新時はrevisionとupdatedを進める。索引を更新する担当は1人に限定し、競合を上書きで解消しない。同期や整理から分析・AI・外部送信を自動起動しない。

## 互換性と検証

今回の追加は既存パス・ノートID・Flask保存処理を変更しない。従来の検索コマンドと `--root` は引き続き使用できる。新Vaultの利用を止める場合も既存のSoftware Vaultと元データはそのまま読める。保存済み実験は削除せず保持し、設定変更前に該当ノートとmanifestをバックアップする。

保存支援と検索の検証は一時ディレクトリで行う。通常検索で成果物が読まれないこと、ID衝突で上書きしないこと、runと図表の参照が解決できることを確認する。
