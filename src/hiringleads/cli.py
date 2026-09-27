"""Operator CLI. This is the tool you actually live in during the pilot."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import settings
from .db import create_all, session, session_factory
from .delivery.csv_export import default_filename, leads_to_csv_bytes
from .delivery.runner import deliver_all
from .discovery.probe import discover_via_commoncrawl, probe_domain
from .discovery.seed import seed_boards
from .matching import build_leads
from .models import Recruiter, Watchlist
from .pipeline import run_all, run_board, summarize, upsert_board
from .sources.base import HttpClient

app = typer.Typer(help="HiringLeads operator CLI", no_args_is_help=True)
console = Console()

db_app = typer.Typer(help="Database")
seed_app = typer.Typer(help="Seed / discovery")
ing_app = typer.Typer(help="Ingestion")
lead_app = typer.Typer(help="Leads")
app.add_typer(db_app, name="db")
app.add_typer(seed_app, name="seed")
app.add_typer(ing_app, name="ingest")
app.add_typer(lead_app, name="leads")


# ------------------------------------------------------------------ db
@db_app.command("init")
def db_init() -> None:
    """Create tables for local development only."""
    if not settings().auto_create_schema:
        console.print("[yellow]HL_AUTO_CREATE_SCHEMA=false; use `hl db upgrade` instead.[/yellow]")
        raise typer.Exit(2)
    asyncio.run(create_all())
    console.print("[green]schema ready[/green]")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to the configured database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings().database_url)
    command.upgrade(cfg, "head")
    console.print("[green]migrations applied[/green]")


@db_app.command("current")
def db_current() -> None:
    """Show current Alembic revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings().database_url)
    command.current(cfg)


# ------------------------------------------------------------------ seed
@seed_app.command("seeds")
def seed_seeds() -> None:
    """Load the curated seed board list."""

    async def _run() -> int:
        async with session() as s:
            n = 0
            for b in seed_boards():
                await upsert_board(
                    s,
                    provider=b.provider,
                    token=b.token,
                    url=b.url,
                    company_name=b.company_name,
                    discovered_via="seed",
                )
                n += 1
            return n

    n = asyncio.run(_run())
    console.print(f"[green]loaded {n} seed boards[/green]")


@seed_app.command("probe")
def seed_probe(domain: str) -> None:
    """Probe one company domain for any supported ATS board."""

    async def _run():
        client = HttpClient()
        try:
            found = await probe_domain(client, domain)
            return [(b.provider, b.token, b.url) for b in found]
        finally:
            await client.aclose()

    found = asyncio.run(_run())
    if not found:
        console.print(f"[yellow]no board found for {domain}[/yellow]")
        raise typer.Exit(1)
    for provider, token, url in found:
        console.print(f"  [cyan]{provider}[/cyan]  token=[bold]{token}[/bold]  {url}")


@seed_app.command("crawl")
def seed_crawl(pages: int = 2, limit: int = 2000) -> None:
    """Grow the registry via Common Crawl. Expect thousands of boards."""

    async def _run() -> tuple[int, int]:
        client = HttpClient()
        try:
            boards = await discover_via_commoncrawl(client, pages_per_target=pages)
            async with session() as s:
                n = 0
                for b in boards[:limit]:
                    await upsert_board(
                        s, provider=b.provider, token=b.token, url=b.url,
                        discovered_via="commoncrawl",
                    )
                    n += 1
                return len(boards), n
        finally:
            await client.aclose()

    found, added = asyncio.run(_run())
    console.print(f"[green]discovered {found}, upserted {added}[/green]")


@seed_app.command("boards")
def seed_boards_list(provider: str | None = None, limit: int = 200) -> None:
    """List registered boards."""
    from sqlalchemy import select

    from .models import JobBoard

    async def _run():
        async with session() as s:
            q = select(JobBoard).limit(limit)
            if provider:
                q = q.where(JobBoard.provider == provider)
            return [
                (b.id, b.provider, b.token, b.is_active, b.last_job_count)
                for b in (await s.execute(q)).scalars()
            ]

    rows = asyncio.run(_run())
    t = Table("id", "provider", "token", "active", "jobs")
    for r in rows:
        t.add_row(str(r[0]), r[1], r[2], "✓" if r[3] else "✗", str(r[4]))
    console.print(t)


