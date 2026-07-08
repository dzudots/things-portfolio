"""Phase A: seed canonical models + whitelist comps (demo price indices)."""

from __future__ import annotations

import json
import random
from datetime import timedelta

from app.auth import create_user
from app.models import (
    CanonicalModel,
    Category,
    CompListing,
    Condition,
    SessionLocal,
    User,
    init_db,
    utcnow,
)
from app.valuation import save_snapshot
from app.models import Item


def _phone(brand: str, name: str, year: int, storage: str, good: int, **extra) -> dict:
    """CIS secondary-market mid anchors (good) → other buckets."""
    return {
        "category": Category.SMARTPHONE.value,
        "brand": brand,
        "name": name,
        "attrs": {"storage": storage, "year": year, **extra},
        "base_prices": {
            "mint": round(good * 1.15 / 100) * 100,
            "good": good,
            "fair": round(good * 0.82 / 100) * 100,
            "poor": round(good * 0.58 / 100) * 100,
            "parts": round(good * 0.32 / 100) * 100,
        },
    }


def _laptop(brand: str, name: str, year: int, good: int, **attrs) -> dict:
    return {
        "category": Category.LAPTOP.value,
        "brand": brand,
        "name": name,
        "attrs": {"year": year, **attrs},
        "base_prices": {
            "mint": round(good * 1.12 / 100) * 100,
            "good": good,
            "fair": round(good * 0.84 / 100) * 100,
            "poor": round(good * 0.60 / 100) * 100,
            "parts": round(good * 0.34 / 100) * 100,
        },
    }


def _car(brand: str, name: str, year: int, good: int, **attrs) -> dict:
    return {
        "category": Category.CAR.value,
        "brand": brand,
        "name": name,
        "attrs": {"year": year, **attrs},
        "base_prices": {
            "mint": round(good * 1.10 / 1000) * 1000,
            "good": good,
            "fair": round(good * 0.88 / 1000) * 1000,
            "poor": round(good * 0.72 / 1000) * 1000,
            "parts": round(good * 0.40 / 1000) * 1000,
        },
    }


