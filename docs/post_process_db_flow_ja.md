# 後処理ボタン押下後に実行されるDB更新フロー

## 全体像
`後処理を実行`ボタンを押すと、選択したRun IDの処理内容がキューへ登録され、ワーカーが順番に7段階のステップを実行します。ステップは常に同じ順序で呼び出され、各フェーズが完了するたびに進捗とカラムの集計結果がUIへ反映されます。【F:Source_code/routes.py†L367-L459】

各ステップはSQLiteのDetectionテーブルや関連テーブルを書き換え、後続の分析やエクスポートで利用できる派生データを保存します。ここではRun単位で実行される7ステップと、そのステップが格納する主なカラムを説明します。

## 1. グループID割当 (`assign_group_ids`)
- 対象: Detectionテーブル
- 内容: 既存の`group_id`をリセットし、推論時に得た`track_id`をベースに車両へ新しい`group_id`を割当。タイヤ（model_name=`best`）は同一フレーム内の車両バウンディングボックスへ突合し、対応する車両の`group_id`をコピーします。【F:Source_code/modules/group_id.py†L14-L90】
- 保存されるカラム: `group_id`

## 2. 運動学情報計算 (`assign_kinematics`)
- 対象: Detectionテーブル
- 内容: キャリブレーションに登録したスケール（縦スケール/ホモグラフィ/走行パス）を利用して各フレームの移動量をメートル換算し、速度・加速度・進行方向を算出します。速度の10フレーム最頻値平滑化と方向の投票補正を行ったのち、各車両行へ結果を保存します。【F:Source_code/modules/speed/__init__.py†L58-L263】【F:Source_code/modules/speed/__init__.py†L265-L282】
- 保存されるカラム: `travel_direction`, `scale_pixels_per_meter`, `pixel_speed`, `speed_km_h`, `acceleration_m_s2`, `acceleration_state`

## 3. 追い越し判定 (`assign_overtake`)
- 対象: Detectionテーブル, OvertakeEventsテーブル
- 内容: 自動車と自転車の`group_id`ペアを走査し、縦方向の位置が入れ替わった瞬間だけ自転車側の検出行に`overtake = 1`を付与します。同時に`overtake_after`や`overtake_window_offset`で追い越し前後のフレームをマーキングし、`overtake_by`へ追い越した自動車の`group_id`、`overtake_by_second`へ自転車自身の`group_id`を保存します。成立フレームでは両者の`auto_id`や接近距離・離隔距離・白線距離をまとめ、周辺10秒の速度プロファイルと一緒に`OvertakeEvents`へ書き込みます。【F:Source_code/modules/overtake.py†L14-L340】【F:Source_code/modules/overtake.py†L612-L685】
- 保存されるカラム: `overtake`, `overtake_after`, `overtake_window_offset`, `overtake_by`, `overtake_by_second`（Detection） / `OvertakeEvents`テーブルの `event_frame_num`, `overtaker_group_id`, `overtaken_group_id`, `overtaker_auto_id`, `overtaken_auto_id`, `approach_distance_px`, `approach_distance_m`, `clearance_distance_px`, `clearance_distance_m`, `clearance_distance_cm`, `l_line_distance`, `r_line_distance`, `line_distance`, `speed_profile_json`

## 4. 接近距離・離隔距離計算 (`assign_approach_and_clearance`)
- 対象: Detectionテーブル
- 内容: 自転車と自動車の前輪測定点を用いて各フレームの最短距離を算出し、接近距離・対向フラグを記録。追い越し中のフレームでは同じ組み合わせから離隔距離（px/m/cm）を抽出します。環境設定に基づく自転車/車のクラス振り分けや、グループ幅からのスケール推定も行われます。【F:Source_code/modules/approach_distance/__init__.py†L100-L244】【F:Source_code/modules/approach_distance/__init__.py†L248-L308】
- 保存されるカラム: `approach_distance_px`, `approach_distance_m`, `approach_partner_group_id`, `clearance_distance_px`, `clearance_distance_m`, `clearance_distance_cm`, `oncoming_flag`

## 5. 白線距離計算 (`assign_lane_distance`)
- 対象: Detectionテーブル
- 内容: キャリブレーションで指定した左右の白線ポリラインから、前輪測定点との水平方向距離を算出。左右距離と最短距離に加え、測定点が白線内側にあるかの判定（+/-）を決定して保存します。【F:Source_code/modules/lane_distance/__init__.py†L171-L248】【F:Source_code/modules/lane_distance/__init__.py†L261-L295】
- 保存されるカラム: `l_line_distance`, `r_line_distance`, `line_distance`, `lane_position_flag`

## 6. 車両間距離解析 (`analyze_proximity`)
- 対象: Detectionテーブル, ProximityDataテーブル
- 内容: 同一フレーム内の車両ペアごとにキャリブレーションのスケール線からローカルなpixel/m換算値を取得し、直線距離・横方向・縦方向距離をメートルで記録します。各車両の前方最近接車両も求め、Detectionへ距離と相手`group_id`を保存します。【F:Source_code/modules/inter_vehicle_distance.py†L1-L80】
- 保存されるカラム: `front_distance_m`, `front_vehicle_id`（Detection） / `ProximityData`テーブルの新規行

## 7. TTC計算 (`assign_ttc`)
- 対象: Detectionテーブル
- 内容: 前方車両との相対速度と距離からTTC（衝突余裕時間）を算出し、接近している車両行へ`ttc_s`を保存します。前処理としてRun内の既存TTCをリセットします。【F:Source_code/modules/ttc_calculator.py†L1-L34】
- 保存されるカラム: `ttc_s`

## 付録: 集計結果の反映
各Runの後処理が終わると、Detectionテーブルの主要カラムに値が入っている件数を集計し、UIの進捗パネルに表示します。これにより、白線距離や離隔距離などの欠損を即座に確認できます。【F:Source_code/routes.py†L378-L419】【F:Source_code/routes.py†L440-L459】