# ------------------------------------------------------------------ ingest
@ing_app.command("run")
def ingest_run(
    provider: str | None = None,
    limit: int | None = None,
    concurrency: int = 8,
) -> None:
    """Run the ingestion pipeline."""

    async def _run():
        client = HttpClient()
        try:
            return await run_all(
                session_factory(), client, provider=provider, limit=limit, concurrency=concurrency
            )
        finally:
            await client.aclose()

    results = asyncio.run(_run())
    s = summarize(results)
    t = Table("metric", "value")
    for k, v in s.items():
        t.add_row(k, str(v))
    console.print(t)

    failures = [r for r in results if r.error]
    if failures:
        console.print(f"[yellow]{len(failures)} boards failed[/yellow]")
        for r in failures[:10]:
            console.print(f"  [red]{r.provider}/{r.token}[/red] {r.error}")


@ing_app.command("board")
def ingest_board_cmd(board_id: int) -> None:
    """Ingest a single board, verbosely."""

    async def _run():
        client = HttpClient()
        try:
            async with session() as s:
                return await run_board(s, board_id, client)
        finally:
            await client.aclose()

    r = asyncio.run(_run())
    console.print_json(json.dumps(asdict(r) if is_dataclass(r) else r, default=str))


# ------------------------------------------------------------------ leads
@lead_app.command("add-recruiter")
def lead_add_recruiter(
    email: str,
    name: str = "",
    agency: str = "",
    plan: str = "trial",
) -> None:
    async def _run() -> int:
        async with session() as s:
            r = Recruiter(email=email, name=name or None, agency=agency or None, plan=plan)
            s.add(r)
            await s.flush()
            return r.id

    rid = asyncio.run(_run())
    console.print(f"[green]recruiter {rid} created[/green]")


@lead_app.command("add-watchlist")
def lead_add_watchlist(
    recruiter_id: int,
    name: str,
    families: str = typer.Option("", help="comma-separated role families"),
    skills: str = typer.Option("", help="comma-separated skills"),
    countries: str = typer.Option("", help="comma-separated ISO country codes"),
    seniorities: str = typer.Option("", help="comma-separated seniorities"),
    exclude_skills: str = typer.Option("", help="comma-separated skills to exclude"),
    include_keywords: str = typer.Option("", help="comma-separated title keywords required"),
    min_score: float = 45.0,
    max_age_days: int = 14,
    daily_cap: int = 40,
    remote_ok: bool = True,
) -> None:
    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    async def _run() -> int:
        async with session() as s:
            wl = Watchlist(
                recruiter_id=recruiter_id,
                name=name,
                role_families=_split(families),
                skills=_split(skills),
                exclude_skills=_split(exclude_skills),
                seniorities=_split(seniorities),
                countries=_split(countries),
                remote_ok=remote_ok,
                min_score=min_score,
                max_age_days=max_age_days,
                daily_cap=daily_cap,
                include_keywords=_split(include_keywords),
            )
            s.add(wl)
            await s.flush()
            return wl.id

    wid = asyncio.run(_run())
    console.print(f"[green]watchlist {wid} created[/green]")


@lead_app.command("preview")
def lead_preview(
    watchlist_id: int,
    limit: int = 30,
    hours: int = 168,
    export: Path | None = None,
) -> None:
    """Preview leads for a watchlist without marking them delivered.

    This is your free-sample generator. Run it against a prospect's stated
    specialty, export CSV, attach to the outreach email.
    """

    async def _run():
        async with session() as s:
            wl = await s.get(Watchlist, watchlist_id)
            if wl is None:
                raise typer.BadParameter(f"watchlist {watchlist_id} not found")
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
            return wl, await build_leads(
                s, wl, since=since, exclude_delivered=False, limit=limit
            )

    wl, leads = asyncio.run(_run())

    if not leads:
        console.print("[yellow]no leads matched[/yellow]")
        raise typer.Exit(1)

    t = Table("score", "company", "title", "loc", "roles30d", "first seen", show_lines=False)
    for l in leads:
        loc = l.city or l.country or l.remote_type or "?"
        t.add_row(
            f"{l.score:.0f}",
            l.company[:28],
            l.title[:46],
            loc[:18],
            str(l.open_roles_30d),
            l.first_seen_at.strftime("%m-%d %H:%M"),
        )
    console.print(t)
    console.print(f"[dim]{len(leads)} leads for '{wl.name}'[/dim]")

    if export:
        export.write_bytes(leads_to_csv_bytes(leads))
        console.print(f"[green]wrote {export}[/green]")


