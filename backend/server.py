from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from minio import Minio
from minio.error import S3Error
from datetime import timedelta
from typing import Optional
from contextlib import contextmanager, suppress
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from urllib.parse import quote
import psycopg2  # type: ignore[import-untyped]
import psycopg2.extras  # type: ignore[import-untyped]
import uuid
import os
import io
import hashlib
import secrets
import mimetypes
import msal  # type: ignore[import-untyped]
import requests  # type: ignore[import-untyped]
import jwt
import zipfile
from pypdf import PdfReader, PdfWriter

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..")
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ══════════════════════════════════════════════════════
#  MinIO CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
# ══════════════════════════════════════════════════════
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT", "localhost:9000")   # S3 API port
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")               # Access Key ของ MinIO
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")               # Secret Key ของ MinIO
MINIO_BUCKET     = os.getenv("MINIO_BUCKET", "me-smart")           # ชื่อ Bucket ที่สร้างไว้แล้ว
MINIO_SECURE     = os.getenv("MINIO_SECURE", "false").lower() == "true"  # True ถ้าใช้ HTTPS

AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1").strip()

mc = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
           secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE,
           region=AWS_REGION)

# ══════════════════════════════════════════════════════
#  PostgreSQL CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
# ══════════════════════════════════════════════════════
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5433")),
    "dbname":   os.getenv("DB_NAME", "me_smart_db"),
    "user":     os.getenv("DB_USER", ""),
    "password": os.getenv("DB_PASSWORD", ""),
}

