"""
สร้าง folder structure ใน MinIO bucket: me_smart
โครงสร้าง: [Company]/A-MN/Test/Data/

วิธีใช้:
    python create_paths.py
"""

from minio import Minio
from dotenv import load_dotenv
import io
import os

load_dotenv()

# ══════════════════════════════════════════════════════
#  CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
# ══════════════════════════════════════════════════════
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT", "localhost:9000")   # S3 API port
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_SECURE     = os.getenv("MINIO_SECURE", "false").lower() == "true"
BUCKET           = os.getenv("MINIO_BUCKET", "me-smart")

# ══════════════════════════════════════════════════════
#  PATHS ที่ต้องการสร้าง
# ══════════════════════════════════════════════════════
COMPANIES = [
    "GC",
    # เพิ่มบริษัทอื่นได้ที่นี่ เช่น "PTT", "GPSC", "ThaiOil", "HMC"
]

SUB_PATH = "A-MN/Test/Data/"   # path หลังชื่อบริษัท

# ══════════════════════════════════════════════════════

mc = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

print(f"📦 ใช้ bucket '{BUCKET}' ที่มีอยู่แล้ว")

# สร้าง folder paths (ใน S3/MinIO ใช้วิธี upload empty object)
print("\nสร้าง folder paths:")
for company in COMPANIES:
    # สร้างทุก level ของ path
    full_path = f"{company}/{SUB_PATH}"
    parts = full_path.split("/")

    current = ""
    for part in parts:
        if not part:
            continue
        current += part + "/"
        try:
            mc.put_object(BUCKET, current, io.BytesIO(b""), 0)
            print(f"  ✅ {current}")
        except Exception as e:
            print(f"  ⚠️  {current} — {e}")

print("\nเสร็จสิ้น")
