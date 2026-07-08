from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.achievements import (
    achievement_progress,
    evaluate_achievements,
    mark_achievements_seen,
    unseen_achievements,
)
from app.ai.providers import provider_ready
from app.ai.service import (
    can_scan,
    run_photo_scan,
    scan_limit_for,
    scans_today,
    usage_summary,
)
from app.alerts import build_weekly_digests, mark_alerts_read, unread_alerts
from app.auth import (
    assert_admin,
    authenticate,
    create_user,
    delete_user_account,
    export_user_data,
)
from app.billing import (
    create_pro_checkout,
    ensure_plan_fresh,
    handle_yookassa_webhook,
    is_pro,
    redeem_promo,
    yookassa_configured,
)
from app.config import (
    FREE_ITEM_LIMIT,
    FREE_SCANS_PER_DAY,
    MAX_UPLOAD_BYTES,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
    PRO_ITEM_LIMIT,
    PRO_PRICE_RUB,
    PRO_PRICE_YEAR_RUB,
    PRO_SCANS_PER_DAY,
    PUBLIC_BASE_URL,
    SESSION_COOKIE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_SECRET,
    UPLOAD_DIR,
)
from app.fx import CURRENCY_META, DISPLAY_CURRENCIES, format_amount, get_rates
from app.regions import city_choices
from app.comps.sources.registry import INGESTABLE_SOURCES, SOURCE_LABELS
from app.jobs import (
    ingest_comp_aggregates,
    refresh_market_comps,
    revalue_all_items,
    shutdown_scheduler,
    start_scheduler,
)
from app.metrics import compute_metrics, track_event
from app.models import (
    CAR_DEFECTS,
    CATEGORY_LABELS,
    CONDITION_HINTS,
    CONDITION_LABELS,
    CONFIDENCE_LABELS,
    Category,
    Condition,
    DEFECT_LABELS,
    ELECTRONICS_DEFECTS,
    Item,
    CanonicalModel,
    ScanJob,
    User,
    WeeklyDigest,
    get_db,
    init_db,
    utcnow,
)
from app.seed import run_seed
from app.telegram.client import get_bot_username, telegram_configured
from app.telegram.handlers import handle_update
from app.telegram.linking import create_link_token, unlink_telegram
from app.telegram.setup import setup_telegram, shutdown_telegram
from app.telegram.webapp import user_from_init_data, validate_init_data
from app.sell_signal import FRIEND_LOOP_STEPS, build_sell_signal
from app.valuation import (
    compute_valuation,
    display_mid,
    latest_snapshot,
    save_snapshot,
)

BASE = Path(__file__).resolve().parent


class ThingsTemplates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):  # type: ignore[override]
        if "context" in kwargs:
            ctx = kwargs["context"]
        elif len(args) >= 2:
            ctx = args[1]
        else:
            ctx = {}
        if isinstance(ctx, dict):
            user = ctx.get("user")
            ctx.setdefault(
                "currency",
                (getattr(user, "display_currency", None) or "RUB") if user else "RUB",
            )
            ctx.setdefault("product_name", PRODUCT_NAME)
            ctx.setdefault("product_tagline", PRODUCT_TAGLINE)
            ctx.setdefault("fx_rates", get_rates())
        return super().TemplateResponse(*args, **kwargs)


templates = ThingsTemplates(directory=str(BASE / "templates"))