# Major phone models for CIS Gen Z (seed comps). Prices ≈ secondary mid (RUB).
MODELS = [
    # Apple iPhone 12–16 (+ SE)
    _phone("Apple", "iPhone 16 Pro Max 256GB", 2024, "256GB", 118000),
    _phone("Apple", "iPhone 16 Pro 256GB", 2024, "256GB", 105000),
    _phone("Apple", "iPhone 16 Plus 128GB", 2024, "128GB", 88000),
    _phone("Apple", "iPhone 16 128GB", 2024, "128GB", 78000),
    _phone("Apple", "iPhone 15 Pro Max 256GB", 2023, "256GB", 92000),
    _phone("Apple", "iPhone 15 Pro 256GB", 2023, "256GB", 85000),
    _phone("Apple", "iPhone 15 Plus 128GB", 2023, "128GB", 68000),
    _phone("Apple", "iPhone 15 128GB", 2023, "128GB", 62000),
    _phone("Apple", "iPhone 14 Pro Max 256GB", 2022, "256GB", 72000),
    _phone("Apple", "iPhone 14 Pro 256GB", 2022, "256GB", 62000),
    _phone("Apple", "iPhone 14 Plus 128GB", 2022, "128GB", 52000),
    _phone("Apple", "iPhone 14 128GB", 2022, "128GB", 48000),
    _phone("Apple", "iPhone 13 Pro Max 256GB", 2021, "256GB", 58000),
    _phone("Apple", "iPhone 13 Pro 256GB", 2021, "256GB", 52000),
    _phone("Apple", "iPhone 13 128GB", 2021, "128GB", 42000),
    _phone("Apple", "iPhone 13 mini 128GB", 2021, "128GB", 36000),
    _phone("Apple", "iPhone 12 Pro Max 256GB", 2020, "256GB", 42000),
    _phone("Apple", "iPhone 12 Pro 128GB", 2020, "128GB", 36000),
    _phone("Apple", "iPhone 12 128GB", 2020, "128GB", 32000),
    _phone("Apple", "iPhone 12 mini 64GB", 2020, "64GB", 26000),
    _phone("Apple", "iPhone SE 2022 64GB", 2022, "64GB", 28000),
    # Samsung Galaxy S / A / Z
    _phone("Samsung", "Galaxy S24 Ultra 256GB", 2024, "256GB", 78000),
    _phone("Samsung", "Galaxy S24+ 256GB", 2024, "256GB", 62000),
    _phone("Samsung", "Galaxy S24 256GB", 2024, "256GB", 52000),
    _phone("Samsung", "Galaxy S23 Ultra 256GB", 2023, "256GB", 58000),
    _phone("Samsung", "Galaxy S23+ 256GB", 2023, "256GB", 48000),
    _phone("Samsung", "Galaxy S23 256GB", 2023, "256GB", 42000),
    _phone("Samsung", "Galaxy S22 Ultra 256GB", 2022, "256GB", 42000),
    _phone("Samsung", "Galaxy S22 128GB", 2022, "128GB", 32000),
    _phone("Samsung", "Galaxy A55 256GB", 2024, "256GB", 28000),
    _phone("Samsung", "Galaxy A54 256GB", 2023, "256GB", 24000),
    _phone("Samsung", "Galaxy A35 128GB", 2024, "128GB", 20000),
    _phone("Samsung", "Galaxy A25 128GB", 2024, "128GB", 16000),
    _phone("Samsung", "Galaxy A15 128GB", 2024, "128GB", 12000),
    _phone("Samsung", "Galaxy Z Flip5 256GB", 2023, "256GB", 48000),
    _phone("Samsung", "Galaxy Z Fold5 256GB", 2023, "256GB", 78000),
    # Xiaomi / Redmi / Poco
    _phone("Xiaomi", "Xiaomi 14 Ultra 512GB", 2024, "512GB", 72000),
    _phone("Xiaomi", "Xiaomi 14 256GB", 2024, "256GB", 42000),
    _phone("Xiaomi", "Xiaomi 13T Pro 256GB", 2023, "256GB", 36000),
    _phone("Xiaomi", "Xiaomi 13 256GB", 2023, "256GB", 32000),
    _phone("Xiaomi", "Redmi Note 13 Pro+ 256GB", 2024, "256GB", 28000),
    _phone("Xiaomi", "Redmi Note 13 Pro 256GB", 2024, "256GB", 22000),
    _phone("Xiaomi", "Redmi Note 12 Pro 256GB", 2023, "256GB", 18000),
    _phone("Xiaomi", "Poco X6 Pro 256GB", 2024, "256GB", 24000),
    _phone("Xiaomi", "Poco F6 256GB", 2024, "256GB", 32000),
    _phone("Xiaomi", "Poco M6 Pro 256GB", 2024, "256GB", 16000),
    # Google Pixel
    _phone("Google", "Pixel 9 Pro 128GB", 2024, "128GB", 72000),
    _phone("Google", "Pixel 9 128GB", 2024, "128GB", 58000),
    _phone("Google", "Pixel 8 Pro 128GB", 2023, "128GB", 52000),
    _phone("Google", "Pixel 8 128GB", 2023, "128GB", 40000),
    _phone("Google", "Pixel 8a 128GB", 2024, "128GB", 32000),
    _phone("Google", "Pixel 7a 128GB", 2023, "128GB", 26000),
    # Nothing / OnePlus / Realme / Honor / Huawei
    _phone("Nothing", "Nothing Phone (2a) 256GB", 2024, "256GB", 28000),
    _phone("Nothing", "Nothing Phone (2) 256GB", 2023, "256GB", 38000),
    _phone("OnePlus", "OnePlus 12 256GB", 2024, "256GB", 48000),
    _phone("OnePlus", "OnePlus Nord 3 256GB", 2023, "256GB", 28000),
    _phone("Realme", "Realme GT 5 256GB", 2023, "256GB", 30000),
    _phone("Realme", "Realme 12 Pro+ 256GB", 2024, "256GB", 26000),
    _phone("Honor", "Honor 200 256GB", 2024, "256GB", 28000),
    _phone("Honor", "Honor Magic6 Lite 256GB", 2024, "256GB", 22000),
    _phone("Huawei", "Huawei Pura 70 256GB", 2024, "256GB", 52000),
    _phone("Huawei", "Huawei Nova 12 256GB", 2024, "256GB", 28000),
    # Laptops
    _laptop("Apple", "MacBook Air M3 8/256", 2024, 98000, cpu="M3", ram="8GB", storage="256GB"),
    _laptop("Apple", "MacBook Air M2 8/256", 2022, 82000, cpu="M2", ram="8GB", storage="256GB"),
    _laptop("Apple", "MacBook Pro 14 M3 16/512", 2023, 148000, cpu="M3", ram="16GB", storage="512GB"),
    _laptop("Apple", "MacBook Pro 14 M2 16/512", 2023, 128000, cpu="M2", ram="16GB", storage="512GB"),
    _laptop("ASUS", "ASUS Zenbook 14 OLED i7/16/512", 2023, 68000, cpu="i7", ram="16GB", storage="512GB"),
    _laptop("ASUS", "ASUS ROG Zephyrus G14 2023", 2023, 98000, cpu="Ryzen9", ram="16GB", storage="512GB"),
    _laptop("Lenovo", "Lenovo ThinkPad X1 Carbon Gen 10", 2022, 75000, cpu="i7", ram="16GB", storage="512GB"),
    _laptop("Lenovo", "Lenovo Yoga Slim 7 14", 2023, 62000, cpu="Ryzen7", ram="16GB", storage="512GB"),
    _laptop("Huawei", "Huawei MateBook D16 i5/16/512", 2023, 52000, cpu="i5", ram="16GB", storage="512GB"),
    _laptop("Xiaomi", "Xiaomi RedmiBook 15 i5/16/512", 2023, 42000, cpu="i5", ram="16GB", storage="512GB"),
    # Cars (popular CIS)
    _car("Toyota", "Toyota Camry 2.5 2019", 2019, 2200000, engine="2.5", mileage_bucket="80-120k"),
    _car("Hyundai", "Hyundai Solaris 1.6 2020", 2020, 1200000, engine="1.6", mileage_bucket="40-80k"),
    _car("Kia", "Kia Rio 1.6 2021", 2021, 1280000, engine="1.6", mileage_bucket="20-60k"),
    _car("Volkswagen", "Volkswagen Polo 1.6 2018", 2018, 980000, engine="1.6", mileage_bucket="80-120k"),
    _car("Lada", "Lada Vesta 1.6 2021", 2021, 980000, engine="1.6", mileage_bucket="40-80k"),
    _car("Geely", "Geely Coolray 1.5 2022", 2022, 1650000, engine="1.5", mileage_bucket="20-60k"),
    _car("Haval", "Haval Jolion 1.5 2022", 2022, 1750000, engine="1.5", mileage_bucket="20-60k"),
    _car("Chery", "Chery Tiggo 7 Pro 1.5 2022", 2022, 1850000, engine="1.5", mileage_bucket="20-60k"),
]

