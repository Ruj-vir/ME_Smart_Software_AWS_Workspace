# งานแก้โค้ดจากผลสแกนคุณภาพ (Ruff + Bandit + mypy)

คุณเป็นวิศวกรซอฟต์แวร์ที่ช่วยแก้โค้ด Python ด้านล่างคือ issue ที่เครื่องมือสแกนตรวจพบ ทั้งหมด **15 รายการ** จาก **2 ไฟล์**

กรุณา:
1. แก้ทุก issue โดยคงพฤติกรรมเดิมของโปรแกรมไว้ (ยกเว้นช่องโหว่ security ที่ต้องแก้ให้ปลอดภัยขึ้น)
2. สำหรับแต่ละไฟล์ ส่งโค้ดเวอร์ชันที่แก้แล้วกลับมาให้
3. ใต้โค้ดของแต่ละไฟล์ สรุปสั้น ๆ ว่าแก้ issue ไหน และแก้อย่างไร
4. ถ้า issue ไหนเป็น false positive ให้บอกเหตุผลแทนการแก้

หมายเหตุ: ในบล็อกโค้ด บรรทัดที่ขึ้นต้นด้วย `>` คือบรรทัดที่ตรวจพบปัญหา (เลขหน้า `|` คือเลขบรรทัดจริงในไฟล์)

---

## ไฟล์: `backend\create_paths.py`

**Issues ที่ต้องแก้:**

- [ruff · E401 · Warning] บรรทัด 11: Multiple imports on one line

```python
     6 |     python create_paths.py
     7 | """
     8 | 
     9 | from minio import Minio
    10 | from dotenv import load_dotenv
>   11 | import io, os
    12 | 
    13 | load_dotenv()
    14 | 
    15 | # ══════════════════════════════════════════════════════
    16 | #  CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
```

## ไฟล์: `backend\server.py`

**Issues ที่ต้องแก้:**

- [bandit · B324 · Critical] บรรทัด 300: Use of weak MD5 hash for security. Consider usedforsecurity=False
- [mypy · import-untyped · Major] บรรทัด 13: Library stubs not installed for "psycopg2.extras"
- [mypy · import-untyped · Major] บรรทัด 13: Library stubs not installed for "psycopg2"
- [mypy · import-untyped · Major] บรรทัด 15: Skipping analyzing "msal": module is installed, but missing library stubs or py.typed marker
- [mypy · import-untyped · Major] บรรทัด 15: Library stubs not installed for "requests"
- [mypy · union-attr · Major] บรรทัด 299: Item "None" of "str | None" has no attribute "strip"
- [ruff · E401 · Warning] บรรทัด 13: Multiple imports on one line
- [ruff · E401 · Warning] บรรทัด 14: Multiple imports on one line
- [ruff · E401 · Warning] บรรทัด 15: Multiple imports on one line
- [mypy · type · Minor] บรรทัด 13: Hint: "python3 -m pip install types-psycopg2"
- [mypy · type · Minor] บรรทัด 13: (or run "mypy --install-types" to install all missing stub packages)
- [mypy · type · Minor] บรรทัด 13: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
- [mypy · type · Minor] บรรทัด 15: Hint: "python3 -m pip install types-requests"
- [bandit · B110 · Minor] บรรทัด 338: Try, Except, Pass detected.

```python
     8 | from datetime import timedelta
     9 | from typing import Optional
    10 | from contextlib import contextmanager
    11 | from dotenv import load_dotenv
    12 | from urllib.parse import quote
>   13 | import psycopg2, psycopg2.extras
>   14 | import uuid, os, io, hashlib, secrets, mimetypes
>   15 | import msal, requests, jwt
    16 | 
    17 | load_dotenv()
    18 | 
    19 | app = FastAPI()
    20 | 
       ...
   294 |     except S3Error:
   295 |         raise HTTPException(404, "File not found in MinIO")
   296 | 
   297 |     filename = object_name.split("/")[-1]
   298 |     # key ต้องเปลี่ยนทุกครั้งที่ไฟล์เปลี่ยน เพื่อให้ OnlyOffice ไม่ใช้ cache เก่า
>  299 |     etag = stat.etag.strip('"')
>  300 |     doc_key = hashlib.md5(f"{object_name}:{etag}".encode()).hexdigest()
   301 | 
   302 |     config = {
   303 |         "document": {
   304 |             "fileType": ext,
   305 |             "key": doc_key,
       ...
   333 |         raise HTTPException(404, "File not found")
   334 |     finally:
   335 |         try:
   336 |             response.close()
   337 |             response.release_conn()
>  338 |         except Exception:
   339 |             pass
   340 | 
   341 |     media_type = mimetypes.guess_type(object_name)[0] or "application/octet-stream"
   342 |     filename = object_name.split("/")[-1]
   343 |     return Response(
```
