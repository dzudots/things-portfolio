from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import DATABASE_URL
from app.crypto import decrypt_float, decrypt_text, encrypt_float, encrypt_text


class Base(DeclarativeBase):
    pass


class Category(str, Enum):
    SMARTPHONE = "smartphone"
    LAPTOP = "laptop"
    CAR = "car"


class Condition(str, Enum):
    MINT = "mint"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    PARTS = "parts"


ELECTRONICS_DEFECTS = [
    "cracked_screen",
    "non_original_battery",
    "icloud_lock",
    "after_repair",
    "water_damage",
]

CAR_DEFECTS = [
    "accident",
    "repainted",
    "multiple_owners",
]

CONDITION_LABELS = {
    Condition.MINT.value: "Как новый",
    Condition.GOOD.value: "Б/У без дефектов",
    Condition.FAIR.value: "Заметный износ",
    Condition.POOR.value: "Сильные дефекты",
    Condition.PARTS.value: "На запчасти",
}

DEFECT_LABELS = {
    "cracked_screen": "Разбит экран",
    "non_original_battery": "Неоригинальная АКБ",
    "icloud_lock": "iCloud lock",
    "after_repair": "После ремонта",
    "water_damage": "Затопление",
    "accident": "ДТП",
    "repainted": "Окрасы",
    "multiple_owners": "Несколько владельцев",
}

CATEGORY_LABELS = {
    Category.SMARTPHONE.value: "Смартфон",
    Category.LAPTOP.value: "Ноутбук",
    Category.CAR.value: "Авто",
}

CONFIDENCE_LABELS = {
    "low": "низкая",
    "medium": "средняя",
    "high": "высокая",
}

CONDITION_HINTS = {
    Condition.MINT.value: "Как с витрины, почти без следов использования",
    Condition.GOOD.value: "Б/У, экран и корпус без серьёзных дефектов",
    Condition.FAIR.value: "Заметные царапины, потёртости, следы носки",
    Condition.POOR.value: "Сильный износ или явные повреждения",
    Condition.PARTS.value: "Не включается / на запчасти",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Encrypted at rest — personal label only
    display_name_enc: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Privacy / product preferences
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_threshold_pct: Mapped[float] = mapped_column(Float, default=5.0)
    # free | pro — for scan limits / future billing
    plan: Mapped[str] = mapped_column(String(16), default="free")
    # RUB | KZT | BYN | UAH | USD — display only; storage in RUB
    display_currency: Mapped[str] = mapped_column(String(8), default="RUB")
    privacy_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Telegram (optional alert push; linked via one-time deep-link token)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_link_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    telegram_link_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    items: Mapped[list["Item"]] = relationship(back_populates="owner")
    events: Mapped[list["UserEvent"]] = relationship(back_populates="user")
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="user")
    digests: Mapped[list["WeeklyDigest"]] = relationship(back_populates="user")
    achievements: Mapped[list["UserAchievement"]] = relationship(back_populates="user")
    api_usage: Mapped[list["ApiUsage"]] = relationship(back_populates="user")
    scans: Mapped[list["ScanJob"]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return decrypt_text(self.display_name_enc) or self.email.split("@")[0]

    @display_name.setter
    def display_name(self, value: str) -> None:
        self.display_name_enc = encrypt_text(value or "")


class CanonicalModel(Base):
    __tablename__ = "canonical_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    brand: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    attrs_json: Mapped[str] = mapped_column(Text, default="{}")
    search_text: Mapped[str] = mapped_column(String(400), index=True)

    items: Mapped[list["Item"]] = relationship(back_populates="model")
    comps: Mapped[list["CompListing"]] = relationship(back_populates="model")


class Item(Base):
    """
    Private portfolio position. Sensitive money/notes fields are encrypted at rest.
    We intentionally do NOT store VIN, serial, INN, passport, or tax IDs.
    """

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    canonical_model_id: Mapped[int] = mapped_column(ForeignKey("canonical_models.id"))
    condition: Mapped[str] = mapped_column(String(16), default=Condition.GOOD.value)
    defects: Mapped[str] = mapped_column(String(400), default="")

    # Encrypted private fields
    cost_basis_enc: Mapped[str] = mapped_column(Text, default="")
    override_mid_enc: Mapped[str] = mapped_column(Text, default="")
    notes_enc: Mapped[str] = mapped_column(Text, default="")

    # Coarse location for comps geo — city/region only, not street address
    location_city: Mapped[str] = mapped_column(String(80), default="Москва")
    location_region: Mapped[str] = mapped_column(String(80), default="Москва")
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="items")
    model: Mapped[CanonicalModel] = relationship(back_populates="items")
    valuations: Mapped[list["ValuationSnapshot"]] = relationship(
        back_populates="item", order_by="ValuationSnapshot.ts"
    )

    def defect_list(self) -> list[str]:
        if not self.defects:
            return []
        return [d for d in self.defects.split(",") if d]

    @property
    def cost_basis(self) -> Optional[float]:
        return decrypt_float(self.cost_basis_enc)

    @cost_basis.setter
    def cost_basis(self, value: Optional[float]) -> None:
        self.cost_basis_enc = encrypt_float(value)

    @property
    def override_mid(self) -> Optional[float]:
        return decrypt_float(self.override_mid_enc)

    @override_mid.setter
    def override_mid(self, value: Optional[float]) -> None:
        self.override_mid_enc = encrypt_float(value)

    @property
    def notes(self) -> str:
        return decrypt_text(self.notes_enc)

    @notes.setter
    def notes(self, value: str) -> None:
        self.notes_enc = encrypt_text(value or "")


