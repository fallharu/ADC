# カウント線機能実装完了

## 📊 実装内容

### 1. データベーステーブル作成
**テーブル名**: `TrafficCount`

**カラム構成**:
- `count_id` (INTEGER PRIMARY KEY): 自動採番ID
- `run_id` (INTEGER): 処理Run ID
- `line_name` (TEXT): カウント線名 (例: "Line 1", "Line 2")
- `object_type` (TEXT): 車両タイプ ("車" または "自転車")
- `direction` (TEXT): 進行方向 ("上向き" または "下向き")
- `count` (INTEGER): カウント数
- `created_at` (TEXT): 作成日時

### 2. カウント処理の実装 (`traffic_counter.py`)

#### 機能:
1. **車両タイプ分類**:
   - 自転車: "bicycle", "bike" → "自転車"
   - 車両: "car", "truck", "bus", "vehicle" → "車"

2. **進行方向の判定**:
   - Y座標が増加 (下方向) → "下向き"
   - Y座標が減少 (上方向) → "上向き"

3. **カウントロジック**:
   - カウント線を横切った車両を検出
   - 同一オブジェクトが同じ線を複数回横切っても1回のみカウント
   - 車両タイプ × 進行方向 × カウント線ごとに集計

### 3. API エンドポイント追加

**エンドポイント**: `GET /api/traffic_count/<run_id>`

**レスポンス例**:
```json
{
  "status": "ok",
  "run_id": 100145,
  "has_data": true,
  "data": [
    {
      "line_name": "Line 1",
      "object_type": "車",
      "direction": "下向き",
      "count": 45,
      "created_at": "2026-01-08 12:30:00"
    },
    {
      "line_name": "Line 1",
      "object_type": "車",
      "direction": "上向き",
      "count": 38,
      "created_at": "2026-01-08 12:30:00"
    },
    {
      "line_name": "Line 1",
      "object_type": "自転車",
      "direction": "下向き",
      "count": 12,
      "created_at": "2026-01-08 12:30:00"
    },
    {
      "line_name": "Line 1",
      "object_type": "自転車",
      "direction": "上向き",
      "count": 8,
      "created_at": "2026-01-08 12:30:00"
    }
  ]
}
```

## 🔧 実行タイミング

カウント処理は**ポストプロセス時に自動実行**されます:
- `batch_processor.py` の Step 0 で実行
- カウント線が定義されているキャリブレーションプロファイルが適用されているRun IDに対して自動的にカウント

## 📝 使用方法

### フロントエンドでの取得例:
```javascript
fetch(`/api/traffic_count/${runId}`)
  .then(response => response.json())
  .then(data => {
    if (data.has_data) {
      console.log("カウント結果:", data.data);
      // 車: 上向き 38台, 下向き 45台
      // 自転車: 上向き 8台, 下向き 12台
    } else {
      console.log(data.message); // "カウントデータが見つかりません"
    }
  });
```

### SQLでの直接取得:
```sql
SELECT 
    line_name,
    object_type,
    direction,
    count
FROM TrafficCount
WHERE run_id = 100145
ORDER BY line_name, object_type, direction;
```

## ✅ 完了項目

- [x] TrafficCountテーブルの作成
- [x] 進行方向判定ロジック実装
- [x] 車両/自転車分類ロジック実装
- [x] カウント処理の修正
- [x] APIエンドポイント追加
- [x] データベーススキーマ更新

## 🔄 次回の処理時から有効

現在実行中のアプリケーションは再起動後、または次回のポストプロセス実行時からカウント機能が有効になります。

既存のRun IDに対してカウントを実行したい場合は、そのRun IDに対して再度ポストプロセスを実行してください。
