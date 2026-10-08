# Tire Distance Studio

画像・動画フレームの下中央から、タイヤ検出bboxの基準点までのピクセル距離を計算・可視化する改善版UIです。既存の計算エンジンを変更せず利用します。

## 必要ライブラリの導入

このStudioはWindows上のPython仮想環境を前提としています。現在の環境ではPython 3.13.7、Ultralytics 8.3.200、PyTorch 2.9.1、OpenCV 4.12.0、Pillow 11.3.0で動作確認しています。

主なライブラリ:

| ライブラリ | 用途 |
|---|---|
| `torch`, `torchvision` | YOLOの推論・GPU処理・再学習 |
| `ultralytics` | YOLOモデルの読込、検出、学習 |
| `opencv-python` | 画像・動画の読込、動画出力、描画 |
| `Pillow` | アノテーション画像のTkinter表示 |
| `tkinter` | デスクトップUI。通常はWindows版Pythonに同梱 |

### 1. 仮想環境を作成

PowerShellを開き、ダウンロードまたはcloneした`tire_distance_studio`フォルダで実行します。`.venv`という名前は`start_studio.bat`が参照するため変更しないでください。

```powershell
cd ＜保存先＞\tire_distance_studio
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
```

`py`が見つからない場合は、64bit版Pythonをインストールしてから再実行します。Pythonのインストール時は「Add Python to PATH」を有効にしてください。

### 2. PyTorchを導入

#### NVIDIA GPUを使う場合（推奨）

最初に次のコマンドでGPUとドライバーが認識されることを確認します。

```powershell
nvidia-smi
```

