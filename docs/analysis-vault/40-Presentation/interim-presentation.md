---
note_id: adc-interim-presentation
vault_kind: analysis
note_type: workflow
title: 中間発表の準備
summary: 実験ごとに主張・比較図・根拠・限界を残し、後から中間発表スライドへ組み立てる。
revision: 1
status: current
updated: 2026-09-24
---

# 中間発表の準備

現時点では発表日・枚数・形式を決めず、実験ごとに材料を残す。

## 1つの実験から残す材料

- 伝えることを1文で書いたスライド見出し
- 問題と改善方法、比較対象、同じ条件で比較できる根拠
- 主張の根拠となるrun ID・artifact ID・元データ版
- 元表、描画コード、PNGと可能ならSVG/PDF、単位・標本数・誤差
- 改善前後の値、効果なし・失敗も含む判断、適用できる条件と限界
- 口頭で補う説明、残る課題、次に試すこと

実験作成時に `80-Artifacts/<run_id>/slides/slide-card.md` が作られる。ひな形は [[90-Templates/slide-card]]。

## 発表を作るとき

背景 → ADCの現状と課題 → 評価条件 → 改善方法 → 結果 → 限界 → 今後の計画を基本に、発表時間に合わせて選ぶ。結果1件を無条件に1枚にする必要はない。

`planned` は計画として、`failed` は失敗の知見として提示できる。未検証の数値を確定結果にしない。`stale` の図表は再確認するまで結果スライドに採用しない。

発表の保存場所は `docs/output-vault/80-Artifacts/<presentation_id>/`。編集可能なPPTXまたは元Markdown、生成スクリプト、PDF、発表者メモ、スライド番号とrun/artifact IDを結ぶ `sources.json` を保持する。カタログはOutput Vaultの `20-Presentations/` に置く。
