import os
import uuid
from typing import Optional, List
from fastapi import FastAPI, File, Form, UploadFile, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from agents.collector.models import RawAd, PlatformType
from agents.collector.service import CollectorService
from agents.collector.filter import check_relevance
from database.repository import AdRepository

app = FastAPI(title="SAQ QURYLYS - Monitoring Risk Engine")

# Setup uploads directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Static files for uploaded images and Web UI
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/", response_class=HTMLResponse)
def index_page():
    if os.path.exists("static/index.html"):
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>SAQ QURYLYS API</h1>"

repo = AdRepository()
collector_service = CollectorService()

class RunCollectorRequest(BaseModel):
    source: str
    query_or_url: str

class CollectorRunResponse(BaseModel):
    status: str
    count: int
    duplicates: int
    ads: List[RawAd]

@app.post("/api/collector/run", response_model=CollectorRunResponse)
def run_collector(req: RunCollectorRequest):
    try:
        ads = collector_service.collect(req.source, req.query_or_url)
        saved_count = 0
        dup_count = 0

        for ad in ads:
            if repo.save_ad(ad):
                saved_count += 1
            else:
                dup_count += 1

        return CollectorRunResponse(
            status="success",
            count=saved_count,
            duplicates=dup_count,
            ads=ads
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/ads", response_model=List[RawAd])
def get_ads(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_demo: Optional[bool] = Query(None)
):
    return repo.get_ads(platform=platform, status=status, is_demo=is_demo)

@app.post("/api/ads", response_model=RawAd)
async def create_ad_manual(
    platform: str = Form("manual"),
    account: Optional[str] = Form("Аналитик MIO"),
    url: Optional[str] = Form("https://manual-entry.local/ad"),
    text: str = Form(...),
    is_demo: bool = Form(False),
    file: Optional[UploadFile] = File(None)
):
    image_path = None
    if file:
        file_ext = os.path.splitext(file.filename)[1]
        file_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        image_path = f"/uploads/{file_name}"

    # Determine status & relevance
    is_rel, reason = check_relevance(text)
    status = "new" if is_rel else "filtered"
    status_reason = None if is_rel else reason

    ad = RawAd(
        id=f"manual-{uuid.uuid4().hex[:8]}",
        platform=platform if platform in ["krisha", "telegram", "instagram", "manual", "demo"] else "manual",
        account=account or "Аналитик MIO",
        url=url or "https://manual-entry.local/ad",
        text=text,
        image_path=image_path,
        is_demo=is_demo,
        status=status,
        status_reason=status_reason
    )

    if not repo.save_ad(ad):
        raise HTTPException(status_code=400, detail="Дубликат публикации уже существует в базе")

    return ad
