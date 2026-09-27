from __future__ import annotations

import datetime as dt
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select

from ..config import settings
from ..db import ping, session
from ..delivery.csv_export import default_filename, leads_to_csv
from ..matching import build_leads
from ..models import Company, JobPosting, Recruiter, Watchlist
from ..observability import REGISTRY
from ..security import parse_unsubscribe_token

app = FastAPI(
    title="HiringLeads API",
    version="1.0.0",
    description="Public company-level hiring signal intelligence for recruiting teams.",
)


async def auth(x_api_key: str = Header(default="")) -> None:
    if not x_api_key or not hmac.compare_digest(x_api_key, settings().api_key):
        raise HTTPException(status_code=401, detail="invalid api key")


class RecruiterIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    name: str | None = Field(default=None, max_length=200)
    agency: str | None = Field(default=None, max_length=200)
    plan: str = Field(default="trial", max_length=40)


class WatchlistIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    role_families: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    exclude_skills: list[str] = Field(default_factory=list)
    seniorities: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    min_score: float = Field(default=45.0, ge=0, le=100)
    max_age_days: int = Field(default=14, ge=1, le=90)
    daily_cap: int = Field(default=40, ge=1, le=500)
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def cap_filter_lists(self) -> "WatchlistIn":
        for name in (
            "role_families",
            "skills",
            "exclude_skills",
            "seniorities",
            "countries",
            "regions",
            "include_keywords",
            "exclude_keywords",
        ):
            values = getattr(self, name)
            if len(values) > 50:
                raise ValueError(f"{name} supports at most 50 entries")
            if any(len(str(value)) > 100 for value in values):
                raise ValueError(f"{name} entries must be <= 100 characters")
        return self


class LeadOut(BaseModel):
    score: float
    company: str
    domain: str | None
    open_roles_band: str | None
    title: str
    role_family: str | None
    seniority: str | None
    skills: list[str]
    evidence: list[str]
    location: str
    remote_type: str | None
    url: str
    apply_url: str | None
    first_seen_at: dt.datetime
    posted_at: dt.datetime | None
    open_roles_30d: int
    open_roles_total: int
    is_repost: bool


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "hiringleads-api",
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@app.get("/readyz")
async def readyz() -> dict:
    try:
        await ping()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"ok": True}


@app.get("/metrics")
async def metrics() -> Response:
    if not settings().metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/recruiters", dependencies=[Depends(auth)])
async def create_recruiter(body: RecruiterIn) -> dict:
    email = str(body.email).casefold()
    async with session() as db:
        existing = (
            await db.execute(select(Recruiter).where(Recruiter.email == email))
        ).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "existing": True}

        recruiter = Recruiter(
            email=email,
            name=body.name,
            agency=body.agency,
            plan=body.plan,
        )
        db.add(recruiter)
        await db.flush()
        return {"id": recruiter.id, "existing": False}


@app.post("/recruiters/{recruiter_id}/watchlists", dependencies=[Depends(auth)])
async def create_watchlist(
    recruiter_id: int,
    body: WatchlistIn,
) -> dict:
    async with session() as db:
        recruiter = await db.get(Recruiter, recruiter_id)
        if recruiter is None:
            raise HTTPException(404, "recruiter not found")

        payload = body.model_dump()
        payload["role_families"] = [str(v).casefold() for v in payload["role_families"]]
        payload["skills"] = [str(v).casefold() for v in payload["skills"]]
        payload["exclude_skills"] = [str(v).casefold() for v in payload["exclude_skills"]]
        payload["seniorities"] = [str(v).casefold() for v in payload["seniorities"]]
        payload["countries"] = [str(v).upper() for v in payload["countries"]]
        payload["regions"] = [str(v).upper() for v in payload["regions"]]

        watchlist = Watchlist(recruiter_id=recruiter_id, **payload)
        db.add(watchlist)
        await db.flush()
        return {"id": watchlist.id}


