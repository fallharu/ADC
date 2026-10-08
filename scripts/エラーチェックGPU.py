import torch
import torchaudio
import torchvision
import subprocess

def get_cuda_version():
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True, check=True)
        for line in result.stdout.split('\n'):
            if 'release' in line:
                return line.strip()
    except subprocess.CalledProcessError:
        return "CUDAがインストールされていないか、パスが設定されていません。"

def check_gpu_status():
    print("=== GPU/環境チェック開始 ===")
    
    # 1. CUDA が利用可能かどうか確認
    print(f"CUDA 利用可能: {torch.cuda.is_available()}")
    
    # 2. CUDA のバージョン確認
    if torch.cuda.is_available():
        print(f"CUDA バージョン: {torch.version.cuda}")
    else:
        print("CUDA が利用できないためバージョン確認不可。")

    # nvcc コマンドを使用して CUDA ツールキットのバージョンも確認
    print(f"CUDA ツールキットのバージョン: {get_cuda_version()}")

    # 3. PyTorch のバージョン確認
    print(f"PyTorch バージョン: {torch.__version__}")

    # 4. GPU デバイスの数確認
    gpu_count = torch.cuda.device_count()
    print(f"利用可能な GPU デバイス数: {gpu_count}")

    # 5. 各 GPU デバイスの詳細を出力
    if gpu_count > 0:
        for i in range(gpu_count):
            print(f"デバイス {i}: {torch.cuda.get_device_name(i)}")
            print(f"  - メモリ使用状況: {torch.cuda.memory_allocated(i) / 1024 ** 3:.2f} GB / {torch.cuda.get_device_properties(i).total_memory / 1024 ** 3:.2f} GB")
            print(f"  - デバイスのステータス: {'正常' if torch.cuda.get_device_capability(i) else '異常'}")
    else:
        print("利用可能な GPU デバイスが見つかりません。")

    # 6. 実行デバイスのチェック
    try:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"現在の実行デバイス: {device}")
        
        # デバイスを使ってテンソルを作成（動作確認）
        test_tensor = torch.tensor([1.0, 2.0, 3.0]).to(device)
        print(f"テンソルの作成とデバイスへの配置成功: {test_tensor}")
    except Exception as e:
        print(f"GPU 利用時にエラーが発生しました: {e}")
    
    print("=== GPU/環境チェック終了 ===")

# GPU エラーチェック関数の実行
check_gpu_status()

print("torch version:", torch.__version__)
print("torchvision version:", torchvision.__version__)
print("torchaudio version:", torchaudio.__version__)
print("CUDA version:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
