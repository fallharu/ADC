---
note_id: adc-experiment-lifecycle
vault_kind: analysis
note_type: workflow
title: 分析実験の保存と改善
summary: 試験コード、実行条件、集計、図表、失敗理由を実験IDで保存しスライドへ引き継ぐ。
revision: 1
status: current
updated: 2026-09-24
---

# 分析実験の保存と改善

## 開始

1. 仮説、変更対象、比較する基準実装、指標・単位、成功基準を決める。
2. リポジトリ直下で `python scripts/new_analysis_run.py <short-slug> --title "実験名"` を実行する。再実験は `--parent-run-id <元のID>` を追加する。
3. 作成された実験ノートに計画を記入する。未実行は `planned` と明記し、数値を埋めない。

## 実験フォルダー

`80-Artifacts/<run_id>/` に以下を保存する。試験プログラムも将来の再現資料として保持する。

| 場所 | 内容 |
| --- | --- |
| `code/` | 今回の試験・描画用コード。既存コードはGit SHAと相対パスで参照し、未コミット変更は対象ファイルだけの差分または試験版を保存 |
| `config/` | 実行引数、Python・依存ライブラリ版、乱数seed、条件JSON。秘密を含めない |
| `tables/` | 匿名化した集計CSV/JSON。列名、単位、件数、欠損・除外条件を記録 |
| `figures/` | 分析・比較図。PNGに加えて可能ならSVG/PDF、図の元表と描画コード |
| `logs/` | 秘密と個人情報を除いた実行時間、終了コード、エラー要約 |
| `slides/` | `slide-card.md`、構成、発表者メモ、生成コード、後で作成するPPTX/PDF |
| `manifest.json` | 実験ID、由来、条件、成果物IDと相対パス・ハッシュ、検証状態 |

作成コマンドは空の保存先とテンプレートを用意する。実行・取り込み・数値検証・manifestの完成は分析担当が行う。現行Flaskの保存先を変更するフックではない。

## 実行と記録

- 実行コマンド、作業ディレクトリ、対象コードのGit SHAとdirty状態を記録する。dirtyの場合は対象差分を保存し、SHAだけで再現可能としない。
- 元データは匿名の `source_id` と版・ハッシュを参照する。原動画・DB・uploads・未加工exportをVaultへコピーしない。
- manifestの `parameters` に実際の比較条件を書く。`artifacts` は `artifact_id, path, kind, sha256, source_ids, command` を記録する。SHA-256は対象成果物だけに計算する。
- 図表のタイトル、軸・単位、凡例、標本数、比較対象、範囲、除外条件、不確実性を残す。画像だけで判断を保存しない。

## 終了と引継ぎ

1. 分析担当：実験ノートに観測結果・根拠ID・限界・検証コマンドを記入する。実行終了と検証完了は別に記録する。
2. 結果の `status` を `completed` / `failed` / `inconclusive` にし、`validation_status` を `unverified` / `verified` にする。失敗や効果なしも理由・ログ・次の案を残す。
3. 改善案は効果、実装コスト、リスク、比較根拠を示し、採用／保留／棄却と理由を記す。必要なら `15-Improvements/` に独立ノートを作る。
4. スライド担当：`slides/slide-card.md` に主張、根拠図表ID、説明、限界、発表者メモを記入する。未検証はその旨を表示する。
5. 整理担当：実験索引を更新し、共有可能な確認済み結果をOutput Vaultの `10-Results/` に登録する。根拠データをコピーせずrun IDとartifact IDを参照する。

`completed` の過去実験に別条件の結果を上書きしない。新実験から `parent_run_id` で結ぶ。条件変更の影響を受ける要約や発表原稿は `stale` として、再利用前に根拠を確認する。

保管は発表終了までに限定しない。利用者の削除指示があるまで試験コード・図表・結果を残す。