@app.get(
    "/watchlists/{watchlist_id}/leads",
    response_model=list[LeadOut],
    dependencies=[Depends(auth)],
)
async def get_leads(
    watchlist_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    since_hours: int = Query(default=168, ge=1, le=24 * 90),
) -> list[LeadOut]:
    async with session() as db:
        watchlist = await db.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(404, "watchlist not found")

        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
        leads = await build_leads(
            db,
            watchlist,
            since=since,
            exclude_delivered=False,
            limit=limit,
        )
        return [
            LeadOut(
                score=lead.score,
                company=lead.company,
                domain=lead.domain,
                open_roles_band=lead.open_roles_band,
                title=lead.title,
                role_family=lead.role_family,
                seniority=lead.seniority,
                skills=lead.skills,
                evidence=lead.evidence,
                location=", ".join(
                    filter(None, [lead.city, lead.region, lead.country])
                ),
                remote_type=lead.remote_type,
                url=lead.url,
                apply_url=lead.apply_url,
                first_seen_at=lead.first_seen_at,
                posted_at=lead.posted_at,
                open_roles_30d=lead.open_roles_30d,
                open_roles_total=lead.open_roles_total,
                is_repost=lead.is_repost,
            )
            for lead in leads
        ]


@app.get("/watchlists/{watchlist_id}/leads.csv", dependencies=[Depends(auth)])
async def get_leads_csv(
    watchlist_id: int,
    since_hours: int = Query(default=168, ge=1, le=24 * 90),
) -> Response:
    async with session() as db:
        watchlist = await db.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(404, "watchlist not found")

        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
        leads = await build_leads(
            db,
            watchlist,
            since=since,
            exclude_delivered=False,
        )
        filename = default_filename(watchlist.name)
        return Response(
            content=leads_to_csv(leads),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@app.get("/companies", dependencies=[Depends(auth)])
async def list_companies(
    hiring_roles: int = Query(default=3, ge=1, le=500),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=100000),
) -> list[dict]:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    async with session() as db:
        rows = (
            await db.execute(
                select(
                    Company.id,
                    Company.name,
                    Company.domain,
                    Company.hq_country,
                    Company.open_roles_band,
                    func.count(JobPosting.id).label("open_roles"),
                )
                .join(JobPosting, JobPosting.company_id == Company.id)
                .where(
                    JobPosting.is_active.is_(True),
                    JobPosting.first_seen_at >= since,
                )
                .group_by(Company.id)
                .having(func.count(JobPosting.id) >= hiring_roles)
                .order_by(func.count(JobPosting.id).desc(), Company.name.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()

        return [
            {
                "id": row[0],
                "name": row[1],
                "domain": row[2],
                "country": row[3],
                "open_roles_band": row[4],
                "open_roles": row[5],
            }
            for row in rows
        ]


async def _unsubscribe(token: str) -> dict:
    watchlist_id = parse_unsubscribe_token(token)
    if watchlist_id is None:
        raise HTTPException(400, "invalid unsubscribe token")

    async with session() as db:
        watchlist = await db.get(Watchlist, watchlist_id)
        if watchlist is None:
            raise HTTPException(404, "watchlist not found")
        watchlist.email_enabled = False
        return {"ok": True, "watchlist_id": watchlist.id}


@app.get("/unsubscribe/{token}", response_class=Response)
async def unsubscribe_get(token: str) -> Response:
    # GET is confirmation-only so link scanners/prefetchers cannot silently
    # unsubscribe a real recipient.
    if parse_unsubscribe_token(token) is None:
        return Response(
            content="<html><body><h1>Invalid unsubscribe link</h1></body></html>",
            status_code=400,
            media_type="text/html",
        )
    html = f"""
    <html><body>
      <h1>Unsubscribe</h1>
      <p>Stop hiring-lead emails for this watchlist?</p>
      <form method="post" action="/unsubscribe/{token}">
        <button type="submit">Confirm unsubscribe</button>
      </form>
    </body></html>
    """
    return Response(content=html, media_type="text/html")


@app.post("/unsubscribe/{token}", response_model=dict)
async def unsubscribe_post(token: str) -> dict:
    return await _unsubscribe(token)
