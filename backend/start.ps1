# รัน FastAPI server ผ่าน WSL (เพราะ Podman MinIO เข้าถึงได้จาก WSL เท่านั้น)
$project = "/mnt/c/Users/26009623/Downloads/ME_Smart_Coding_Alphaproject2026/backend"

Write-Host "Installing dependencies in WSL..." -ForegroundColor Cyan
wsl -u root -- pip3 install fastapi uvicorn minio python-multipart --quiet

Write-Host "Starting FastAPI server on port 8000..." -ForegroundColor Green
wsl -u root -- bash -c "cd $project && uvicorn server:app --reload --host 0.0.0.0 --port 8000"
