# 追い越し判定ロジックの詳細

本書では、後処理パイプラインの「追い越し」ステップ (`assign_overtake`) がどのように Detection テーブルへフラグや追い越しイベント
を保存しているかを段階的に説明します。

## 1. 前処理と対象クラスの決定

1. `.env` から自動車・自転車クラス名を読み込みます。既定値は `car` と `bicycle` で、カンマ区切りで複数指定できます (`OVERTAKE_CAR_CLASSES` / `OVERTAKE_BICYCLE_CLASSES`)。【F:Source_code/modules/overtake.py†L311-L333】
2. 指定 Run (`run_id`) に属する検出行の `overtake` / `overtake_after` / `overtake_window_offset` / `overtake_by` / `overtake_by_second` を一度リセットします。【F:Source_code/modules/overtake.py†L326-L339】
3. 対象 Run のフレームレートを取得し、クラス名を付与した検出データ（`model_name != 'best'` のみ）を読み込みます。【F:Source_code/modules/overtake.py†L341-L384】

## 2. 追い越し候補の抽出

1. 自動車・自転車のクラスだけに絞り込み、中心座標 (`center_x`, `center_y`) を算出します。【F:Source_code/modules/overtake.py†L65-L79】
2. `group_id` ごとに代表クラスを決め、Run 内の全グループの組み合わせを走査します。【F:Source_code/modules/overtake.py†L420-L512】
3. 自動車と自転車のペアに該当する場合だけ、共通フレームを抜き出してバウンディングボックスを結合し、左右方向の距離が車両幅のおよそ2倍以内となる並走フレームを抽出します。【F:Source_code/modules/overtake.py†L514-L528】

## 3. 追い越し成立の判定

1. 並走区間で自転車と自動車の計測点 `measure_y`（欠測時はボックス下辺）が入れ替わるフレームを検出します。自動車側の `relative_y` が自転車より大きい（後方）状態から小さい（前方）状態へ変わった瞬間が追い越し成立です。【F:Source_code/modules/overtake.py†L399-L409】【F:Source_code/modules/overtake.py†L544-L555】
2. 該当フレームごとに自動車側の検出行 (`auto_id`) を特定し、直前直後5秒分の速度プロファイルを抽出して辞書化します。速度が未計測のフレームは `null` で保存されます。【F:Source_code/modules/overtake.py†L586-L599】
3. 検出した瞬間ごとに、自動車と自転車の検出行（`auto_id`）を取得し、自転車側の `auto_id` ごとに追い越した車両グループIDと自転車自身のグループIDを更新候補として蓄えます。併せて、接近距離・離隔距離・白線距離などの関連数値も取り出してイベント保存用に保持します。【F:Source_code/modules/overtake.py†L576-L660】

## 4. データベース更新

1. 準備した自転車側 `auto_id` ごとの更新内容を `overtake = 1` / `overtake_after = 0` とし、`overtake_by` に追い越した車両（自動車）の `group_id`、`overtake_by_second` に自転車自身の `group_id` を書き戻します。【F:Source_code/modules/overtake.py†L646-L658】
2. 追い越し成立フレームを中心に前後30フレームの自転車行 `auto_id` へ相対カウントを記録し、`overtake_window_offset` として保存します（追い越し直前は負、直後は正の値）。【F:Source_code/modules/overtake.py†L440-L476】【F:Source_code/modules/overtake.py†L667-L675】
3. 追い越し後に同じ自転車が後方に残り続けるフレームについては `overtake_after = 1` を付与し、追い越し後区間を識別できるようにします。【F:Source_code/modules/overtake.py†L661-L665】
4. 同じ Run の過去イベントを削除し、今回検出した追い越しイベントを `OvertakeEvents` テーブルへ一括挿入します。挿入時には自動車・自転車の `auto_id` と接近距離・離隔距離・白線距離を含めて保存します。【F:Source_code/modules/overtake.py†L677-L685】
5. 更新件数とイベント数をログへ出力して処理を終了します。【F:Source_code/modules/overtake.py†L684-L687】

## 5. DBへ保存されるカラムと値

追い越し処理では Detection テーブルの複数列と `OvertakeEvents` テーブルに値が書き込まれます。列名と役割の関係は次のとおりです。