app = FastAPI(title=f"{PRODUCT_NAME} — портфель имущества", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@pass_context
def _fmt_money(ctx, value: Optional[float], currency: Optional[str] = None) -> str:
    cur = currency or (ctx.get("currency") if ctx else None) or "RUB"
    return format_amount(value, cur)


templates.env.filters["money"] = _fmt_money


def things_count_label(n: int) -> str:
    n = int(n or 0)
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        word = "вещь"
    elif mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        word = "вещи"
    else:
        word = "вещей"
    return f"{n} {word}"


def _pct(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return round(((new - old) / old) * 100.0, 1)


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%".replace(".", ",")


def spark_points(valuations, limit: int = 10) -> list[float]:
    vals = [v.mid for v in valuations[-limit:]] if valuations else []
    return vals


def week_ago_mid(valuations) -> Optional[float]:
    if not valuations:
        return None
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    def _aware(ts):
        if ts is None:
            return None
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    past = [v for v in valuations if _aware(v.ts) is not None and _aware(v.ts) <= cutoff]
    if past:
        return past[-1].mid
    if len(valuations) >= 2:
        return valuations[0].mid
    return valuations[-1].mid if valuations else None


def portfolio_story(
    total_mid: float,
    week_pct: Optional[float],
    item_count: int,
    top_mover: Optional[dict],
    currency: str = "RUB",
) -> str:
    """Bite-sized data story — Revolut/Artha style, CIS Gen Z tone."""
    if item_count == 0:
        return "Пока пусто. Добавь первую вещь — и увидишь, сколько она стоит на рынке."
    base = f"У тебя {things_count_label(item_count)} на ~{format_amount(total_mid, currency)}"
    if week_pct is None:
        return f"{base}. Следи за ценой как за тикером — без налоговой и без брокера."
    if abs(week_pct) < 0.3:
        mood = "за неделю почти без движения"
    elif week_pct > 0:
        mood = f"за неделю {_fmt_pct(week_pct)}"
    else:
        mood = f"за неделю {_fmt_pct(week_pct)}"
    if top_mover and top_mover.get("pct") is not None and abs(top_mover["pct"]) >= 1:
        direction = "вырос" if top_mover["pct"] > 0 else "просел"
        return (
            f"{base}, {mood}. "
            f"Главный мув: {top_mover['name']} {direction} на {_fmt_pct(top_mover['pct'])}."
        )
    return f"{base}, {mood}. Не инвест-совет — просто честный рынок б/у."


def model_label(model) -> str:
    """Avoid 'Toyota Toyota Camry' when name already includes brand."""
    if not model:
        return ""
    name = (model.name or "").strip()
    brand = (model.brand or "").strip()
    if brand and name.lower().startswith(brand.lower()):
        return name
    return f"{brand} {name}".strip()


templates.env.filters["pct"] = _fmt_pct
templates.env.filters["model_label"] = model_label
templates.env.filters["things_count"] = things_count_label
templates.env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
templates.env.globals["CONDITION_LABELS"] = CONDITION_LABELS
templates.env.globals["CONDITION_HINTS"] = CONDITION_HINTS
templates.env.globals["CONFIDENCE_LABELS"] = CONFIDENCE_LABELS
templates.env.globals["DEFECT_LABELS"] = DEFECT_LABELS
templates.env.globals["CURRENCY_META"] = CURRENCY_META
templates.env.globals["DISPLAY_CURRENCIES"] = DISPLAY_CURRENCIES
templates.env.globals["model_label"] = model_label
templates.env.globals["things_count_label"] = things_count_label
templates.env.globals["product_name"] = PRODUCT_NAME


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from app.models import SessionLocal, CanonicalModel
    from app.seed import ensure_catalog, run_seed

    db = SessionLocal()
    try:
        if db.query(CanonicalModel).count() == 0:
            run_seed(reset=False)
        else:
            ensure_catalog(db)
    finally:
        db.close()
    start_scheduler()
    setup_telegram()


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_scheduler()
    shutdown_telegram()


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    uid = request.cookies.get(SESSION_COOKIE)
    if not uid:
        return None
    try:
        return db.query(User).filter(User.id == int(uid)).first()
    except ValueError:
        return None


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def login_required_handler(_request: Request, _exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = get_current_user(request, db)
    if not user:
        raise LoginRequired()
    return ensure_plan_fresh(db, user)


def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """Admin gate: allowlisted email (session) and/or THINGS_ADMIN_API_KEY."""
    user = get_current_user(request, db)
    if user:
        user = ensure_plan_fresh(db, user)
    assert_admin(request, user)
    return user


def _achievement_toast(db: Session, user: User) -> list[dict]:
    """Evaluate, then return unseen unlocks for a one-shot toast (marks seen)."""
    evaluate_achievements(db, user.id)
    fresh = unseen_achievements(db, user.id)
    if fresh:
        mark_achievements_seen(db, user.id)
    return [
        {"id": a.id, "title": a.title, "description": a.description, "icon": a.icon}
        for a in fresh
    ]


def _set_session(resp: Response, user_id: int) -> None:
    resp.set_cookie(
        SESSION_COOKIE,
        str(user_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


# ---------- Public pages ----------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse("/portfolio", status_code=303)
    return templates.TemplateResponse("landing.html", {"request": request, "user": user})


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse("privacy.html", {"request": request, "user": user})


@app.get("/manifest.webmanifest")
def manifest():
    return Response(
        content=(BASE / "static" / "manifest.webmanifest").read_text(encoding="utf-8"),
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
def service_worker():
    return Response(
        content=(BASE / "static" / "sw.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse("/portfolio", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None, "error": None, "mode": "login"},
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse("/portfolio", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None, "error": None, "mode": "register"},
    )


@app.post("/login")
def login_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    user = authenticate(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "user": None,
                "error": "Неверный email или пароль",
                "mode": "login",
            },
            status_code=400,
        )
    resp = RedirectResponse("/portfolio", status_code=303)
    _set_session(resp, user.id)
    return resp


@app.post("/register")
def register_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
    accept_privacy: Annotated[Optional[str], Form()] = None,
    db: Session = Depends(get_db),
):
    if not accept_privacy:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "user": None,
                "error": "Нужно принять политику конфиденциальности",
                "mode": "register",
            },
            status_code=400,
        )
    if db.query(User).filter(User.email == email.lower().strip()).first():
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "user": None,
                "error": "Такой email уже зарегистрирован",
                "mode": "register",
            },
            status_code=400,
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "user": None,
                "error": "Пароль минимум 6 символов",
                "mode": "register",
            },
            status_code=400,
        )
    user = create_user(db, email, password, display_name, accept_privacy=True)
    track_event(db, user.id, "register", {})
    resp = RedirectResponse("/portfolio", status_code=303)
    _set_session(resp, user.id)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------- Portfolio ----------


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    track_event(db, user.id, "portfolio_view")
    items = (
        db.query(Item)
        .options(joinedload(Item.model), joinedload(Item.valuations))
        .filter(Item.owner_id == user.id)
        .order_by(Item.created_at.desc())
        .all()
    )

    rows = []
    total_mid = 0.0
    total_cost = 0.0
    history_map: dict[str, float] = {}
    week_old_total = 0.0
    top_mover = None

    for item in items:
        snap = latest_snapshot(item)
        mid = display_mid(item, snap)
        if mid is not None:
            total_mid += mid
        if item.cost_basis:
            total_cost += item.cost_basis

        delta = None
        delta_pct = None
        if mid is not None and item.cost_basis:
            delta = mid - item.cost_basis
            delta_pct = _pct(item.cost_basis, mid)

        past_mid = week_ago_mid(item.valuations)
        week_pct = _pct(past_mid, mid if item.override_mid is None else item.override_mid)
        if past_mid is not None:
            week_old_total += past_mid
        elif mid is not None:
            week_old_total += mid

        spark = spark_points(item.valuations)
        name = model_label(item.model)
        if week_pct is not None and (
            top_mover is None or abs(week_pct) > abs(top_mover.get("pct") or 0)
        ):
            top_mover = {"name": name, "pct": week_pct, "mid": mid}

        for v in item.valuations:
            day = v.ts.strftime("%Y-%m-%d")
            history_map[day] = history_map.get(day, 0) + (
                item.override_mid if item.override_mid is not None else v.mid
            )

        rows.append(
            {
                "item": item,
                "snap": snap,
                "mid": mid,
                "delta": delta,
                "delta_pct": delta_pct,
                "week_pct": week_pct,
                "spark_json": json.dumps(spark),
                "name": name,
            }
        )

    # Sort movers first (StockX-like: biggest weekly move on top), then by value
    rows.sort(
        key=lambda r: (
            -(abs(r["week_pct"]) if r["week_pct"] is not None else -1),
            -(r["mid"] or 0),
        )
    )

    history = [{"date": k, "total": history_map[k]} for k in sorted(history_map.keys())]
    portfolio_delta = (total_mid - total_cost) if total_cost else None
    portfolio_delta_pct = _pct(total_cost, total_mid) if total_cost else None
    week_pct_total = _pct(week_old_total, total_mid) if week_old_total else None
    story = portfolio_story(
        total_mid, week_pct_total, len(rows), top_mover, user.display_currency or "RUB"
    )
    alerts = unread_alerts(db, user.id, limit=5)
    toast = _achievement_toast(db, user)
    progress = achievement_progress(db, user.id)

    return templates.TemplateResponse(
        "portfolio.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "total_mid": total_mid,
            "total_cost": total_cost,
            "portfolio_delta": portfolio_delta,
            "portfolio_delta_pct": portfolio_delta_pct,
            "week_pct_total": week_pct_total,
            "story": story,
            "history_json": json.dumps(history, ensure_ascii=False),
            "alerts": alerts,
            "achievement_toast": toast,
            "achievement_progress": progress,
        },
    )


