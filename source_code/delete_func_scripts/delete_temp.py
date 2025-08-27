import os
import shutil
import json
from pathlib import Path

def clean(progress_callback=None):
    folder_name = "Windows Temp"
    folder_path = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Temp"

    if not folder_path.exists():
        print(f"{folder_name} klasörü bulunamadı: {folder_path}", flush=True)
        return

    files = list(folder_path.iterdir())
    total_files = len(files)
    print(f"{folder_name} klasöründe {total_files} dosya bulundu. Temizleniyor...", flush=True)

    for i, file in enumerate(files, start=1):
        try:
            if file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
            else:
                file.unlink()
        except Exception as e:
            print(f"Hata: {e}", flush=True)

        progress = {
            'folder': folder_name,
            'current': i,
            'total': total_files
        }

        if progress_callback:
            progress_callback(progress)
        else:
            print("PROGRESS:" + json.dumps(progress), flush=True)

    print(f"{folder_name} klasörü başarıyla temizlendi.\n", flush=True)