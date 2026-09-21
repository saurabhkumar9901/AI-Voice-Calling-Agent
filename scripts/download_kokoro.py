import os
import urllib.request
import sys

def report(block_num, block_size, total_size):
    downloaded = block_num * block_size
    percent = downloaded / total_size * 100 if total_size > 0 else 0
    sys.stdout.write(f"\rDownloading: {downloaded / (1024 * 1024):.2f} MB / {total_size / (1024 * 1024):.2f} MB ({percent:.1f}%)")
    sys.stdout.flush()

cache_dir = os.path.expanduser("~/.cache/kokoro-onnx")
os.makedirs(cache_dir, exist_ok=True)

model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
voice_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

model_path = os.path.join(cache_dir, "kokoro-v1.0.onnx")
voice_path = os.path.join(cache_dir, "voices-v1.0.bin")

print(f"Downloading Kokoro Model to {model_path}...")
urllib.request.urlretrieve(model_url, model_path, reporthook=report)
print("\nModel Download Complete!\n")

print(f"Downloading Voices to {voice_path}...")
urllib.request.urlretrieve(voice_url, voice_path, reporthook=report)
print("\nVoices Download Complete!\n")

print("Kokoro TTS successfully installed!")
