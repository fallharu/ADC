---
note_id: adc-context-retrieval
vault_kind: software
note_type: workflow
title: Context retrieval
summary: 1Vaultの要約を検索し、ID・種類・見出しで必要な根拠だけを取得する。
revision: 3
status: current
updated: 2026-09-24
---

# Context retrieval

対象が分かる場合は直接参照する。不明な場合だけ、1つのVaultで候補を探す。全Vaultや成果物の一括読込みは行わない。

## 候補を探す

```powershell
python scripts/retrieve_memory.py "実験結果を保存する" --vault analysis
python scripts/retrieve_memory.py "速度" --vault analysis --type experiment
```

既定は要約3件・最大1,200文字。ID・Vault相対パス・版・ノート種類・状態・要約を1回だけ表示する。`--summaries` は既定動作を明示する互換オプション。`--vault` は software（既定）/ output / analysis。`--root` で明示した別Vaultも使えるが、`--vault` とは併用しない。

日本語は文字種による分割と漢字の2文字単位の部分一致で検索し、全角英数字は正規化する。`aliases`・`tags` も候補検索に使える（1行リスト・複数行リスト）。意味検索ではないので、別表現はaliasesへ登録するか、短いキーワードを使う。`--type` は完全一致で複数指定可能。検索語なしでも種類別の候補一覧を得られる。順位同点はパス順で、最新順ではない。

## 必要な根拠を読む

```powershell
python scripts/retrieve_memory.py --vault analysis --id adc-experiment-lifecycle --section "終了と引継ぎ"
python scripts/retrieve_memory.py --vault analysis --id adc-experiment-lifecycle --excerpts --max-chars 2000
```

`--id` はnote_idの完全一致。検索語・種類を併用すると全条件で絞る。同じIDの重複はエラーにする。任意のファイルパスをIDとして開かない。

`--section` は `#` 形式の見出し名（#記号を除く）の完全一致で、大文字小文字・全角半角を正規化する。その節と下位節だけを取得し、同階層の次の節で止める。コードブロック内の見出しは対象外。同名の見出しが複数あれば曖昧さをエラーで知らせる。下線形式の見出しには対応しない。

`--section` は本文取得を意味し、`--summaries` とは併用しない。`--excerpts` または `--section` の既定上限は8,000文字。各ノートに表示枠を配分し、切れた抜粋には「…」を付ける。枠に収まらないノートや件数超過は `omitted=N` として知らせる。3件・8,000文字は必ず消費する量ではない。

## 来歴・状態・対象外

- `--provenance` を付けたときだけSHA-256を表示する。計算対象は選択節ではなく元ノート全体（UTF-8、改行は読込み時に正規化）。表示した版・ハッシュと元ノートが一致するか、根拠を再利用する際に確認する。自動キャッシュはない。
- stale / superseded / archived / deleted / unverifiedと `99-Archive` は既定で除外。`--include-archive` で明示的に取得できるが、検証済みの意味にはならない。
- `80-Artifacts`・`90-Templates`・隠しフォルダー・秘密・生データの既定除外はID指定でも解除しない。
- 文字数の上限はトークン数ではない。検索はローカルで、結果の外部送信を許可するものではない。

## 記録と検証

ノートは短い `summary`、安定した `note_id`、`revision`・`status`・`updated` を持つ。更新は該当ノートと索引行だけに限定し、人の本文を維持する。

旧コマンドの本文表示が必要なら `--excerpts` を追加する。今回は既定の表示だけを要約へ変更し、保存先とIDは維持する。検索の検証は `tests/test_retrieve_memory.py`。作業全体の節約率は、同じ依頼の総トークン・再検索回数・正答率で別途測る。
