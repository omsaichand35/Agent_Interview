import shutil
import sys
from pathlib import Path
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

VALIDATION_DIR = PROJECT_ROOT / "data" / "raw" / "identity_validation"
GENUINE_DIR = VALIDATION_DIR / "genuine"
IMPOSTOR_DIR = VALIDATION_DIR / "impostor"


def download_file(url: str, dest: Path):
    if not dest.exists():
        print(f"Downloading {dest.name}...")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        dest.write_bytes(resp.content)


def main():
    GENUINE_DIR.mkdir(parents=True, exist_ok=True)
    IMPOSTOR_DIR.mkdir(parents=True, exist_ok=True)

    hopkins_1_url = "https://raw.githubusercontent.com/davidsandberg/facenet/master/data/images/Anthony_Hopkins_0001.jpg"
    hopkins_2_url = "https://raw.githubusercontent.com/davidsandberg/facenet/master/data/images/Anthony_Hopkins_0002.jpg"
    lena_url = "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg"

    download_file(hopkins_1_url, GENUINE_DIR / "pair01_reference.jpg")
    download_file(hopkins_2_url, GENUINE_DIR / "pair01_live.jpg")

    download_file(hopkins_1_url, IMPOSTOR_DIR / "pair01_reference.jpg")
    download_file(lena_url, IMPOSTOR_DIR / "pair01_live.jpg")

    user_pic = Path(r"C:\Users\omsai\OneDrive\Pictures\WhatsApp Image 2025-12-11 at 10.31.26_ca8d9b38.jpg")
    if user_pic.exists():
        shutil.copy2(user_pic, GENUINE_DIR / "pair02_reference.jpg")
        shutil.copy2(user_pic, GENUINE_DIR / "pair02_live.jpg")

        shutil.copy2(user_pic, IMPOSTOR_DIR / "pair02_reference.jpg")
        download_file(lena_url, IMPOSTOR_DIR / "pair02_live.jpg")
        print("Included your local photo as pair02 (genuine and impostor).")

    print(f"\nValidation dataset successfully prepared at:\n{VALIDATION_DIR}")
    print(f"- Genuine pairs: {len(list(GENUINE_DIR.glob('*_reference.*')))}")
    print(f"- Impostor pairs: {len(list(IMPOSTOR_DIR.glob('*_reference.*')))}")


if __name__ == "__main__":
    main()