次に[PyTorch公式インストール選択画面](https://pytorch.org/get-started/locally/)で次を選び、表示されたコマンドを実行します。

- OS: Windows
- Package: Pip
- Language: Python
- Compute Platform: 使用環境に合うCUDA

表示コマンドの`pip`または`pip3`部分は、次の形式へ置き換えると、作成した`.venv`へ確実にインストールできます。

```powershell
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/＜公式画面に表示されたCUDA用index＞
```

CUDAの文字列は環境やPyTorchのリリースによって変わるため、`cu121`などを推測で固定しないでください。必ず公式画面が現在表示するコマンドを使用します。

#### CPUだけで使う場合

GPUを使用しない場合はCPU版をインストールします。距離解析と再学習はGPUより大幅に遅くなる可能性があります。

```powershell
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

### 3. Studio用ライブラリを導入

PyTorchの導入後に実行します。Ultralytics公式ではPyPIからの`pip install -U ultralytics`が推奨されています。

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade ultralytics opencv-python Pillow
```

このStudioは上記の最小構成だけで実行できます。


`opencv-python`と`opencv-python-headless`は同じ環境へ同時に入れないでください。このStudioはデスクトップUI用なので`opencv-python`を使用します。

### 4. インストール確認

```powershell
.\.venv\Scripts\python.exe -c "import cv2, PIL, torch, ultralytics; print('OpenCV', cv2.__version__); print('Pillow', PIL.__version__); print('PyTorch', torch.__version__); print('Ultralytics', ultralytics.__version__); print('CUDA', torch.cuda.is_available())"
.\.venv\Scripts\python.exe -m tkinter
.\.venv\Scripts\python.exe app.py --check
```

確認内容:

- 4ライブラリのバージョンが表示される
- NVIDIA GPUを使う場合は`CUDA True`になる
- `python -m tkinter`で小さなTk画面が開く
- `app.py --check`のengine、tire_model、base_model、engine importがすべて`OK`になる

確認後、Tkのテスト画面は閉じてください。

### 導入時のトラブル

#### `CUDA False`になる

CPU版PyTorchが入っているか、NVIDIAドライバーとPyTorchのCUDA版が合っていません。PyTorch公式選択画面で現在のWindows向けコマンドを確認し、`.venv`内のPyTorchを入れ直してください。PCへCUDA Toolkitを別途入れる必要があるかどうかも、使用するPyTorch版の公式説明に従ってください。

#### PowerShellで仮想環境を有効化できない

このREADMEのコマンドは`Activate.ps1`を使わず、`.venv`のPythonを直接指定しているため、そのまま実行できます。手動で有効化する場合だけ、実行ポリシーの設定が必要になることがあります。

#### `No module named tkinter`になる

Microsoft Store版など一部のPython構成ではTkが不足することがあります。Python公式Windowsインストーラーの変更・修復画面で`Tcl/Tk and IDLE`を有効にしてください。

#### ライブラリ導入後も起動できない

```powershell
cd ＜保存先＞\tire_distance_studio
.\check_environment.bat
```

表示された最初の`NG`またはエラーを確認します。

参考資料:

- [Ultralytics公式インストールガイド](https://docs.ultralytics.com/quickstart/)
- [PyTorch公式インストール選択画面](https://pytorch.org/get-started/locally/)
- [Python公式venv説明](https://docs.python.org/ja/3/library/venv.html)

## 起動

`start_studio.bat` をダブルクリックしてください。

PowerShellから起動する場合:

```powershell
cd ＜保存先＞\tire_distance_studio
.\.venv\Scripts\python.exe app.py
```

起動できない場合は `check_environment.bat` を実行します。

## UIの解像度と表示倍率

Windowsの高DPI表示に対応しています。4Kディスプレイや125～200%の拡大表示では、モニターDPIに合わせてウィンドウと文字を自動調整します。

左下の「表示倍率」で80～150%へ変更できます。

- 拡大: `Ctrl` + `+`
- 縮小: `Ctrl` + `-`
- 100%へ戻す: `Ctrl` + `0`

表示が小さい場合は110～125%、画面に収まらない場合は80～90%を選んでください。

## 最短の使い方

1. 左メニューの「距離解析」を開きます。
2. 「画像／動画」で入力ファイルを選びます。
3. モデルが `models\best.pt` になっていることを確認します。
4. 初回は「最大フレーム」を `30` にして「解析を開始」を押します。
5. `outputs` フォルダのCSVと可視化MP4を確認します。
6. 問題がなければ「最大フレーム」を `0` にして動画全体を処理します。

画像入力ではCSVのみを出力します。動画入力ではCSVと可視化MP4を出力します。

## 可視化の読み方

- 赤点: 画像・動画フレームの下中央 `(幅/2, 高さ)`
- 緑枠: 検出されたタイヤbbox
- 青点: 選択したタイヤ基準点
- 水色線: 距離を測っている2点
- ラベル: ピクセル距離と検出信頼度

距離は画像座標上のユークリッド距離です。カメラ校正なしではメートルやセンチメートルではありません。

## 推論設定

### conf

検出を採用する最低信頼度です。

- `0.05～0.10`: 見逃しを減らす。誤検出が増えやすい
- `0.20～0.35`: 誤検出を減らす。小さいタイヤを見逃しやすい
- 初期値 `0.10`: 小さいタイヤを拾うことを優先

### imgsz

モデルへ渡す画像サイズです。

- `640`: 標準。最初に使用
- `960`: 小さいタイヤを改善したい場合
- `1280`: さらに精細だが、処理時間とGPUメモリが大きく増える

### device

- `auto`: CUDA GPUがあればGPU、なければCPU
- `0`: 1台目のGPUを明示
- `cpu`: CPUを明示。かなり遅くなる可能性あり

### frame step

動画で推論するフレーム間隔です。

- `1`: 全フレーム。滑らかな可視化動画向け
- `5～15`: 試験処理
- `30～60`: 学習画像の間引き抽出向け

### 最大フレーム

実際に推論する最大枚数です。`0` は制限なしです。初回確認は `30` を推奨します。

## アノテーション

「アノテーション」画面では `best.pt` を使ってYOLO形式の自動ラベルを作れます。生成先は次の構造になります。

```text
datasets/tire_training_dataset/
├─ data.yaml
├─ images/
│  ├─ train/
│  └─ val/
└─ labels/
   ├─ train/
   └─ val/
```

自動ラベルは正解ではありません。学習前に次を確認してください。

- タイヤを囲むbboxが過度に大きくない
- Number plateや車体をタイヤとして囲っていない
- 見逃したタイヤを追加した
- 同じ場面がtrainとvalの両方に重複していない

新UIの「手動アノテーションエディタを開く」から、直接矩形編集できます。

1. 入力の「ファイル」または「フォルダ」で画像・動画を選びます。
2. 動画の場合は抽出間隔と最大枚数を設定します。
3. 「読み込む」を押します。
4. 画像上でタイヤを左ドラッグして、緑色のbboxを作ります。
5. 間違えた場合は「直前の矩形を削除」またはBackspaceを使います。
6. `Ctrl+S`で現在の画像、または「全画像を保存」でまとめて保存します。

既存のYOLOラベルがデータセット内にある場合は自動的に読み込みます。未保存の変更は画像名の横に「●未保存」と表示されます。旧画面が必要な場合のみ「旧ツールも開く」を使用してください。

## 再学習

1. アノテーションを目視確認します。
2. 「再学習」でデータセットを選びます。
3. ベースモデルは通常 `yolo26x.pt` を選びます。
4. 最初は `epochs=20`, `imgsz=640`, `batch=4～8` で動作確認します。
5. 問題がなければ `epochs=50～100` へ増やします。

学習結果はrunごとの別フォルダへ保存されます。Studio内の `models\best.pt` は自動上書きしません。

## トラブルシューティング

### 検出件数が0

- モデルが `best.pt` か確認
- confを `0.05` へ下げる
- imgszを `960` へ上げる
- 入力映像にタイヤが十分な大きさで写っているか確認

### 誤検出が多い

- confを `0.20`、`0.30` と段階的に上げる
- 自動ラベルをそのまま学習へ使わない
- Number_plateの誤検出を削除する

### CUDA out of memory

- 再学習のbatchを半分にする
- imgszを下げる
- 他のGPU使用アプリを終了する

### 出力動画を再生できない

MP4コーデックの環境差が考えられます。出力名を`.avi`にして再実行するか、VLC等の再生ソフトで確認してください。

## ファイル配置

実行に必要な計算エンジンとタイヤモデルは、このStudio内へ同梱しています。

- 計算エンジン: `engine\tire_distance_engine.py`
- タイヤ専用モデル: `models\best.pt`
- 再学習ベース: 同梱しません。再学習画面から任意の`.pt`を選択してください。

Studio内の`models`フォルダへ配置するモデルは、距離解析・自動アノテーション用の`best.pt`だけです。

```text
tire_distance_studio/
└─ models/
   └─ best.pt
```

`yolo26x.pt`などの汎用ベースモデルはStudio内へ同梱せず、再学習を使う場合だけ利用者が別途用意して選択します。

`engine`と`models`の相対配置は変更しないでください。

## 改善版の安全機能

- Windowsでコピーした引用符付きパスをそのまま貼り付け可能
- Tk入力をメインスレッドで確定し、推論・学習中の不安定動作を防止
- 空の保存先、範囲外の数値、未対応入力形式を開始前に検出
- 同名の解析結果がある場合は、既存CSVへ追記せず日時付きの別ファイルへ保存
- 別モデル選択時にクラス名を調べ、Tire系クラスがなければ警告
- 不正な既存YOLOラベルを安全にスキップし、画像外bboxを境界内へ補正
- アノテーションの最大枚数を入力全体へ適用し、メモリ使用量を制限
- 全関数・クラスに日本語docstringを付け、設計判断はコードコメントで説明

内部構造、座標変換、スレッド境界、機能追加時の注意は [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) を参照してください。

実機での指定動画テスト結果は [TEST_REPORT.md](TEST_REPORT.md) に記録しています。