class CompListing(Base):
    """Global market aggregates — not linked to any user identity."""

    __tablename__ = "comp_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("canonical_models.id"), index=True)
    condition_bucket: Mapped[str] = mapped_column(String(16), index=True)
    defects: Mapped[str] = mapped_column(String(400), default="")
    price: Mapped[float] = mapped_column(Float)
    region: Mapped[str] = mapped_column(String(80), default="Москва")
    city: Mapped[str] = mapped_column(String(80), default="Москва")
    source: Mapped[str] = mapped_column(String(40), default="seed")
    external_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    model: Mapped[CanonicalModel] = relationship(back_populates="comps")


class ValuationSnapshot(Base):
    """Market estimate history for an item. Access only via owner session."""

    __tablename__ = "valuation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    low: Mapped[float] = mapped_column(Float)
    mid: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(16))
    comps_count: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(40), default="comps_percentile")
    geo_level: Mapped[str] = mapped_column(String(20), default="city")
    insufficient_data: Mapped[bool] = mapped_column(Boolean, default=False)

    item: Mapped[Item] = relationship(back_populates="valuations")


class PriceAlert(Base):
    """In-app alert when market mid moves beyond user threshold."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # up / down
    change_pct: Mapped[float] = mapped_column(Float)
    old_mid: Mapped[float] = mapped_column(Float)
    new_mid: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(400), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="alerts")


class WeeklyDigest(Base):
    """Stored weekly portfolio summary (in-app; email later)."""

    __tablename__ = "weekly_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    total_mid: Mapped[float] = mapped_column(Float, default=0)
    delta_week: Mapped[float] = mapped_column(Float, default=0)
    body_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="digests")


class UserEvent(Base):
    """Minimal product analytics — no portfolio money amounts in meta by default."""

    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="events")


class UserAchievement(Base):
    """Private unlocks — no leaderboard, no public score."""

    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    achievement_id: Mapped[str] = mapped_column(String(40), index=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="achievements")


class ApiUsage(Base):
    """Ledger of AI/API calls: provider cost + product markup (10–30%)."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(40), index=True)  # vision_scan
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    provider_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    markup_pct: Mapped[float] = mapped_column(Float, default=20.0)
    billed_usd: Mapped[float] = mapped_column(Float, default=0.0)
    billed_rub: Mapped[float] = mapped_column(Float, default=0.0)
    mock: Mapped[bool] = mapped_column(Boolean, default=False)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[Optional[User]] = relationship(back_populates="api_usage")


class ScanJob(Base):
    """Photo → identify → comps result (private to user)."""

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="done")  # done | failed
    category: Mapped[str] = mapped_column(String(32), default="unknown")
    brand: Mapped[str] = mapped_column(String(80), default="")
    model_hint: Mapped[str] = mapped_column(String(200), default="")
    condition_guess: Mapped[str] = mapped_column(String(16), default="good")
    identify_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    matched_model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("canonical_models.id"), nullable=True
    )
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comps_count: Mapped[int] = mapped_column(Integer, default=0)
    valuation_confidence: Mapped[str] = mapped_column(String(16), default="low")
    usage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_usage.id"), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="scans")


_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _sqlite_fk(dbapi_conn, _):
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _migrate_sqlite() -> None:
    """Additive SQLite patches for existing local DBs (create_all won't ALTER)."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        if cols and "plan" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN plan VARCHAR(16) DEFAULT 'free'"
            )
        if cols and "display_currency" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN display_currency VARCHAR(8) DEFAULT 'RUB'"
            )
        _telegram_cols = {
            "telegram_chat_id": "VARCHAR(32)",
            "telegram_username": "VARCHAR(64)",
            "telegram_alerts_enabled": "BOOLEAN DEFAULT 0",
            "telegram_link_token": "VARCHAR(64)",
            "telegram_link_expires_at": "DATETIME",
        }
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        for name, ddl in _telegram_cols.items():
            if cols and name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


def _migrate_postgres() -> None:
    """Additive Postgres patches (create_all won't ALTER)."""
    if not str(engine.url).startswith("postgresql"):
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(16) DEFAULT 'free'"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_currency VARCHAR(8) DEFAULT 'RUB'"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(32)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(64)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_alerts_enabled BOOLEAN DEFAULT FALSE"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_link_token VARCHAR(64)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_link_expires_at TIMESTAMPTZ"
        )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    _migrate_postgres()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
