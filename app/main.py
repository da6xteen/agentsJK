import os
import re
import uuid
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, File, Form, UploadFile, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from agents.collector.models import RawAd, PlatformType
from agents.collector.service import CollectorService
from agents.collector.filter import check_relevance
from agents.matcher.payment_extractor import PaymentExtractor
from agents.matcher.complex_matcher import ComplexMatcher
from agents.scoring import calculate_risk_score
from database.repository import AdRepository

app = FastAPI(title="SAQ QURYLYS - Monitoring Risk Engine")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

repo = AdRepository()
collector_service = CollectorService()
payment_extractor = PaymentExtractor(repo=repo)
complex_matcher = ComplexMatcher(repo=repo)

@app.get("/", response_class=HTMLResponse)
def index_page():
    if os.path.exists("static/index.html"):
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>SAQ QURYLYS API</h1>"

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

# Helper for ad current score
def _compute_ad_score(ad_id: str):
    hypotheses = repo.get_hypotheses_by_ad(ad_id)
    confirmed_factors = [
        h["type"] for h in hypotheses
        if h["status"] == "accepted" and h["type"] in ["R1", "R2", "R3", "R4", "R5", "R6"]
    ]
    return calculate_risk_score(confirmed_factors)

@app.post("/api/ads/{ad_id}/analyze")
def analyze_ad(ad_id: str):
    ad = repo.get_ad(ad_id)
    if not ad:
        raise HTTPException(status_code=404, detail="Публикация не найдена")

    created_hypotheses = []

    # 1. Part A: Payment Extractor (R2)
    pay_res = payment_extractor.process(text=ad.text, image_path=ad.image_path)
    if pay_res.offers_payment:
        r2_hyp = {
            "ad_id": ad.id,
            "type": "R2",
            "title": "R2: прямое предложение внести деньги",
            "description": pay_res.reasoning_short,
            "evidence_quote": pay_res.evidence_quote,
            "confidence": pay_res.confidence,
            "source": pay_res.source,
            "status": "pending",
            "payload_json": {
                "payment_type": pay_res.payment_type,
                "amount": pay_res.amount,
                "currency": pay_res.currency
            }
        }
        r2_id = repo.save_hypothesis(r2_hyp)
        r2_hyp["id"] = r2_id
        created_hypotheses.append(r2_hyp)

    # 2. R3: Advertising under construction housing
    norm_text = ad.text.lower()
    if any(k in norm_text for k in ["строящ", "новостройк", "котлован", "сдача", "долевое", "каркас"]):
        # Find quote for R3
        r3_quote = ""
        for line in ad.text.splitlines():
            if any(k in line.lower() for k in ["строящ", "новостройк", "котлован", "сдача", "долевое"]):
                r3_quote = line.strip()
                break
        if not r3_quote:
            r3_quote = ad.text[:100].strip()

        r3_hyp = {
            "ad_id": ad.id,
            "type": "R3",
            "title": "R3: реклама строящегося жилья",
            "description": "Обнаружена реклама строящегося ЖК / объекта долевого строительства.",
            "evidence_quote": r3_quote,
            "confidence": 0.90,
            "source": "rules",
            "status": "pending",
            "payload_json": {}
        }
        r3_id = repo.save_hypothesis(r3_hyp)
        r3_hyp["id"] = r3_id
        created_hypotheses.append(r3_hyp)

    # 3. Part B: Complex & Developer Matcher
    match_res = complex_matcher.process(ad_id=ad.id, text=ad.text, account=ad.account)
    if match_res.candidates:
        c_hyp = {
            "ad_id": ad.id,
            "type": "complex_link",
            "title": f"привязка к ЖК: {match_res.candidates[0].complex_name}",
            "description": match_res.reasoning,
            "evidence_quote": match_res.candidates[0].evidence_quotes[0] if match_res.candidates[0].evidence_quotes else "",
            "confidence": match_res.candidates[0].confidence,
            "source": match_res.source,
            "status": "pending",
            "payload_json": {
                "candidates": [c.model_dump() for c in match_res.candidates],
                "auto_linked": match_res.auto_linked,
                "top_candidate_id": match_res.top_candidate_id,
                "matcher_status": match_res.status
            }
        }
        c_id = repo.save_hypothesis(c_hyp)
        c_hyp["id"] = c_id
        created_hypotheses.append(c_hyp)

    score, zone_code, zone_label = _compute_ad_score(ad.id)
    related_ads = repo.get_related_ads(ad.account)

    return {
        "status": "success",
        "ad_id": ad.id,
        "created_hypotheses": created_hypotheses,
        "risk_score": score,
        "risk_zone": zone_code,
        "risk_label": zone_label,
        "related_ads_count": len(related_ads)
    }

