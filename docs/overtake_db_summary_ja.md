# 追い越し処理とDB書き込み内容の概要

このメモでは、後処理ステップ `assign_overtake` がどのように追い越しイベントを検知し、どのカラムへ値を保存するかを簡潔に整理します。詳細なロジックは `docs/overtake_processing_ja.md` を参照してください。

## 対象クラスの決定と前処理
- `.env` の `OVERTAKE_CAR_CLASSES`（既定: `car`）と `OVERTAKE_BICYCLE_CLASSES`（既定: `bicycle`）を読み込み、自動車・自転車に該当するクラス名の集合を作成します。【F:Source_code/modules/overtake.py†L14-L38】
- 対象 Run の Detection 行から既存の `overtake` / `overtake_after` / `overtake_window_offset` / `overtake_by` / `overtake_by_second` をクリアし、後続の計算に備えます。【F:Source_code/modules/overtake.py†L40-L57】

## 追い越しイベントの検出手順
1. Detection と Class を結合し、Run 内で車両グループ（`group_id`）ごとの軌跡を抽出します。【F:Source_code/modules/overtake.py†L58-L83】
2. 自動車と自転車の組み合わせだけを残し、横方向に並走している区間を判定します。【F:Source_code/modules/overtake.py†L85-L137】
3. 並走区間で `center_y` の前後関係が反転したフレームが追い越し成立フレームです。成立フレームの自転車側 `auto_id` を控え、後でまとめてDBへ書き戻します。【F:Source_code/modules/overtake.py†L139-L208】

## Detectionテーブルへ書き込む値
| カラム | 内容 | 更新対象 |
| --- | --- | --- |
| `overtake` | 追い越しが成立した瞬間の自転車側 `auto_id` に 1 を設定します。 | 成立フレームの自転車行【F:Source_code/modules/overtake.py†L210-L296】 |
| `overtake_after` | 追い越し成立後、同じ自転車が後方に残っているフレームを 1 でマーキングします。 | 追い越し後区間の自転車行【F:Source_code/modules/overtake.py†L182-L308】 |
| `overtake_window_offset` | 追い越しフレームを基準0とした±30フレームの相対オフセット値です。自転車側 `auto_id` に対して最も近いイベントのオフセットが保存されます。【F:Source_code/modules/overtake.py†L124-L332】 |
| `overtake_by` | 追い越しを行った自動車の `group_id` を追い越し瞬間の自転車行に保存します。 | 自転車行【F:Source_code/modules/overtake.py†L210-L296】 |
| `overtake_by_second` | 追い越された自転車（自分自身）の `group_id` を追い越し瞬間の自転車行に保存します。 | 自転車行【F:Source_code/modules/overtake.py†L210-L296】 |

## OvertakeEventsテーブルへの保存内容
- 既存の Run 行を削除したあと、新たに検出したイベントを挿入します。【F:Source_code/modules/overtake.py†L252-L288】
- 保存する列は以下のとおりです。
  - `run_id` / `event_frame_num`: イベントの属する Run とフレーム番号。
  - `overtaker_group_id` / `overtaken_group_id`: 追い越した自動車と追い越された自転車の `group_id`。【F:Source_code/modules/overtake.py†L264-L288】
  - `overtaker_auto_id` / `overtaken_auto_id`: 成立フレームにおける自動車・自転車の `auto_id` を保持します。検出行とイベント行を直接突き合わせたいときに利用できます。【F:Source_code/modules/overtake.py†L612-L690】
  - `approach_distance_px` / `approach_distance_m`: 成立フレームの接近距離（ピクセル・メートル）。【F:Source_code/modules/overtake.py†L648-L690】
  - `clearance_distance_px` / `clearance_distance_m` / `clearance_distance_cm`: 追い越しフレームにおける離隔距離をそれぞれの単位で保存します。【F:Source_code/modules/overtake.py†L648-L690】
  - `l_line_distance` / `r_line_distance` / `line_distance`: キャリブレーション白線との距離（左・右・最短）。【F:Source_code/modules/overtake.py†L648-L690】
  - `speed_profile_json`: 追い越し前後約5秒間の自動車速度（km/h）を時刻キー付きのJSONで保存します。値が欠測の場合は `null` になります。【F:Source_code/modules/overtake.py†L180-L207】【F:Source_code/modules/overtake.py†L648-L690】

この処理により、追い越し相手の特定・時間的な前後関係・速度変化を DB 上で再現でき、CSV や統計モジュールからも同じデータを利用できます。
