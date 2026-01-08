# 検出データ項目リファレンス

本書は Detection テーブルおよび出力CSVに含まれる主要カラムの意味と算出元をまとめたものです。解析ロジックの概要を併記しているので、値の確認や集計条件を設定する際の参照にしてください。

## 距離系の指標

| カラム | 内容 | 算出モジュール |
| --- | --- | --- |
| `approach_distance_px` / `approach_distance_m` / `approach_distance_cm` | 自転車と自動車の最短距離。ピクセル値とスケール適用後のメートル・センチメートルを同時に保存します。 | `modules/approach_distance.assign_approach_and_clearance`【F:Source_code/modules/approach_distance/__init__.py†L16-L330】 |
| `clearance_distance_px` / `clearance_distance_m` / `clearance_distance_cm` | 追い越し判定フレームにおける離隔距離。追い越しイベントの相手グループを共有します。 | `modules/approach_distance.assign_approach_and_clearance`【F:Source_code/modules/approach_distance/__init__.py†L200-L330】 |
| `l_line_distance` / `r_line_distance` | 前輪の計測点と左右白線との水平距離（ピクセル）。白線形状と同じ高さでx座標を補間して算出し、白線が欠ける区間は従来の最短距離をフォールバックします。 | `modules/lane_distance.assign_lane_distance`【F:Source_code/modules/lane_distance/__init__.py†L1-L310】 |
| `line_distance` | 上記2値のうち小さい方。白線との最近接距離（水平）。 | 同上 |
| `approach_partner_group_id` | 接近距離を計算した相手グループID。 | `modules/approach_distance.assign_approach_and_clearance`【F:Source_code/modules/approach_distance/__init__.py†L204-L281】 |

## 速度・加速度関連

| カラム | 内容 | 算出モジュール |
| --- | --- | --- |
| `pixel_speed` | スケール補正前の移動速度（px/s）。平滑化したバウンディングボックス中心の差分をFPSで割って算出します。 | `modules/speed.assign_kinematics`【F:Source_code/modules/speed/__init__.py†L94-L213】 |
| `speed_km_h` | スケール適用後の速度（km/h）。キャリブレーションスケールでピクセル差をメートルへ変換して算出します。 | 同上【F:Source_code/modules/speed/__init__.py†L166-L257】 |
| `acceleration_m_s2` | 1秒（FPS分）の速度差から求める加速度。 | 同上【F:Source_code/modules/speed/__init__.py†L214-L247】 |
| `acceleration_state` | 加速・減速・巡航の区分。しきい値は `ACCEL_THRESHOLD` / `DECEL_THRESHOLD` を使用します。 | 同上【F:Source_code/modules/speed/__init__.py†L214-L252】 |
| `scale_pixels_per_meter` / `x_pixels_per_meter` | キャリブレーションから得た縦・横方向のスケール値。速度や距離換算で利用します。 | 同上【F:Source_code/modules/speed/__init__.py†L121-L206】 |

## 判定フラグ

| カラム | 内容 | 算出モジュール |
| --- | --- | --- |
| `overtake` / `overtake_after` / `overtake_by` / `overtake_by_second` | 自転車行を中心に追い越し瞬間を示すフラグ群。`overtake` は交差したフレームの自転車行だけが1になり、同じ自転車が追い越された後のフレームは `overtake_after` が1になります。追い越しが成立すると `overtake_by` に追い越した車両（自動車）の `group_id`、`overtake_by_second` に自転車自身の `group_id` を保存します。 | `modules/overtake.assign_overtake`【F:Source_code/modules/overtake.py†L18-L304】 |
| `overtake_window_offset` | 追い越し成立フレームを0として、自転車行の前後30フレームを相対カウントした値。マイナスは追い越し前、プラスは追い越し後のフレームを示します。 | `modules/overtake.assign_overtake`【F:Source_code/modules/overtake.py†L124-L340】 |
| `oncoming_flag` | 上方向と下方向の移動が交差したフレームで1を設定。自転車と車の組合せを解析する際に進行方向が異なる場合に付与します。 | `modules/approach_distance.assign_approach_and_clearance`【F:Source_code/modules/approach_distance/__init__.py†L168-L332】 |
| `lane_position_flag` | タイヤ計測点が白線内側なら「+」、外側なら「-」。レーンポリゴンを用いて判定。 | `modules/lane_distance.assign_lane_distance`【F:Source_code/modules/lane_distance/__init__.py†L40-L310】 |
| `travel_direction` | `R`（上方向）/`L`（下方向）などの進行向き。グループ単位の速度投票により決定します。 | `modules/speed.assign_kinematics`【F:Source_code/modules/speed/__init__.py†L200-L252】 |

## 車種・分類とメタ情報

| カラム | 内容 | 算出モジュール |
| --- | --- | --- |
| `class_id` / `class_name` | YOLO検出クラスをClassテーブルに保存。車種比較はこの値で行います。 | `modules/inference.process_video`【F:Source_code/modules/inference.py†L120-L340】 |
| `group_id` | トラッキング後の車両・自転車ごとのグループID。 | `modules/grouping` 等（後処理ステップ）【F:Source_code/modules/approach_distance/__init__.py†L190-L276】 |
| `folder_alias` / `output_folder` | Run単位の出力先とフォルダ名。集計時の比較単位として利用できます。 | `modules/db_manager.create_process_log`【F:Source_code/modules/db_manager.py†L506-L760】 |

## 備考

- 路肩拡幅の有無は現在DBカラムとして保持していません。必要な場合はキャリブレーション設定やRunメモ（フォルダエイリアス等）で管理してください。今後専用フラグを追加する余地があります。
- CSV出力時は `db/csv_output_columns_description.csv` の一覧をヘッダーとして書き出します。Run毎のエクスポートは `modules/all_save.create_all_save` を参照してください。【F:db/csv_output_columns_description.csv†L1-L32】【F:Source_code/modules/all_save.py†L19-L122】
- フォルダ一括出力では `modules/all_save.create_combined_detection_csv` がRun一覧を結合し、各行の末尾に `video_filename` 列を付与したまとめCSVも生成します。【F:Source_code/modules/all_save.py†L122-L210】【F:Source_code/routes.py†L554-L618】
- 走行方向に応じた対向車検知は `oncoming_flag` と `travel_direction` を組み合わせることで集計可能です。白線距離は水平距離なので、レーン幅の比較では同一高さを基準にできます。

