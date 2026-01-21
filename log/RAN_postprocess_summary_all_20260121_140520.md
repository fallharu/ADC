# RAN 後処理まとめログ

- 作成日時: 2026-01-21 14:05:20
- ラベル: all
- Run数: 240

## カウント線通過統計

|種別|方向|通過数|
|---|---|---:|
|車|上向き|39|
|車|下向き|124|

合計:
- 車: 163

車種別合計:
- 車: 163
- 自転車: 0
## 測定区間Y長さの統計

- 最小: 174.0px
- 最大: 492.0px
- 中央値: 398.0px
- ピーク(上位2件): 398.0px, 427.0px

## 追い越し集計

- OvertakeEvents 行数: 47
- overtake_by 行数: 92
- overtake_by_second 行数: 92
- overtake=1 行数: 47

### 追い越し時の速度変化

- 変化あり: 0 / 47 (0.0%)
- 内訳: 加速 0, 減速 0, 等速 47, 不明 0

## Detection カラム別 行数/割合

> 注記: overtake/overtake_after は 1 の行数を表示 (0は未検出扱い)

|カラム名|行数|割合|
|---|---:|---:|
|auto_id|909073|100.0%|
|run_id|909073|100.0%|
|video_id|909073|100.0%|
|class_id|909073|100.0%|
|frame_num|909073|100.0%|
|x1|909073|100.0%|
|y1|909073|100.0%|
|x2|909073|100.0%|
|y2|909073|100.0%|
|measure_x|419336|46.1%|
|measure_y|419336|46.1%|
|model_name|909073|100.0%|
|track_id|895515|98.5%|
|confidence|909073|100.0%|
|group_id|853443|93.9%|
|approach_partner_group_id|88876|9.8%|
|approach_distance_m|86710|9.5%|
|approach_distance_px|88876|9.8%|
|clearance_distance_m|43|0.0%|
|clearance_distance_cm|43|0.0%|
|clearance_distance_px|47|0.0%|
|pixel_speed|417819|46.0%|
|pixel_speed_frame|2271|0.2%|
|speed_km_h|417819|46.0%|
|overtake|47|0.0%|
|overtake_after|1274|0.1%|
|overtake_window_offset|2454|0.3%|
|overtake_by|92|0.0%|
|overtake_by_second|92|0.0%|
|oncoming_flag|909073|100.0%|
|l_line_distance|419336|46.1%|
|l_line_distance_m|419336|46.1%|
|l_line_distance_cm|419336|46.1%|
|r_line_distance|419336|46.1%|
|r_line_distance_m|419336|46.1%|
|r_line_distance_cm|419336|46.1%|
|line_distance|419336|46.1%|
|line_distance_m|419336|46.1%|
|line_distance_cm|419336|46.1%|
|lane_position_flag|419336|46.1%|
|front_distance_m|211842|23.3%|
|front_vehicle_id|211842|23.3%|
|travel_direction|417819|46.0%|
|scale_pixels_per_meter|0|0.0%|
|x_pixels_per_meter|417819|46.0%|
|acceleration_m_s2|417819|46.0%|
|acceleration_state|417819|46.0%|
|ttc_s|79072|8.7%|
|obj_id|0|0.0%|
|l_line_cross_m|43727|4.8%|
|r_line_cross_m|67266|7.4%|
|center_line_overtake_status|417819|46.0%|
|white_line_overtake_status|46980|5.2%|

## 後処理生成カラム 行数/割合

|カラム名|行数|割合|
|---|---:|---:|
|measure_x|419336|46.1%|
|measure_y|419336|46.1%|
|group_id|853443|93.9%|
|approach_partner_group_id|88876|9.8%|
|approach_distance_m|86710|9.5%|
|approach_distance_px|88876|9.8%|
|clearance_distance_m|43|0.0%|
|clearance_distance_cm|43|0.0%|
|clearance_distance_px|47|0.0%|
|pixel_speed|417819|46.0%|
|speed_km_h|417819|46.0%|
|overtake|47|0.0%|
|overtake_after|1274|0.1%|
|overtake_window_offset|2454|0.3%|
|overtake_by|92|0.0%|
|overtake_by_second|92|0.0%|
|oncoming_flag|909073|100.0%|
|l_line_distance|419336|46.1%|
|l_line_distance_m|419336|46.1%|
|l_line_distance_cm|419336|46.1%|
|r_line_distance|419336|46.1%|
|r_line_distance_m|419336|46.1%|
|r_line_distance_cm|419336|46.1%|
|line_distance|419336|46.1%|
|line_distance_m|419336|46.1%|
|line_distance_cm|419336|46.1%|
|lane_position_flag|419336|46.1%|
|front_distance_m|211842|23.3%|
|front_vehicle_id|211842|23.3%|
|travel_direction|417819|46.0%|
|scale_pixels_per_meter|0|0.0%|
|x_pixels_per_meter|417819|46.0%|
|acceleration_m_s2|417819|46.0%|
|acceleration_state|417819|46.0%|
|ttc_s|79072|8.7%|
|l_line_cross_m|43727|4.8%|
|r_line_cross_m|67266|7.4%|
|center_line_overtake_status|417819|46.0%|
|white_line_overtake_status|46980|5.2%|

## Run ID一覧 (先頭20件)

100248, 100249, 100250, 100251, 100252, 100253, 100254, 100255, 100256, 100258, 100259, 100260, 100261, 100262, 100263, 100264, 100265, 100266, 100267, 100268
