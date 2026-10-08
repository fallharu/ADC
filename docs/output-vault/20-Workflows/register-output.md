---
note_id: adc-register-output
vault_kind: output
note_type: workflow
title: 出力の登録
summary: 実験の根拠ID、検証状態、図表の意味を結果カタログに残す。
revision: 1
status: current
updated: 2026-09-24
---

# 出力の登録

1. 対象runの実験ノートと指定されたmanifestを確認する。結果と再現条件が揃い、検証済みのものを通常の結果カタログに登録する。
2. [[90-Templates/result]] を `10-Results/<note_id>.md` に作成し、プレースホルダーを実際の値に置き換える。
3. run ID、artifact ID、元データ版、コード版、比較条件、単位、件数、限界を残す。数値の根拠は成果物に置き、ノートには必要な集計だけを書く。
4. `00-Index.md` にID・1文の要約・状態・同じVaultのリンクを1行追加する。タイトルだけを根拠に既存ノートを上書きしない。
5. 古い根拠が更新された場合は関連する結果・発表ノートを `stale` にし、再確認するまで確定結果として再利用しない。

図表は元の実験に保持し、このVaultへ重複コピーしない。run IDは `docs/vault-registry.json` のanalysisルートと既定の実験ノート・manifestパスで解決する。発表は `20-Presentations/<presentation_id>.md` に使用run/artifact ID、スライド番号、出力先を記す。

未検証の既存結果を仮登録する必要がある場合は `status: unverified` と明示し、確認済みの検索結果に混ぜない。秘密・個人情報・未加工exportを要約や索引へ含めない。