@lead_app.command("sample")
def lead_sample(
    watchlist_id: int,
    out_dir: Path = Path("./samples"),
    limit: int = 120,
    hours: int = 336,
) -> None:
    """Generate a pilot sample: CSV + a summary you can paste into outreach."""
    out_dir.mkdir(parents=True, exist_ok=True)

    async def _run():
        async with session() as s:
            wl = await s.get(Watchlist, watchlist_id)
            if wl is None:
                raise typer.BadParameter("watchlist not found")
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
            return wl, await build_leads(
                s, wl, since=since, exclude_delivered=False, limit=limit
            )

    wl, leads = asyncio.run(_run())
    if not leads:
        console.print("[yellow]no leads[/yellow]")
        raise typer.Exit(1)

    csv_path = out_dir / default_filename(wl.name)
    csv_path.write_bytes(leads_to_csv_bytes(leads))

    lines = [f"Sample: {len(leads)} companies hiring {wl.name}", ""]
    for l in leads[:12]:
        loc = l.city or l.country or ("Remote" if l.remote_type == "remote" else "—")
        lines.append(f"• {l.company} — {l.title} — {loc}")
    lines += ["", f"Full list: {csv_path.name}"]
    (out_dir / "outreach_snippet.txt").write_text("\n".join(lines), encoding="utf-8")

    console.print(f"[green]wrote {csv_path}[/green]")
    console.print("\n".join(lines[:16]))


@lead_app.command("deliver")
def lead_deliver(dry_run: bool = False) -> None:
    """Send today's digests."""

    async def _run():
        return await deliver_all(dry_run=dry_run)

    stats = asyncio.run(_run())
    console.print_json(json.dumps(stats))


@lead_app.command("hot-companies")
def lead_hot_companies(days: int = 30, min_roles: int = 5, limit: int = 60) -> None:
    """Companies with the most open roles in the window. The BD shortlist."""
    from sqlalchemy import func, select

    from .models import Company, JobPosting

    async def _run():
        async with session() as s:
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
            rows = (
                await s.execute(
                    select(
                        Company.name, Company.domain, Company.hq_country,
                        func.count(JobPosting.id).label("n"),
                    )
                    .join(JobPosting, JobPosting.company_id == Company.id)
                    .where(JobPosting.is_active.is_(True), JobPosting.first_seen_at >= since)
                    .group_by(Company.id)
                    .having(func.count(JobPosting.id) >= min_roles)
                    .order_by(func.count(JobPosting.id).desc())
                    .limit(limit)
                )
            ).all()
            return rows

    rows = asyncio.run(_run())
    t = Table("company", "domain", "country", "open roles")
    for name, domain, country, n in rows:
        t.add_row(name[:34], (domain or "")[:30], country or "", str(n))
    console.print(t)


@lead_app.command("stats")
def lead_stats() -> None:
    """Pipeline health."""
    from sqlalchemy import func, select

    from .models import Company, JobBoard, JobPosting

    async def _run():
        async with session() as s:
            boards = (await s.execute(select(func.count()).select_from(JobBoard))).scalar_one()
            companies = (await s.execute(select(func.count()).select_from(Company))).scalar_one()
            active = (
                await s.execute(
                    select(func.count()).select_from(JobPosting).where(JobPosting.is_active.is_(True))
                )
            ).scalar_one()
            fresh = (
                await s.execute(
                    select(func.count())
                    .select_from(JobPosting)
                    .where(
                        JobPosting.is_active.is_(True),
                        JobPosting.first_seen_at
                        >= dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
                    )
                )
            ).scalar_one()
            return boards, companies, active, fresh

    boards, companies, active, fresh = asyncio.run(_run())
    t = Table("metric", "value")
    t.add_row("boards", str(boards))
    t.add_row("companies", str(companies))
    t.add_row("active postings", str(active))
    t.add_row("new in last 24h", str(fresh))
    console.print(t)


if __name__ == "__main__":
    app()
