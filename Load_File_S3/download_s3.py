"""
download_s3.py — โหลดไฟล์จาก S3 / MinIO

วิธีใช้:
    # โหลดไฟล์เดียว (ใช้ค่า default key/dest ในไฟล์ หรือใส่เอง)
    python download_s3.py
    python download_s3.py A-MN/Test/Data/file.xlsx
    python download_s3.py A-MN/Test/Data/file.xlsx ./output/file.xlsx

    # โหลดทั้งโฟลเดอร์ (prefix) — ลงท้าย key ด้วย / หรือใส่ --recursive
    python download_s3.py A-MN/Test/Data/ ./download --recursive

ก่อนรัน:
    pip install boto3 python-dotenv
    แล้วสร้างไฟล์ .env (ดูตัวอย่างในไฟล์ .env.example)
"""

import os
import sys
import argparse

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

# โหลดค่าจาก .env ที่อยู่โฟลเดอร์เดียวกัน
load_dotenv()

# ---------- config (อ่านจาก .env) ----------
BUCKET = os.getenv("MINIO_BUCKET", "gcme-me-smart")
ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
REGION = os.getenv("AWS_REGION", "ap-southeast-1")

# MINIO_SECURE=true -> https, false -> http
SECURE = os.getenv("MINIO_SECURE", "true").strip().lower() in ("true", "1", "yes")

# สร้าง endpoint_url พร้อม scheme จาก MINIO_ENDPOINT + MINIO_SECURE
_raw_endpoint = (os.getenv("MINIO_ENDPOINT") or "").strip()
if _raw_endpoint and not _raw_endpoint.startswith(("http://", "https://")):
    scheme = "https" if SECURE else "http"
    ENDPOINT = f"{scheme}://{_raw_endpoint}"
else:
    ENDPOINT = _raw_endpoint or None

# ค่า default ถ้าไม่ได้ใส่ argument มา
DEFAULT_KEY = ""
DEFAULT_DEST = "./file.xlsx"


def make_client():
    """สร้าง s3 client โดยใช้ค่าจาก .env"""
    kwargs = {"region_name": REGION}
    if ENDPOINT:
        kwargs["endpoint_url"] = ENDPOINT
    # ถ้ามี key ใน .env ก็ใช้ / ถ้าไม่มี boto3 จะหา credential จาก IAM role / aws cli เอง
    if ACCESS_KEY and SECRET_KEY:
        kwargs["aws_access_key_id"] = ACCESS_KEY
        kwargs["aws_secret_access_key"] = SECRET_KEY
    return boto3.client("s3", **kwargs)


def download_one(s3, key, dest):
    """โหลดไฟล์เดียว"""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    print(f"กำลังโหลด  s3://{BUCKET}/{key}  ->  {dest}")
    s3.download_file(BUCKET, key, dest)
    print(f"  เสร็จ ({os.path.getsize(dest):,} bytes)")


def download_prefix(s3, prefix, dest_dir):
    """โหลดทุกไฟล์ใน prefix (โฟลเดอร์)"""
    paginator = s3.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):  # ข้าม placeholder ของโฟลเดอร์
                continue
            # คงโครงสร้างโฟลเดอร์เดิมไว้ใต้ dest_dir
            rel = key[len(prefix):] if key.startswith(prefix) else key
            local = os.path.join(dest_dir, rel)
            download_one(s3, key, local)
            count += 1
    if count == 0:
        print(f"ไม่พบไฟล์ภายใต้ prefix: {prefix}")
    else:
        print(f"\nรวมโหลดทั้งหมด {count} ไฟล์ ลงใน {dest_dir}")


def list_prefix(s3, prefix):
    """แสดงรายการ key ภายใต้ prefix (ไม่โหลด) ไว้เช็คโครงสร้างจริง"""
    paginator = s3.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            size = obj.get("Size", 0)
            print(f"  {obj['Key']}  ({size:,} bytes)")
            count += 1
    print(f"\nพบทั้งหมด {count} รายการ ภายใต้ prefix: '{prefix}'")


def main():
    parser = argparse.ArgumentParser(description="Download file(s) from S3/MinIO")
    parser.add_argument("key", nargs="?", default=DEFAULT_KEY,
                        help="object key หรือ prefix ใน bucket")
    parser.add_argument("dest", nargs="?", default=None,
                        help="ปลายทางในเครื่อง (ไฟล์ หรือ โฟลเดอร์)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="โหลดทั้ง prefix (โฟลเดอร์)")
    parser.add_argument("-l", "--list", action="store_true",
                        help="แสดงรายการไฟล์ภายใต้ prefix เฉยๆ (ไม่โหลด)")
    args = parser.parse_args()

    s3 = make_client()
    where = ENDPOINT or "AWS S3 (default endpoint)"
    print(f"เชื่อมต่อ: {where} | bucket: {BUCKET}\n")

    try:
        if args.list:
            list_prefix(s3, args.key)
        # ถือเป็นโฟลเดอร์ถ้า key ลงท้ายด้วย / หรือใส่ --recursive
        elif args.recursive or args.key.endswith("/"):
            dest_dir = args.dest or "./download"
            download_prefix(s3, args.key, dest_dir)
        else:
            dest = args.dest or DEFAULT_DEST
            download_one(s3, args.key, dest)
    except NoCredentialsError:
        print("ผิดพลาด: ไม่พบ credential — ตรวจ MINIO_ACCESS_KEY / MINIO_SECRET_KEY ใน .env")
        sys.exit(1)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            print(f"ผิดพลาด: ไม่พบไฟล์ key นี้ใน bucket -> {args.key}")
        elif code in ("403", "AccessDenied"):
            print("ผิดพลาด: ไม่มีสิทธิ์ (AccessDenied) — ตรวจ IAM ว่ามี s3:GetObject / s3:ListBucket")
        elif code == "NoSuchBucket":
            print(f"ผิดพลาด: ไม่พบ bucket -> {BUCKET}")
        else:
            print(f"ผิดพลาด ({code}): {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()