@app.get("/api/ads/{ad_id}/hypotheses")
def get_ad_hypotheses(ad_id: str):
    ad = repo.get_ad(ad_id)
    if not ad:
        raise HTTPException(status_code=404, detail="Публикация не найдена")

    hypotheses = repo.get_hypotheses_by_ad(ad_id)
    score, zone_code, zone_label = _compute_ad_score(ad_id)
    related_ads = repo.get_related_ads(ad.account)

    return {
        "ad_id": ad_id,
        "hypotheses": hypotheses,
        "risk_score": score,
        "risk_zone": zone_code,
        "risk_label": zone_label,
        "related_ads": [a.model_dump() for a in related_ads if a.id != ad_id]
    }

class HypothesisActionRequest(BaseModel):
    author: Optional[str] = "Аналитик MIO"

@app.post("/api/hypotheses/{hyp_id}/accept")
def accept_hypothesis(hyp_id: str, req: HypothesisActionRequest = HypothesisActionRequest()):
    hyp = repo.get_hypothesis(hyp_id)
    if not hyp:
        raise HTTPException(status_code=404, detail="Гипотеза не найдена")

    ad_id = hyp["ad_id"]
    prev_score, _, _ = _compute_ad_score(ad_id)

    # Accept hypothesis
    repo.update_hypothesis_status(hyp_id, "accepted")

    # Compute new score
    new_score, new_zone, new_label = _compute_ad_score(ad_id)

    # If hypothesis is complex_link, update complex risk score
    if hyp["type"] == "complex_link":
        p_data = hyp.get("payload", {})
        top_c_id = p_data.get("top_candidate_id")
        if top_c_id:
            repo.update_complex_risk(top_c_id, new_score, new_zone)

    # Audit log entry
    repo.save_audit_log(
        ad_id=ad_id,
        hypothesis_id=hyp_id,
        action="accept",
        author=req.author or "Аналитик MIO",
        prev_score=prev_score,
        new_score=new_score
    )

    return {
        "status": "success",
        "action": "accept",
        "hypothesis_id": hyp_id,
        "prev_score": prev_score,
        "new_score": new_score,
        "risk_zone": new_zone,
        "risk_label": new_label
    }

@app.post("/api/hypotheses/{hyp_id}/reject")
def reject_hypothesis(hyp_id: str, req: HypothesisActionRequest = HypothesisActionRequest()):
    hyp = repo.get_hypothesis(hyp_id)
    if not hyp:
        raise HTTPException(status_code=404, detail="Гипотеза не найдена")

    ad_id = hyp["ad_id"]
    prev_score, zone_code, zone_label = _compute_ad_score(ad_id)

    # Reject hypothesis
    repo.update_hypothesis_status(hyp_id, "rejected")

    # Score remains unchanged!
    new_score = prev_score

    # Audit log entry
    repo.save_audit_log(
        ad_id=ad_id,
        hypothesis_id=hyp_id,
        action="reject",
        author=req.author or "Аналитик MIO",
        prev_score=prev_score,
        new_score=new_score
    )

    return {
        "status": "success",
        "action": "reject",
        "hypothesis_id": hyp_id,
        "prev_score": prev_score,
        "new_score": new_score,
        "risk_zone": zone_code,
        "risk_label": zone_label
    }

@app.get("/api/complexes")
def list_complexes(q: Optional[str] = Query(None)):
    return repo.get_complexes(query=q)

@app.get("/api/complexes/{complex_id}")
def get_complex_details(complex_id: str):
    cplx = repo.get_complex_by_id(complex_id)
    if not cplx:
        raise HTTPException(status_code=404, detail="ЖК не найден")
    return cplx

@app.get("/api/audit-logs")
def list_audit_logs(ad_id: Optional[str] = Query(None)):
    return repo.get_audit_logs(ad_id=ad_id)