# ---------- Items ----------


@app.get("/items/new", response_class=HTMLResponse)
def new_item_page(
    request: Request,
    category: Optional[str] = None,
    q: Optional[str] = None,
    model_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    models = []
    selected = None
    if model_id:
        selected = db.query(CanonicalModel).filter(CanonicalModel.id == model_id).first()
        if selected and not category:
            category = selected.category
    if category in {c.value for c in Category}:
        query = db.query(CanonicalModel).filter(CanonicalModel.category == category)
        if q:
            like = f"%{q.lower().strip()}%"
            query = query.filter(CanonicalModel.search_text.like(like))
        models = query.order_by(CanonicalModel.brand, CanonicalModel.name).limit(40).all()
        if selected and selected not in models:
            models = [selected] + models

    if category == Category.CAR.value:
        defects = CAR_DEFECTS
    elif category in (Category.SMARTPHONE.value, Category.LAPTOP.value):
        defects = ELECTRONICS_DEFECTS
    else:
        defects = []

    return templates.TemplateResponse(
        "item_new.html",
        {
            "request": request,
            "user": user,
            "category": category,
            "q": q or "",
            "models": models,
            "selected": selected,
            "conditions": list(Condition),
            "defects": defects,
            "cities": city_choices(),
            "error": None,
        },
    )


@app.post("/items/new")
async def create_item(
    request: Request,
    category: Annotated[str, Form()],
    canonical_model_id: Annotated[int, Form()],
    condition: Annotated[str, Form()],
    location_city: Annotated[str, Form()] = "Москва",
    location_region: Annotated[str, Form()] = "Москва",
    cost_basis: Annotated[Optional[str], Form()] = None,
    notes: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    form = await request.form()
    defect_flags = [k.replace("defect_", "") for k in form.keys() if k.startswith("defect_")]

    count = db.query(Item).filter(Item.owner_id == user.id).count()
    limit = PRO_ITEM_LIMIT if is_pro(user) else FREE_ITEM_LIMIT
    if count >= limit:
        if not is_pro(user):
            track_event(db, user.id, "hit_limit", {"kind": "items", "limit": limit})
        return templates.TemplateResponse(
            "item_new.html",
            {
                "request": request,
                "user": user,
                "category": category,
                "q": "",
                "models": [],
                "selected": db.get(CanonicalModel, canonical_model_id),
                "conditions": list(Condition),
                "defects": ELECTRONICS_DEFECTS
                if category != Category.CAR.value
                else CAR_DEFECTS,
                "cities": city_choices(),
                "error": f"Лимит тарифа: {limit} вещей"
                + ("" if is_pro(user) else " · активируй Pro в аккаунте"),
                "paywall": not is_pro(user),
            },
            status_code=400,
        )

    model = db.query(CanonicalModel).filter(CanonicalModel.id == canonical_model_id).first()
    if not model or model.category != category:
        raise HTTPException(400, "Модель не найдена")

    cost = None
    if cost_basis and cost_basis.strip():
        cost = float(cost_basis.replace(" ", "").replace(",", "."))

    item = Item(
        owner_id=user.id,
        category=category,
        canonical_model_id=model.id,
        condition=condition,
        defects=",".join(sorted(defect_flags)),
        location_city=location_city.strip() or "Москва",
        location_region=location_region.strip() or location_city.strip() or "Москва",
    )
    item.cost_basis = cost
    item.notes = notes.strip()
    db.add(item)
    db.commit()
    db.refresh(item)
    save_snapshot(db, item)
    track_event(db, user.id, "item_add", {"item_id": item.id, "category": category})
    evaluate_achievements(db, user.id)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    item = (
        db.query(Item)
        .options(joinedload(Item.model), joinedload(Item.valuations))
        .filter(Item.id == item_id, Item.owner_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404)

    snap = latest_snapshot(item)
    market = compute_valuation(db, item)
    mid = display_mid(item, snap)
    delta = (mid - item.cost_basis) if (mid is not None and item.cost_basis) else None
    delta_pct = _pct(item.cost_basis, mid) if item.cost_basis else None
    past_mid = week_ago_mid(item.valuations)
    week_pct = _pct(past_mid, mid if item.override_mid is None else item.override_mid)
    sell = build_sell_signal(
        mid=mid,
        valuations=item.valuations or [],
        comps_count=market.comps_count,
        insufficient_data=market.insufficient_data,
        freshness_days=market.freshness_days,
        confidence=market.confidence,
        low=market.low,
        high=market.high,
        trend_days=30,
    )

    history = [
        {
            "date": v.ts.strftime("%Y-%m-%d"),
            "mid": v.mid,
            "low": v.low,
            "high": v.high,
        }
        for v in item.valuations
    ]

    defects = CAR_DEFECTS if item.category == Category.CAR.value else ELECTRONICS_DEFECTS

    return templates.TemplateResponse(
        "item_detail.html",
        {
            "request": request,
            "user": user,
            "item": item,
            "snap": snap,
            "market": market,
            "mid": mid,
            "delta": delta,
            "delta_pct": delta_pct,
            "week_pct": week_pct,
            "sell": sell,
            "history_json": json.dumps(history, ensure_ascii=False),
            "conditions": list(Condition),
            "defects": defects,
            "item_defects": set(item.defect_list()),
            "achievement_toast": _achievement_toast(db, user),
        },
    )


@app.post("/items/{item_id}/condition")
async def update_condition(
    item_id: int,
    request: Request,
    condition: Annotated[str, Form()],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    item = db.query(Item).filter(Item.id == item_id, Item.owner_id == user.id).first()
    if not item:
        raise HTTPException(404)
    form = await request.form()
    defect_flags = [k.replace("defect_", "") for k in form.keys() if k.startswith("defect_")]
    item.condition = condition
    item.defects = ",".join(sorted(defect_flags))
    db.commit()
    save_snapshot(db, item)
    track_event(db, user.id, "condition_update", {"item_id": item.id, "condition": condition})
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@app.post("/items/{item_id}/override")
def set_override(
    item_id: int,
    override_mid: Annotated[str, Form()],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    item = db.query(Item).filter(Item.id == item_id, Item.owner_id == user.id).first()
    if not item:
        raise HTTPException(404)
    raw = override_mid.strip()
    item.override_mid = None if not raw else float(raw.replace(" ", "").replace(",", "."))
    db.commit()
    # Do not log money amounts in analytics
    track_event(
        db,
        user.id,
        "override_set",
        {"item_id": item.id, "has_override": item.override_mid is not None},
    )
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@app.post("/items/{item_id}/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    item = db.query(Item).filter(Item.id == item_id, Item.owner_id == user.id).first()
    if not item:
        raise HTTPException(404)
    from app.models import PriceAlert, ValuationSnapshot

    db.query(PriceAlert).filter(PriceAlert.item_id == item.id).delete()
    db.query(ValuationSnapshot).filter(ValuationSnapshot.item_id == item.id).delete()
    db.delete(item)
    db.commit()
    return RedirectResponse("/portfolio", status_code=303)


# ---------- Achievements ----------


@app.get("/achievements", response_class=HTMLResponse)
def achievements_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    evaluate_achievements(db, user.id)
    progress = achievement_progress(db, user.id)
    toast = _achievement_toast(db, user)
    return templates.TemplateResponse(
        "achievements.html",
        {
            "request": request,
            "user": user,
            "progress": progress,
            "achievement_toast": toast,
        },
    )


# ---------- Alerts & digests ----------


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    from app.models import PriceAlert

    alerts = (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user.id)
        .order_by(PriceAlert.created_at.desc())
        .limit(50)
        .all()
    )
    digests = (
        db.query(WeeklyDigest)
        .filter(WeeklyDigest.user_id == user.id)
        .order_by(WeeklyDigest.created_at.desc())
        .limit(12)
        .all()
    )
    return templates.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "user": user,
            "alerts": alerts,
            "digests": digests,
        },
    )


@app.post("/alerts/read")
def alerts_mark_read(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    mark_alerts_read(db, user.id)
    return RedirectResponse("/alerts", status_code=303)


@app.get("/friend-loop", response_class=HTMLResponse)
def friend_loop_page(
    request: Request,
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        "friend_loop.html",
        {
            "request": request,
            "user": user,
            "friend_loop_steps": FRIEND_LOOP_STEPS,
        },
    )


@app.post("/api/admin/digest")
def api_digest_now(user: Optional[User] = Depends(require_admin)):
    del user
    n = build_weekly_digests()
    return {"digests_created": n}


# ---------- Account / privacy controls ----------


def _account_ctx(
    request: Request,
    db: Session,
    user: User,
    *,
    saved: Optional[str] = None,
    error: Optional[str] = None,
    pro_message: Optional[str] = None,
) -> dict:
    return {
        "request": request,
        "user": user,
        "saved": saved,
        "error": error,
        "pro_message": pro_message,
        "currencies": DISPLAY_CURRENCIES,
        "telegram_ready": telegram_configured(),
        "telegram_bot_username": get_bot_username() if telegram_configured() else None,
        "is_pro": is_pro(user),
        "plan_expires_at": user.plan_expires_at,
        "free_item_limit": FREE_ITEM_LIMIT,
        "pro_item_limit": PRO_ITEM_LIMIT,
        "free_scans_limit": FREE_SCANS_PER_DAY,
        "pro_scans_limit": PRO_SCANS_PER_DAY,
        "scans_used": scans_today(db, user.id),
        "yookassa_ready": yookassa_configured(),
        "pro_price_rub": PRO_PRICE_RUB,
        "pro_price_year_rub": PRO_PRICE_YEAR_RUB,
    }


@app.get("/account", response_class=HTMLResponse)
def account_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    saved: Optional[str] = None,
    pro: Optional[str] = None,
    paid: Optional[str] = None,
):
    msg = pro
    if paid:
        msg = msg or "Если оплата прошла — Pro активируется за минуту. Обнови страницу."
    return templates.TemplateResponse(
        "account.html",
        _account_ctx(request, db, user, saved=saved, pro_message=msg),
    )


@app.post("/account")
def account_save(
    request: Request,
    display_name: Annotated[str, Form()] = "",
    alert_threshold_pct: Annotated[str, Form()] = "5",
    alerts_enabled: Annotated[Optional[str], Form()] = None,
    digest_enabled: Annotated[Optional[str], Form()] = None,
    telegram_alerts_enabled: Annotated[Optional[str], Form()] = None,
    display_currency: Annotated[str, Form()] = "RUB",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    user.display_name = display_name.strip()
    cur = (display_currency or "RUB").upper()
    user.display_currency = cur if cur in DISPLAY_CURRENCIES else "RUB"
    try:
        user.alert_threshold_pct = max(1.0, min(50.0, float(alert_threshold_pct.replace(",", "."))))
    except ValueError:
        user.alert_threshold_pct = 5.0
    user.alerts_enabled = alerts_enabled is not None
    user.digest_enabled = digest_enabled is not None
    if user.telegram_chat_id:
        user.telegram_alerts_enabled = telegram_alerts_enabled is not None
    db.commit()
    return RedirectResponse("/account?saved=1", status_code=303)


@app.post("/account/pro")
def account_pro_redeem(
    request: Request,
    promo_code: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    result = redeem_promo(db, user, promo_code)
    if not result.ok:
        return templates.TemplateResponse(
            "account.html",
            _account_ctx(request, db, user, error=result.message),
            status_code=400,
        )
    from urllib.parse import quote

    return RedirectResponse(
        f"/account?saved=1&pro={quote(result.message)}",
        status_code=303,
    )


@app.post("/account/pro/pay")
def account_pro_pay(
    request: Request,
    period: Annotated[str, Form()] = "month",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    track_event(db, user.id, "pay_cta", {"period": period})
    result = create_pro_checkout(db, user, period=period if period in {"month", "year"} else "month")
    if not result.ok or not result.confirmation_url:
        return templates.TemplateResponse(
            "account.html",
            _account_ctx(request, db, user, error=result.message),
            status_code=400,
        )
    return RedirectResponse(result.confirmation_url, status_code=303)


@app.post("/api/billing/yookassa/webhook")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")
    if not isinstance(payload, dict):
        raise HTTPException(400, "invalid payload")
    return handle_yookassa_webhook(db, payload)


@app.post("/account/telegram/link")
def account_telegram_link(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not telegram_configured():
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")
    username = get_bot_username()
    if not username:
        raise HTTPException(status_code=503, detail="Could not resolve Telegram bot username")
    token = create_link_token(db, user)
    return RedirectResponse(
        f"https://t.me/{username}?start=link_{token}",
        status_code=303,
    )


@app.post("/account/telegram/unlink")
def account_telegram_unlink(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    unlink_telegram(db, user)
    return RedirectResponse("/account?saved=1", status_code=303)


@app.post(TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404, detail="Not configured")
    if TELEGRAM_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if isinstance(update, dict):
        handle_update(db, update)
    return {"ok": True}


def _stack_summary(db: Session, user: User) -> tuple[float, int, list[dict]]:
    items = (
        db.query(Item)
        .options(joinedload(Item.model), joinedload(Item.valuations))
        .filter(Item.owner_id == user.id)
        .all()
    )
    total = 0.0
    lines: list[dict] = []
    for item in items:
        mid = display_mid(item, latest_snapshot(item))
        if mid is None:
            continue
        total += mid
        name = f"{item.model.brand} {item.model.name}" if item.model else f"#{item.id}"
        # Share card: category + model only (no city / email / notes)
        lines.append({"name": name, "mid": mid, "category": item.category})
    lines.sort(key=lambda x: -x["mid"])
    return total, len(lines), lines[:12]


@app.get("/tg", response_class=HTMLResponse)
def telegram_miniapp(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    total = 0.0
    count = 0
    if user:
        user = ensure_plan_fresh(db, user)
        total, count, _ = _stack_summary(db, user)
    return templates.TemplateResponse(
        "tg.html",
        {
            "request": request,
            "user": user,
            "total_mid": total,
            "item_count": count,
            "error": None,
            "public_base": PUBLIC_BASE_URL,
        },
    )


@app.post("/api/telegram/webapp-auth")
async def telegram_webapp_auth(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")
    init_data = str((body or {}).get("init_data") or "")
    if not validate_init_data(init_data):
        raise HTTPException(403, "invalid initData")
    user = user_from_init_data(db, init_data)
    if not user:
        return {"ok": False, "linked": False, "message": "Привяжи Telegram в аккаунте на сайте"}
    resp = JSONResponse({"ok": True, "linked": True, "email": user.email})
    _set_session(resp, user.id)
    return resp


@app.get("/share/stack", response_class=HTMLResponse)
def share_stack(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    total, count, lines = _stack_summary(db, user)
    share_text = (
        f"Мой стак в {PRODUCT_NAME}: {int(total):,} ₽ · {count} вещей\n".replace(",", " ")
        + "\n".join(f"· {l['name']}" for l in lines[:8])
        + (f"\n{PUBLIC_BASE_URL}" if PUBLIC_BASE_URL else "")
    )
    return templates.TemplateResponse(
        "share_stack.html",
        {
            "request": request,
            "user": user,
            "total_mid": total,
            "item_count": count,
            "lines": lines,
            "share_text": share_text,
        },
    )


@app.get("/account/export")
def account_export(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    data = export_user_data(db, user)
    track_event(db, user.id, "data_export", {})
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="things-export.json"',
        },
    )


@app.post("/account/delete")
def account_delete(
    request: Request,
    confirm: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if confirm.strip().upper() != "УДАЛИТЬ":
        return templates.TemplateResponse(
            "account.html",
            _account_ctx(
                request,
                db,
                user,
                error="Чтобы удалить аккаунт, введите слово УДАЛИТЬ",
            ),
            status_code=400,
        )
    delete_user_account(db, user)
    resp = RedirectResponse("/?deleted=1", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------- Photo scan (AI identify → comps) ----------


def _scan_job_payload(job: ScanJob) -> dict:
    try:
        body = json.loads(job.result_json or "{}")
    except json.JSONDecodeError:
        body = {}
    return {
        "id": job.id,
        "status": job.status,
        "category": job.category,
        "brand": job.brand,
        "model_hint": job.model_hint,
        "condition_guess": job.condition_guess,
        "identify_confidence": job.identify_confidence,
        "matched_model_id": job.matched_model_id,
        "match_score": job.match_score,
        "low": job.low,
        "mid": job.mid,
        "high": job.high,
        "comps_count": job.comps_count,
        "valuation_confidence": job.valuation_confidence,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "result": body,
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    payload = {
        "ok": db_ok,
        "db_ok": db_ok,
        "ai_provider_ready": provider_ready(),
        "product": PRODUCT_NAME,
        "telegram_configured": telegram_configured(),
    }
    if not db_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/scan", response_class=HTMLResponse)
def scan_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    used = scans_today(db, user.id)
    limit = scan_limit_for(user)
    recent = (
        db.query(ScanJob)
        .filter(ScanJob.user_id == user.id)
        .order_by(ScanJob.created_at.desc())
        .limit(8)
        .all()
    )
    return templates.TemplateResponse(
        "scan.html",
        {
            "request": request,
            "user": user,
            "scans_used": used,
            "scans_limit": limit,
            "ai_ready": provider_ready(),
            "recent": recent,
            "error": None,
            "result": None,
        },
    )


@app.post("/scan", response_class=HTMLResponse)
async def scan_submit(
    request: Request,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    used = scans_today(db, user.id)
    limit = scan_limit_for(user)
    recent = (
        db.query(ScanJob)
        .filter(ScanJob.user_id == user.id)
        .order_by(ScanJob.created_at.desc())
        .limit(8)
        .all()
    )
    ctx = {
        "request": request,
        "user": user,
        "scans_used": used,
        "scans_limit": limit,
        "ai_ready": provider_ready(),
        "recent": recent,
        "error": None,
        "result": None,
    }
    mime = (photo.content_type or "").lower()
    if not mime.startswith("image/"):
        ctx["error"] = "Нужно фото (JPEG/PNG/WebP)."
        return templates.TemplateResponse("scan.html", ctx, status_code=400)

    raw = await photo.read()
    if not raw:
        ctx["error"] = "Пустой файл."
        return templates.TemplateResponse("scan.html", ctx, status_code=400)
    if len(raw) > MAX_UPLOAD_BYTES:
        ctx["error"] = f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ)."
        return templates.TemplateResponse("scan.html", ctx, status_code=400)

    try:
        job = await run_photo_scan(
            db, user, raw, mime=mime or "image/jpeg", filename=photo.filename or ""
        )
    except PermissionError as exc:
        ctx["error"] = str(exc)
        return templates.TemplateResponse("scan.html", ctx, status_code=429)
    except Exception:
        ctx["error"] = "Не удалось обработать фото. Попробуйте ещё раз."
        return templates.TemplateResponse("scan.html", ctx, status_code=500)

    track_event(
        db,
        user.id,
        "vision_scan",
        {
            "scan_id": job.id,
            "category": job.category,
            "matched": bool(job.matched_model_id),
            "mock": bool((json.loads(job.result_json or "{}").get("billing") or {}).get("mock")),
        },
    )
    ctx["scans_used"] = scans_today(db, user.id)
    ctx["result"] = _scan_job_payload(job)
    ctx["recent"] = (
        db.query(ScanJob)
        .filter(ScanJob.user_id == user.id)
        .order_by(ScanJob.created_at.desc())
        .limit(8)
        .all()
    )
    return templates.TemplateResponse("scan.html", ctx)


@app.post("/api/scan")
async def api_scan(
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ok, reason = can_scan(db, user)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)

    mime = (photo.content_type or "").lower()
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="image required")

    raw = await photo.read()
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="invalid upload size")

    try:
        job = await run_photo_scan(
            db, user, raw, mime=mime or "image/jpeg", filename=photo.filename or ""
        )
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    track_event(db, user.id, "vision_scan_api", {"scan_id": job.id})
    return _scan_job_payload(job)


@app.get("/api/usage")
def api_usage(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return {
        **usage_summary(db, user_id=user.id, days=days),
        "scans_today": scans_today(db, user.id),
        "scans_limit": scan_limit_for(user),
        "plan": user.plan or "free",
        "is_pro": is_pro(user),
        "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
        "ai_provider_ready": provider_ready(),
    }


# ---------- Metrics / API ----------


@app.get("/api/models")
def api_models(
    category: str = Query(...),
    q: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    query = db.query(CanonicalModel).filter(CanonicalModel.category == category)
    if q:
        query = query.filter(CanonicalModel.search_text.like(f"%{q.lower()}%"))
    rows = query.order_by(CanonicalModel.name).limit(30).all()
    return [
        {
            "id": m.id,
            "brand": m.brand,
            "name": m.name,
            "attrs": json.loads(m.attrs_json or "{}"),
        }
        for m in rows
    ]


@app.get("/api/metrics")
def api_metrics(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return compute_metrics(db)


@app.get("/metrics", response_class=HTMLResponse)
def metrics_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        "metrics.html",
        {"request": request, "user": user, "metrics": compute_metrics(db)},
    )


@app.post("/api/admin/revalue")
def api_revalue(user: Optional[User] = Depends(require_admin)):
    del user
    n = revalue_all_items()
    return {"revalued": n}


@app.get("/api/admin/comps/sources")
def api_comps_sources(user: Optional[User] = Depends(require_admin)):
    del user
    return {
        "sources": [
            {"id": s, "label": SOURCE_LABELS.get(s, s), "ingestable": True}
            for s in sorted(INGESTABLE_SOURCES)
        ]
    }


@app.post("/api/admin/comps/ingest")
def api_comps_ingest(
    payload: dict,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(require_admin),
):
    del user
    source = str(payload.get("source") or "manual_json").strip()
    if source not in INGESTABLE_SOURCES:
        raise HTTPException(400, f"source not allowed: {source}")
    rows = payload.get("rows") or []
    if not rows:
        raise HTTPException(400, "rows required")
    result = ingest_comp_aggregates(db, rows, source=source)
    return result.as_dict()


@app.post("/api/admin/comps/refresh")
def api_comps_refresh(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(require_admin),
):
    del user
    return refresh_market_comps(db)