def valid_uuid(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid UUID: '{value}'")

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(password: str, stored: str) -> bool:
    if ":" not in stored:
        return password == stored
    salt, hashed = stored.split(":", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == hashed

@contextmanager
def db():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════
class FolderIn(BaseModel):
    name: str
    parent_id: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"

class FileConfirm(BaseModel):
    name: str
    folder_id: str
    object_name: str
    size: int
    mime_type: str

class InspectionRecordIn(BaseModel):
    object_name: str
    by: str = ""
    result: str = ""
    note: str = ""

# ══════════════════════════════════════════════════════
#  AUTH ENDPOINTS
# ══════════════════════════════════════════════════════
@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/")
def root():
    return RedirectResponse(url="/ui/Login.html")

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/login")
def login(body: LoginRequest):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE username=%s", (body.username,))
            user = cur.fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return {"status": "ok", "username": user["username"], "role": user["role"]}

@app.post("/api/register")
def register(body: RegisterRequest):
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                    (body.username, body.email, hash_password(body.password), body.role)
                )
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    return {"status": "created", "username": body.username}

# ══════════════════════════════════════════════════════
#  FOLDER ENDPOINTS
# ══════════════════════════════════════════════════════
@app.get("/api/folders")
def list_folders(root: bool = False, parent_id: Optional[str] = None):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if root:
                cur.execute("SELECT * FROM folders WHERE parent_id IS NULL")
            else:
                cur.execute("SELECT * FROM folders WHERE parent_id=%s", (valid_uuid(parent_id),))
            return cur.fetchall()

@app.post("/api/folders")
def create_folder(body: FolderIn):
    fid = str(uuid.uuid4())
    parent = valid_uuid(body.parent_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO folders VALUES (%s,%s,%s)", (fid, body.name, parent))
    return {"id": fid, "name": body.name, "parent_id": parent}

# ══════════════════════════════════════════════════════
#  FILE ENDPOINTS
# ══════════════════════════════════════════════════════
@app.get("/api/files")
def list_files(folder_id: Optional[str] = None):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if folder_id:
                cur.execute("SELECT * FROM files WHERE folder_id=%s", (valid_uuid(folder_id),))
            else:
                cur.execute("SELECT * FROM files")
            return cur.fetchall()

@app.get("/api/upload-url")
def get_upload_url(folder_id: str, filename: str):
    object_name = f"{folder_id}/{uuid.uuid4()}-{filename}"
    url = mc.presigned_put_object(MINIO_BUCKET, object_name, expires=timedelta(hours=1))
    return {"upload_url": url, "object_name": object_name}

@app.post("/api/files/confirm")
def confirm_file(body: FileConfirm):
    fid = str(uuid.uuid4())
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO files VALUES (%s,%s,%s,%s,%s,%s)",
                        (fid, body.name, body.folder_id, body.object_name, body.size, body.mime_type))
    return {"id": fid}

@app.get("/api/files/{file_id}/url")
def get_file_url(file_id: str):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM files WHERE id=%s", (valid_uuid(file_id),))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "File not found")
    url = mc.presigned_get_object(MINIO_BUCKET, row["object_name"], expires=timedelta(hours=1))
    return {"url": url}

# ══════════════════════════════════════════════════════
#  LIST SUBFOLDERS IN MINIO
# ══════════════════════════════════════════════════════
@app.get("/api/list-paths")
def list_paths(prefix: str):
    """คืน list ชื่อ subfolder ใน MinIO ภายใต้ prefix ที่กำหนด"""
    prefix = prefix.strip("/")
    prefix = (prefix + "/") if prefix else ""
    objects = mc.list_objects(MINIO_BUCKET, prefix=prefix, recursive=False)
    folders = []
    for obj in objects:
        if obj.is_dir:
            name = obj.object_name[len(prefix):].rstrip("/")
            if name:
                folders.append(name)
    return {"folders": folders}

# ══════════════════════════════════════════════════════
#  DELETE PATH IN MINIO
# ══════════════════════════════════════════════════════
@app.delete("/api/delete-path")
def delete_path(path: str):
    """ลบ folder และทุกอย่างข้างในออกจาก MinIO"""
    path = path.rstrip("/") + "/"
    deleted = 0
    try:
        objects = list(mc.list_objects(MINIO_BUCKET, prefix=path, recursive=True))
        for obj in objects:
            mc.remove_object(MINIO_BUCKET, obj.object_name)
            deleted += 1
        mc.remove_object(MINIO_BUCKET, path)
    except S3Error:
        pass
    return {"status": "deleted", "path": path, "files_removed": deleted}

# ══════════════════════════════════════════════════════
#  BROWSE MINIO PATH (folders + files)
# ══════════════════════════════════════════════════════
@app.get("/api/browse")
def browse(prefix: str):
    prefix = prefix.strip("/")
    prefix = (prefix + "/") if prefix else ""
    objects = mc.list_objects(MINIO_BUCKET, prefix=prefix, recursive=False)
    folders, files = [], []
    for obj in objects:
        name = obj.object_name[len(prefix):].rstrip("/")
        if not name:
            continue
        if obj.is_dir:
            folders.append({"name": name})
        else:
            files.append({
                "name": name,
                "object_name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            })
    return {"folders": folders, "files": files}

@app.post("/api/browse/upload")
async def browse_upload(prefix: str, file: UploadFile = File(...)):
    prefix = prefix.rstrip("/") + "/"
    object_name = f"{prefix}{file.filename}"
    content = await file.read()
    mc.put_object(
        MINIO_BUCKET, object_name,
        io.BytesIO(content), length=len(content),
        content_type=file.content_type or "application/octet-stream"
    )
    return {"status": "uploaded", "object_name": object_name}

@app.get("/api/browse/file-url")
def browse_file_url(object_name: str):
    url = mc.presigned_get_object(MINIO_BUCKET, object_name, expires=timedelta(hours=1))
    return {"url": url}

@app.get("/api/browse/file-content")
def browse_file_content(object_name: str):
    try:
        resp = mc.get_object(MINIO_BUCKET, object_name)
        content = resp.read()
        resp.close()
        resp.release_conn()
    except S3Error:
        raise HTTPException(status_code=404, detail="file not found")
    return Response(content=content, media_type="application/octet-stream")

@app.delete("/api/browse/file")
def browse_delete_file(object_name: str):
    mc.remove_object(MINIO_BUCKET, object_name)
    return {"status": "deleted", "object_name": object_name}

# ══════════════════════════════════════════════════════
#  INSPECTION RECORDS (QAQC Step > Inspection Report)
#  เก็บ Record By / Result / Note ต่อไฟล์เวอร์ชัน (object_name) ลง Postgres
# ══════════════════════════════════════════════════════
@app.get("/api/inspection-records")
def list_inspection_records(prefix: str):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT object_name, record_by AS by, result, note "
                "FROM inspection_records WHERE object_name LIKE %s",
                (prefix + "%",)
            )
            rows = cur.fetchall()
    return {row["object_name"]: {"by": row["by"], "result": row["result"], "note": row["note"]} for row in rows}

@app.post("/api/inspection-records")
def upsert_inspection_record(body: InspectionRecordIn):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inspection_records (object_name, record_by, result, note, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (object_name) DO UPDATE
                SET record_by = EXCLUDED.record_by,
                    result = EXCLUDED.result,
                    note = EXCLUDED.note,
                    updated_at = NOW()
                """,
                (body.object_name, body.by, body.result, body.note)
            )
    return {"status": "ok", "object_name": body.object_name}

@app.delete("/api/inspection-records")
def delete_inspection_record(object_name: Optional[str] = None, prefix: Optional[str] = None):
    if not object_name and not prefix:
        raise HTTPException(status_code=400, detail="ต้องระบุ object_name หรือ prefix")
    with db() as conn:
        with conn.cursor() as cur:
            if object_name:
                cur.execute("DELETE FROM inspection_records WHERE object_name = %s", (object_name,))
            else:
                cur.execute("DELETE FROM inspection_records WHERE object_name LIKE %s", (prefix.rstrip("/") + "/%",))
    return {"status": "deleted"}

# ══════════════════════════════════════════════════════
#  ONLYOFFICE CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
# ══════════════════════════════════════════════════════
ONLYOFFICE_URL         = os.getenv("ONLYOFFICE_URL", "http://localhost:8080")
ONLYOFFICE_BACKEND_URL = os.getenv("ONLYOFFICE_BACKEND_URL", "http://host.docker.internal:8000")
ONLYOFFICE_JWT_SECRET  = os.getenv("ONLYOFFICE_JWT_SECRET", "")
ONLYOFFICE_DOCSERVER_URL = os.getenv("ONLYOFFICE_DOCSERVER_URL", "")

# นามสกุลไฟล์ที่ OnlyOffice รองรับการแก้ไข → documentType ที่ต้องส่งให้ DocEditor
ONLYOFFICE_DOC_TYPES = {
    "xlsx": "cell", "xls": "cell", "xlsm": "cell", "csv": "cell", "ods": "cell",
    "docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word",
    "pptx": "slide", "ppt": "slide", "odp": "slide",
}


@app.get("/api/onlyoffice/config")
def onlyoffice_config(object_name: str, username: str = "Guest"):
    """สร้าง config สำหรับ OnlyOffice DocEditor ของไฟล์ที่อยู่ใน MinIO"""
    ext = object_name.rsplit(".", 1)[-1].lower()
    doc_type = ONLYOFFICE_DOC_TYPES.get(ext)
    if not doc_type:
        raise HTTPException(400, f"File type '.{ext}' is not supported by OnlyOffice")

    try:
        stat = mc.stat_object(MINIO_BUCKET, object_name)
    except S3Error:
        raise HTTPException(404, "File not found in MinIO")

    filename = object_name.split("/")[-1]
    # key ต้องเปลี่ยนทุกครั้งที่ไฟล์เปลี่ยน เพื่อให้ OnlyOffice ไม่ใช้ cache เก่า
    etag = (stat.etag or "").strip('"')
    doc_key = hashlib.md5(f"{object_name}:{etag}".encode(), usedforsecurity=False).hexdigest()

    config = {
        "document": {
            "fileType": ext,
            "key": doc_key,
            "title": filename,
            "url": f"{ONLYOFFICE_BACKEND_URL}/api/onlyoffice/download?object_name={quote(object_name)}",
            "permissions": {"edit": True, "download": True, "print": True},
        },
        "documentType": doc_type,
        "editorConfig": {
            "callbackUrl": f"{ONLYOFFICE_BACKEND_URL}/api/onlyoffice/callback?object_name={quote(object_name)}",
            "lang": "en",
            "mode": "edit",
            "user": {"id": username, "name": username},
        },
        "type": "desktop",
    }

    if ONLYOFFICE_JWT_SECRET:
        config["token"] = jwt.encode(config, ONLYOFFICE_JWT_SECRET, algorithm="HS256")

    return {"config": config, "onlyofficeUrl": ONLYOFFICE_URL}


@app.get("/api/onlyoffice/download")
def onlyoffice_download(object_name: str):
    """ให้ OnlyOffice Document Server ดึงไฟล์ต้นฉบับจาก MinIO ไปเปิดแก้ไข"""
    try:
        response = mc.get_object(MINIO_BUCKET, object_name)
        data = response.read()
    except S3Error:
        raise HTTPException(404, "File not found")
    finally:
        with suppress(Exception):
            response.close()
            response.release_conn()

    media_type = mimetypes.guess_type(object_name)[0] or "application/octet-stream"
    filename = object_name.split("/")[-1]
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.post("/api/onlyoffice/callback")
async def onlyoffice_callback(object_name: str, request: Request):
    """OnlyOffice Document Server เรียก endpoint นี้เมื่อมีการบันทึกไฟล์ที่แก้ไข"""
    body = await request.json()

    if ONLYOFFICE_JWT_SECRET:
        auth_header = request.headers.get("Authorization", "")
        token = body.get("token") or auth_header.removeprefix("Bearer ")
        try:
            jwt.decode(token, ONLYOFFICE_JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(403, "Invalid JWT token")

    status = body.get("status")
    if status in (2, 6):  # 2 = MustSave, 6 = MustForceSave
        download_url = body.get("url")
        if download_url:
            if ONLYOFFICE_DOCSERVER_URL:
                import re
                download_url = re.sub(r'^https?://[^/]+', ONLYOFFICE_DOCSERVER_URL, download_url)
            resp = requests.get(download_url, timeout=60)
            resp.raise_for_status()
            data = resp.content
            mc.put_object(
                MINIO_BUCKET, object_name,
                io.BytesIO(data), length=len(data),
                content_type=mimetypes.guess_type(object_name)[0] or "application/octet-stream",
            )

    return {"error": 0}

# ══════════════════════════════════════════════════════
#  COMBINE FILES INTO ONE PDF (preview only — nothing saved to MinIO)
#  ใช้ OnlyOffice Document Server ที่มีอยู่แล้วแปลงแต่ละไฟล์เป็น PDF
#  แล้วต่อ (merge) หน้าทั้งหมดเป็น PDF เดียวด้วย pypdf
# ══════════════════════════════════════════════════════
ONLYOFFICE_CONVERT_BASE = ONLYOFFICE_DOCSERVER_URL or ONLYOFFICE_URL
# Converting one file at a time made "combine many files" requests take minutes and
# hit the reverse-proxy timeout — convert concurrently instead. Capped so a large
# selection doesn't flood the single OnlyOffice Document Server instance at once.
COMBINE_PDF_MAX_WORKERS = 5

class CombinePdfRequest(BaseModel):
    object_names: list[str]

def _convert_object_to_pdf_bytes(object_name: str) -> bytes:
    ext = object_name.rsplit(".", 1)[-1].lower()
    filename = object_name.split("/")[-1]

    if ext == "pdf":
        # Already a PDF (e.g. an Inspection Report folder whose original upload was
        # a PDF, not an Excel file) — nothing to convert, OnlyOffice's ConvertService
        # rejects a pdf->pdf request. Just fetch it from MinIO as-is.
        try:
            response = mc.get_object(MINIO_BUCKET, object_name)
            return response.read()
        except S3Error:
            raise HTTPException(404, f"ไม่พบไฟล์ '{filename}'")
        finally:
            with suppress(Exception):
                response.close()
                response.release_conn()

    body = {
        "async": False,
        "filetype": ext,
        "key": hashlib.md5(f"{object_name}:{uuid.uuid4()}".encode(), usedforsecurity=False).hexdigest(),
        "outputtype": "pdf",
        "title": filename,
        "url": f"{ONLYOFFICE_BACKEND_URL}/api/onlyoffice/download?object_name={quote(object_name)}",
    }
    if ONLYOFFICE_DOC_TYPES.get(ext) == "cell":
        # Scale each sheet down to fit on a single page (like Excel's "Fit Sheet on
        # One Page"), instead of OnlyOffice's default of splitting wide/tall sheets
        # across multiple PDF pages.
        body["spreadsheetLayout"] = {"fitToWidth": 1, "fitToHeight": 1}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if ONLYOFFICE_JWT_SECRET:
        token = jwt.encode(body, ONLYOFFICE_JWT_SECRET, algorithm="HS256")
        body["token"] = token
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.post(f"{ONLYOFFICE_CONVERT_BASE}/ConvertService.ashx", json=body, headers=headers, timeout=90)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("endConvert"):
        raise HTTPException(502, f"แปลง '{filename}' เป็น PDF ไม่สำเร็จ: {result.get('error', result)}")

    pdf_resp = requests.get(result["fileUrl"], timeout=90)
    pdf_resp.raise_for_status()
    return pdf_resp.content

@app.post("/api/combine-to-pdf")
def combine_to_pdf(payload: CombinePdfRequest):
    if not payload.object_names:
        raise HTTPException(400, "No files selected")

    # ThreadPoolExecutor.map preserves input order in its results even though the
    # underlying conversions complete concurrently/out of order.
    with ThreadPoolExecutor(max_workers=min(COMBINE_PDF_MAX_WORKERS, len(payload.object_names))) as executor:
        pdf_bytes_list = list(executor.map(_convert_object_to_pdf_bytes, payload.object_names))

    writer = PdfWriter()
    for pdf_bytes in pdf_bytes_list:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return Response(content=out.getvalue(), media_type="application/pdf")

@app.post("/api/combine-to-zip")
def combine_to_zip(payload: CombinePdfRequest):
    if not payload.object_names:
        raise HTTPException(400, "No files selected")

    out = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for object_name in payload.object_names:
            filename = object_name.split("/")[-1]
            if filename in used_names:
                stem, _, ext = filename.rpartition(".")
                filename = f"{stem}_{uuid.uuid4().hex[:6]}.{ext}" if ext else f"{filename}_{uuid.uuid4().hex[:6]}"
            used_names.add(filename)

            try:
                response = mc.get_object(MINIO_BUCKET, object_name)
                zf.writestr(filename, response.read())
            except S3Error:
                raise HTTPException(404, f"ไม่พบไฟล์ '{filename}'")
            finally:
                with suppress(Exception):
                    response.close()
                    response.release_conn()

    return Response(
        content=out.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=report_files.zip"},
    )

# ══════════════════════════════════════════════════════
#  ENSURE PATH IN MINIO
# ══════════════════════════════════════════════════════
class EnsurePath(BaseModel):
    path: str   # เช่น "PTTGC/" หรือ "PTTGC/A-MN/"

class RenamePath(BaseModel):
    old_path: str
    new_path: str

@app.post("/api/rename-path")
def rename_path(body: RenamePath):
    """เปลี่ยนชื่อ folder ใน MinIO โดย copy ทุกไฟล์ไป path ใหม่แล้วลบของเก่า"""
    from minio.commonconfig import CopySource
    old_prefix = body.old_path.rstrip("/") + "/"
    new_prefix = body.new_path.rstrip("/") + "/"
    moved = 0
    try:
        objects = list(mc.list_objects(MINIO_BUCKET, prefix=old_prefix, recursive=True))

        # Pass 1: สร้าง objects ใหม่ทั้งหมดก่อน (ใช้ put_object สำหรับ folder markers เพื่อกัน copy_object fail กับ zero-byte)
        for obj in objects:
            new_name = new_prefix + obj.object_name[len(old_prefix):]
            if obj.size == 0:
                mc.put_object(MINIO_BUCKET, new_name, io.BytesIO(b""), 0)
            else:
                mc.copy_object(MINIO_BUCKET, new_name, CopySource(MINIO_BUCKET, obj.object_name))
            moved += 1

        # สร้าง root folder marker ของ path ใหม่
        mc.put_object(MINIO_BUCKET, new_prefix, io.BytesIO(b""), 0)

        # Pass 2: ลบ objects เก่าทั้งหมด (หลัง copy ครบแล้ว ไม่ใช่ interleave กัน)
        for obj in objects:
            with suppress(S3Error):
                mc.remove_object(MINIO_BUCKET, obj.object_name)
        with suppress(S3Error):
            mc.remove_object(MINIO_BUCKET, old_prefix)

    except S3Error as e:
        raise HTTPException(500, f"Rename failed: {e}")
    return {"status": "renamed", "old": old_prefix, "new": new_prefix, "files_moved": moved}

# ══════════════════════════════════════════════════════
#  RENAME SINGLE FILE IN MINIO
# ══════════════════════════════════════════════════════
class RenameFile(BaseModel):
    old_object: str
    new_object: str

@app.post("/api/rename-file")
def rename_file(body: RenameFile):
    """เปลี่ยนชื่อไฟล์เดี่ยวใน MinIO (copy → delete เก่า)"""
    from minio.commonconfig import CopySource
    try:
        mc.copy_object(MINIO_BUCKET, body.new_object, CopySource(MINIO_BUCKET, body.old_object))
        mc.remove_object(MINIO_BUCKET, body.old_object)
    except S3Error as e:
        raise HTTPException(500, f"Rename file failed: {e}")
    return {"status": "renamed", "old": body.old_object, "new": body.new_object}

# ══════════════════════════════════════════════════════
#  COPY SINGLE FILE IN MINIO (ไม่ลบต้นฉบับ)
# ══════════════════════════════════════════════════════
class CopyFile(BaseModel):
    src_object: str
    dst_object: str

@app.post("/api/copy-file")
def copy_file(body: CopyFile):
    from minio.commonconfig import CopySource
    try:
        mc.copy_object(MINIO_BUCKET, body.dst_object, CopySource(MINIO_BUCKET, body.src_object))
    except S3Error as e:
        raise HTTPException(500, f"Copy failed: {e}")
    return {"status": "copied", "src": body.src_object, "dst": body.dst_object}

@app.post("/api/ensure-path")
def ensure_path(body: EnsurePath):
    path = body.path.strip("/") + "/"
    try:
        mc.stat_object(MINIO_BUCKET, path)
        return {"status": "exists", "path": path}
    except S3Error:
        mc.put_object(MINIO_BUCKET, path, io.BytesIO(b""), 0)
        return {"status": "created", "path": path}

# ══════════════════════════════════════════════════════
#  SHAREPOINT CONFIG  ← ตั้งค่าผ่านไฟล์ .env (ดู .env.example)
# ══════════════════════════════════════════════════════
SP_TENANT_ID     = os.getenv("SP_TENANT_ID", "")           # จาก Azure App Registration
SP_CLIENT_ID     = os.getenv("SP_CLIENT_ID", "")           # จาก Azure App Registration
SP_CLIENT_SECRET = os.getenv("SP_CLIENT_SECRET", "")       # จาก Azure App Registration
SP_SITE_HOSTNAME = os.getenv("SP_SITE_HOSTNAME", "")       # เช่น pttgc.sharepoint.com
SP_SITE_PATH     = os.getenv("SP_SITE_PATH", "")           # เช่น /sites/MESmartDocs
SP_FOLDER        = os.getenv("SP_FOLDER", "MinIO-Sync")    # ชื่อ folder ใน SharePoint ที่จะ sync

GRAPH_URL = "https://graph.microsoft.com/v1.0"


def _sp_token() -> str:
    """ขอ access token จาก Azure AD"""
    app = msal.ConfidentialClientApplication(
        SP_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{SP_TENANT_ID}",
        client_credential=SP_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise HTTPException(500, f"Azure auth failed: {result.get('error_description')}")
    return result["access_token"]


def _sp_drive_id(token: str) -> str:
    """หา drive ID ของ SharePoint site (Documents library)"""
    headers = {"Authorization": f"Bearer {token}"}
    site_resp = requests.get(
        f"{GRAPH_URL}/sites/{SP_SITE_HOSTNAME}:{SP_SITE_PATH}",
        headers=headers, timeout=15
    )
    site_resp.raise_for_status()
    site_id = site_resp.json()["id"]

    drives_resp = requests.get(f"{GRAPH_URL}/sites/{site_id}/drives", headers=headers, timeout=15)
    drives_resp.raise_for_status()
    drives = drives_resp.json()["value"]
    # ใช้ Documents library (drive แรก) หรือกรองตามชื่อ
    for d in drives:
        if d.get("driveType") == "documentLibrary":
            return d["id"]
    return drives[0]["id"]


# ══════════════════════════════════════════════════════
#  SHAREPOINT ENDPOINTS
# ══════════════════════════════════════════════════════

@app.get("/api/sharepoint-files")
def sharepoint_list_files():
    """แสดงรายการไฟล์ใน SharePoint folder ที่กำหนด"""
    token = _sp_token()
    drive_id = _sp_drive_id(token)
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(
        f"{GRAPH_URL}/drives/{drive_id}/root:/{SP_FOLDER}:/children",
        headers=headers, timeout=15
    )
    if resp.status_code == 404:
        return {"files": [], "message": f"Folder '{SP_FOLDER}' not found in SharePoint"}
    resp.raise_for_status()

    files = [
        {
            "name": item["name"],
            "size": item.get("size", 0),
            "last_modified": item.get("lastModifiedDateTime"),
            "sharepoint_id": item["id"],
        }
        for item in resp.json().get("value", [])
        if "file" in item
    ]
    return {"files": files, "folder": SP_FOLDER}


class PushRequest(BaseModel):
    object_name: str   # path ของไฟล์ใน MinIO เช่น "PTTGC/report.xlsx"
    sharepoint_subfolder: Optional[str] = None  # subfolder ใน SharePoint (optional)


@app.post("/api/push-to-sharepoint")
def push_to_sharepoint(body: PushRequest):
    """ดึงไฟล์จาก MinIO แล้วอัปโหลดขึ้น SharePoint"""
    # 1. ดึงไฟล์จาก MinIO
    try:
        response = mc.get_object(MINIO_BUCKET, body.object_name)
        file_data = response.read()
    except S3Error as e:
        raise HTTPException(404, f"MinIO file not found: {e}")

    filename = body.object_name.split("/")[-1]
    sp_path = f"{SP_FOLDER}/{body.sharepoint_subfolder}/{filename}" if body.sharepoint_subfolder else f"{SP_FOLDER}/{filename}"

    # 2. อัปโหลดไปยัง SharePoint ผ่าน Graph API
    token = _sp_token()
    drive_id = _sp_drive_id(token)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }

    upload_resp = requests.put(
        f"{GRAPH_URL}/drives/{drive_id}/root:/{sp_path}:/content",
        headers=headers,
        data=file_data,
        timeout=60,
    )
    upload_resp.raise_for_status()

    item = upload_resp.json()
    return {
        "status": "uploaded",
        "filename": filename,
        "sharepoint_path": sp_path,
        "sharepoint_web_url": item.get("webUrl"),
    }


class PullRequest(BaseModel):
    sharepoint_filename: str       # ชื่อไฟล์ใน SharePoint เช่น "report.xlsx"
    minio_target_path: str         # path ที่จะเก็บใน MinIO เช่น "PTTGC/from-sharepoint/"


@app.post("/api/pull-from-sharepoint")
def pull_from_sharepoint(body: PullRequest):
    """ดาวน์โหลดไฟล์จาก SharePoint แล้วเก็บลง MinIO"""
    token = _sp_token()
    drive_id = _sp_drive_id(token)
    headers = {"Authorization": f"Bearer {token}"}

    sp_path = f"{SP_FOLDER}/{body.sharepoint_filename}"

    # 1. ดาวน์โหลดจาก SharePoint
    dl_resp = requests.get(
        f"{GRAPH_URL}/drives/{drive_id}/root:/{sp_path}:/content",
        headers=headers, timeout=60, allow_redirects=True
    )
    if dl_resp.status_code == 404:
        raise HTTPException(404, f"File '{body.sharepoint_filename}' not found in SharePoint folder '{SP_FOLDER}'")
    dl_resp.raise_for_status()

    file_data = dl_resp.content
    filename = body.sharepoint_filename
    minio_path = body.minio_target_path.rstrip("/") + "/" + filename

    # 2. อัปโหลดเข้า MinIO
    mc.put_object(
        MINIO_BUCKET, minio_path,
        io.BytesIO(file_data), length=len(file_data),
        content_type="application/octet-stream",
    )

    return {
        "status": "saved_to_minio",
        "minio_path": minio_path,
        "size_bytes": len(file_data),
    }


# ══════════════════════════════════════════════════════
#  RUN:  uvicorn server:app --reload --port 8000
# ══════════════════════════════════════════════════════