CITIES = [
    ("Москва", "Москва"),
    ("Санкт-Петербург", "Санкт-Петербург"),
    ("Казань", "Татарстан"),
    ("Екатеринбург", "Свердловская область"),
    ("Новосибирск", "Новосибирская область"),
    ("Краснодар", "Краснодарский край"),
    ("Ростов-на-Дону", "Ростовская область"),
    ("Минск", "Минск"),
    ("Алматы", "Алматы"),
    ("Астана", "Астана"),
    ("Ташкент", "Ташкент"),
    ("Тбилиси", "Тбилиси"),
    ("Ереван", "Ереван"),
    ("Баку", "Баку"),
    ("Киев", "Киев"),
    ("Бишкек", "Бишкек"),
]


def _search_text(brand: str, name: str) -> str:
    """Aliases help match_canonical (Galaxy↔Samsung, Redmi/Poco↔Xiaomi, etc.)."""
    base = f"{brand} {name}".lower()
    aliases: list[str] = []
    b = brand.lower()
    n = name.lower()
    if b == "samsung" or "galaxy" in n:
        aliases += ["samsung", "galaxy", "самсунг"]
    if b == "apple" or "iphone" in n or "macbook" in n:
        aliases += ["apple", "iphone", "айфон", "macbook", "макбук"]
    if b == "xiaomi" or "redmi" in n or "poco" in n:
        aliases += ["xiaomi", "redmi", "poco", "сяоми"]
    if b == "google" or "pixel" in n:
        aliases += ["google", "pixel", "гугл"]
    if "nothing" in b or "nothing" in n:
        aliases += ["nothing phone"]
    # storage / generation tokens already in name
    return " ".join([base] + aliases)


