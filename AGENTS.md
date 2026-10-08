# ADC_08 agent guidance

利用者の依頼を優先する。

- 設計・保存契約・AI文脈・作業手順の変更は `docs/program-vault/00-AI-Entry.md` から必要な参照だけ読む。小さなコード・文言修正は周辺コードだけでよい。全Vault・全索引・設計書を先読みしない。
- 不明な参照は `python scripts/retrieve_memory.py "検索語"`。既定は要約3件・1,200文字。根拠本文はID・見出しで絞り、`--excerpts`（既定8,000文字）で取得する。
- 現行アプリは `Source_code/`。`scripts/0903_adc/` は明示された場合だけ扱う。
- 無関係な変更を維持する。挙動変更前に対象コードと直接の呼出元・テストを読む。最小の検証を行い、今回の変更による失敗は直し、残る制約を報告する。
- `.env`・`key/`・秘密・生export・DB・uploads・mediaを出力・コピー・索引化・コミットしない。秘密は環境変数かGit対象外の鍵ファイルで渡す。
- ADCのObsidian作業は `adc-obsidian-memory` を使う。Gurumoji用は適用しない。
- 実験開始前に `docs/analysis-vault/00-AI-Entry.md` の保存手順でrunを作り、試験コード・条件・図表・結果・発表用メモを保持する。
- 分析相談では必要な担当だけに委任する。3人への相談が指定されたら全員の結果を統合する。役割と編集分担は `docs/analysis-vault/30-Orchestrators/team.md`。