| テーブル | カラム | 値の内容 | 書き込み対象 | 備考 |
| --- | --- | --- | --- | --- |
| Detection | `overtake` | 追い越しが成立した瞬間の自転車行だけ 1 を付与 | 自転車側 `auto_id` | 同じ自転車が複数回追い越されると、その都度該当フレームのみ 1 になります。【F:Source_code/modules/overtake.py†L646-L658】 |
| Detection | `overtake_after` | 追い越し成立後に同じ自転車が後方に残っているフレームを 1 でマーキング | 自転車側 `auto_id` 群 | 追い越し後区間を識別するための継続フラグです。【F:Source_code/modules/overtake.py†L661-L665】 |
| Detection | `overtake_window_offset` | 追い越しフレームを 0 としたときの相対フレーム番号 | 自転車側 `auto_id` | ±30 フレーム内で最も 0 に近い値が保存され、複数イベントが重なる場合は絶対値が小さい方で上書きされます。【F:Source_code/modules/overtake.py†L440-L476】【F:Source_code/modules/overtake.py†L667-L675】 |
| Detection | `overtake_by` | 追い越しを行った自動車の `group_id` | 追い越しフレームの自転車行 | 自転車から見た「誰に追い越されたか」を表す値です。【F:Source_code/modules/overtake.py†L646-L658】 |
| Detection | `overtake_by_second` | 追い越された自転車（自分自身）の `group_id` | 追い越しフレームの自転車行 | `overtake_by` とセットで相手と自分を対応付けます。【F:Source_code/modules/overtake.py†L646-L658】 |
| OvertakeEvents | `event_frame_num` | 追い越しが成立したフレーム番号 | 各イベント行 | Run 内での時系列を復元する際に利用します。【F:Source_code/modules/overtake.py†L677-L685】 |
| OvertakeEvents | `overtaker_group_id` / `overtaken_group_id` | 追い越した自動車と追い越された自転車の `group_id` | 各イベント行 | Detection テーブルの `overtake_by` / `overtake_by_second` と同じ組み合わせです。【F:Source_code/modules/overtake.py†L677-L685】 |
| OvertakeEvents | `overtaker_auto_id` / `overtaken_auto_id` | 成立フレームの自動車・自転車 `auto_id` | 各イベント行 | 個々の検出行へ直接アクセスしたいときの識別子です。【F:Source_code/modules/overtake.py†L648-L685】 |
| OvertakeEvents | `approach_distance_px` / `approach_distance_m` | 成立フレームにおける接近距離 | 各イベント行 | `assign_approach_and_clearance` の結果を転記しています。【F:Source_code/modules/overtake.py†L648-L685】 |
| OvertakeEvents | `clearance_distance_px` / `clearance_distance_m` / `clearance_distance_cm` | 追い越し瞬間の離隔距離 | 各イベント行 | スナップショット描画や後続分析で利用できます。【F:Source_code/modules/overtake.py†L648-L685】 |
| OvertakeEvents | `l_line_distance` / `r_line_distance` / `line_distance` | 成立フレームの白線との距離 | 各イベント行 | キャリブレーション情報がある場合に保存されます。【F:Source_code/modules/overtake.py†L648-L685】 |
| OvertakeEvents | `speed_profile_json` | 追い越し前後 5 秒（±`fps × 5` フレーム）分の自動車速度を 0.1 秒刻みで記録した JSON | 各イベント行 | 欠測速度は `null` として保存され、後段の解析やレポート出力で参照できます。【F:Source_code/modules/overtake.py†L586-L599】【F:Source_code/modules/overtake.py†L648-L685】 |

`OvertakeEvents` は Run ごとに再作成されるため、再処理時は既存行を削除したうえで最新イベントだけが保持されます。【F:Source_code/modules/overtake.py†L677-L683】 Detection テーブル側の各列は後続の検索画面・CSV 出力・統計処理からそのまま参照され、追い越し相手の組み合わせやタイムラインを即座に把握できるようになっています。

## 6. スナップショット出力

追い越し成立時には元フレームへバウンディングボックスや離隔距離ラベル、白線との距離表示を描画した画像を `overtake_snapshots` フォルダに保存します。【F:Source_code/modules/overtake.py†L82-L288】【F:Source_code/modules/overtake.py†L289-L304】

## よくある質問

- **`overtake` や `overtake_after` の違いは？**
  自転車と自動車の組み合わせで縦方向の位置が入れ替わった瞬間の自転車行だけ `overtake = 1` になります。追い越しが成立した後に同じ自転車が後方に残るフレームは `overtake_after = 1` が立ち、2回目以降の追い越しが起きれば再びその瞬間だけ `overtake = 1` になります。速度しきい値は利用していません。

- **`overtake_by` / `overtake_by_second` が NULL のままになるケース**
  同一 Run に自動車と自転車の両方が存在しない場合、もしくは並走して位置が入れ替わる条件を満たさない場合は NULL のままです。追い越しが成立すると `overtake_by` に自動車の `group_id`、`overtake_by_second` に自転車自身の `group_id` が必ず書き込まれます。

- **対象クラスを追加したい**  
  `.env` の `OVERTAKE_CAR_CLASSES` / `OVERTAKE_BICYCLE_CLASSES` にカンマ区切りでクラス名を指定すると、環境に合わせて追い越し対象を拡張できます。
