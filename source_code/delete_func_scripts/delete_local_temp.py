import shutil
import json
from pathlib import Path

def clean(progress_callback=None):
    folder_name = "Local Temp"
    folder_path = Path.home() / "AppData" / "Local" / "Temp"

    if not folder_path.exists():
        print(f"{folder_name} klasörü bulunamadı: {folder_path}")
        return

    files = list(folder_path.iterdir())
    total = len(files)
    print(f"{folder_name} klasöründe {total} dosya bulundu. Temizleniyor...")

    for i, file in enumerate(files, 1):
        try:
            if file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
            else:
                file.unlink()
        except Exception as e:
            print(f"Hata: {e}")

        progress = {"current": i, "total": total}
        if progress_callback:
            progress_callback(progress)
        else:
            print(f"PROGRESS:{json.dumps(progress)}", flush=True)

    print(f"{folder_name} klasörü başarıyla temizlendi.\n")