def seed_models_and_comps(db, rng: random.Random) -> list[CanonicalModel]:
    models: list[CanonicalModel] = []
    now = utcnow()

    for spec in MODELS:
        m = CanonicalModel(
            category=spec["category"],
            brand=spec["brand"],
            name=spec["name"],
            attrs_json=json.dumps(spec["attrs"], ensure_ascii=False),
            search_text=_search_text(spec["brand"], spec["name"]),
        )
        db.add(m)
        db.flush()
        models.append(m)

        for condition, base in spec["base_prices"].items():
            # Whitelist: enough comps per condition for confidence
            n = 14 if condition in ("good", "fair") else 8
            for i in range(n):
                city, region = CITIES[i % len(CITIES)]
                # Regional noise + time scatter within 30 days
                noise = rng.uniform(0.88, 1.12)
                price = round(base * noise / 100) * 100
                observed = now - timedelta(days=rng.randint(0, 28), hours=rng.randint(0, 23))
                db.add(
                    CompListing(
                        model_id=m.id,
                        condition_bucket=condition,
                        defects="",
                        price=price,
                        region=region,
                        city=city,
                        source="seed",
                        external_ref=f"seed:{m.id}:{condition}:{i}",
                        observed_at=observed,
                    )
                )

            # A few cracked-screen comps for phones
            if spec["category"] == Category.SMARTPHONE.value and condition == "poor":
                for i in range(6):
                    city, region = CITIES[i % len(CITIES)]
                    price = round(base * 0.75 * rng.uniform(0.9, 1.1) / 100) * 100
                    db.add(
                        CompListing(
                            model_id=m.id,
                            condition_bucket=condition,
                            defects="cracked_screen",
                            price=price,
                            region=region,
                            city=city,
                            source="seed",
                            external_ref=f"seed:{m.id}:crack:{i}",
                            observed_at=now - timedelta(days=rng.randint(0, 20)),
                        )
                    )

    db.commit()
    return models


def seed_demo_user(db, models: list[CanonicalModel]) -> User:
    existing = db.query(User).filter(User.email == "demo@things.local").first()
    if existing:
        return existing

    user = create_user(db, "demo@things.local", "demo1234", "Демо")
    by_name = {m.name: m for m in models}

    def pick(name: str) -> CanonicalModel:
        if name in by_name:
            return by_name[name]
        # fallback: first smartphone / laptop / car
        for m in models:
            if name.startswith("iPhone") and m.category == Category.SMARTPHONE.value:
                return m
            if name.startswith("MacBook") and m.category == Category.LAPTOP.value:
                return m
            if name.startswith("Toyota") and m.category == Category.CAR.value:
                return m
        return models[0]

    picks = [
        (pick("iPhone 15 Pro 256GB"), Condition.GOOD.value, "", 90000, "Москва"),
        (pick("MacBook Air M2 8/256"), Condition.GOOD.value, "", 90000, "Москва"),
        (pick("Toyota Camry 2.5 2019"), Condition.FAIR.value, "", 2100000, "Казань"),
    ]
    for model, cond, defects, cost, city in picks:
        region = next((r for c, r in CITIES if c == city), city)
        item = Item(
            owner_id=user.id,
            category=model.category,
            canonical_model_id=model.id,
            condition=cond,
            defects=defects,
            location_city=city,
            location_region=region,
        )
        item.cost_basis = cost
        item.notes = ""
        db.add(item)
        db.flush()
        # Historical snapshots for chart (simulate 14 days)
        from app.valuation import compute_valuation
        from app.models import ValuationSnapshot

        base = compute_valuation(db, item)
        for day in range(14, 0, -1):
            drift = 1 + (day - 7) * 0.004
            db.add(
                ValuationSnapshot(
                    item_id=item.id,
                    ts=utcnow() - timedelta(days=day),
                    low=round(base.low * drift),
                    mid=round(base.mid * drift),
                    high=round(base.high * drift),
                    confidence=base.confidence,
                    comps_count=base.comps_count,
                    method=base.method,
                    geo_level=base.geo_level,
                    insufficient_data=base.insufficient_data,
                )
            )
        save_snapshot(db, item, base)

    db.commit()
    from app.achievements import evaluate_achievements
    from app.metrics import track_event

    track_event(db, user.id, "portfolio_view")
    evaluate_achievements(db, user.id)
    return user


def ensure_catalog(db) -> int:
    """Add missing canonical models + comps without wiping existing data (prod-safe)."""
    # Refresh search aliases for existing rows
    for m in db.query(CanonicalModel).all():
        desired = _search_text(m.brand, m.name)
        if (m.search_text or "") != desired:
            m.search_text = desired
    existing = {(m.brand, m.name) for m in db.query(CanonicalModel).all()}
    missing = [s for s in MODELS if (s["brand"], s["name"]) not in existing]
    if not missing:
        db.commit()
        return 0
    rng = random.Random(42 + len(existing))
    now = utcnow()
    added = 0
    for spec in missing:
        m = CanonicalModel(
            category=spec["category"],
            brand=spec["brand"],
            name=spec["name"],
            attrs_json=json.dumps(spec["attrs"], ensure_ascii=False),
            search_text=_search_text(spec["brand"], spec["name"]),
        )
        db.add(m)
        db.flush()
        for condition, base in spec["base_prices"].items():
            n = 14 if condition in ("good", "fair") else 8
            for i in range(n):
                city, region = CITIES[i % len(CITIES)]
                noise = rng.uniform(0.88, 1.12)
                from app.regions import price_index_for

                regional = price_index_for(city, region)
                price = round(base * noise * regional / 100) * 100
                observed = now - timedelta(days=rng.randint(0, 28), hours=rng.randint(0, 23))
                db.add(
                    CompListing(
                        model_id=m.id,
                        condition_bucket=condition,
                        defects="",
                        price=price,
                        region=region,
                        city=city,
                        source="seed",
                        external_ref=f"seed:{m.id}:{condition}:{i}",
                        observed_at=observed,
                    )
                )
        added += 1
    db.commit()
    return added


def run_seed(reset: bool = True) -> None:
    init_db()
    db = SessionLocal()
    try:
        if reset:
            # Clear in FK order
            from app.models import (
                ApiUsage,
                Payment,
                PriceAlert,
                ScanJob,
                UserAchievement,
                UserEvent,
                ValuationSnapshot,
                WeeklyDigest,
            )

            db.query(PriceAlert).delete()
            db.query(WeeklyDigest).delete()
            db.query(UserAchievement).delete()
            db.query(UserEvent).delete()
            db.query(Payment).delete()
            db.query(ScanJob).delete()
            db.query(ApiUsage).delete()
            db.query(ValuationSnapshot).delete()
            db.query(Item).delete()
            db.query(CompListing).delete()
            db.query(CanonicalModel).delete()
            db.query(User).delete()
            db.commit()

        if db.query(CanonicalModel).count() == 0:
            rng = random.Random(42)
            models = seed_models_and_comps(db, rng)
            seed_demo_user(db, models)
            print(f"Seeded {len(models)} models, comps, and demo user demo@things.local / demo1234")
        else:
            n = ensure_catalog(db)
            print(f"Catalog up to date (+{n} models)." if n else "Database already has models; skip seed (pass reset).")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed(reset=True)
