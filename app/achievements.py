"""
Calm gamification: personal achievements for useful portfolio habits.

No leaderboards, no public scores, no pressure to grind.
Unlocks stay private to the account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Category,
    Item,
    PriceAlert,
    User,
    UserAchievement,
    UserEvent,
    WeeklyDigest,
    utcnow,
)


@dataclass(frozen=True)
class AchievementDef:
    id: str
    title: str
    description: str
    icon: str  # icon key from icons.html
    hint: str  # how to unlock


def _item_count(db: Session, user_id: int) -> int:
    return db.query(func.count(Item.id)).filter(Item.owner_id == user_id).scalar() or 0


def _categories(db: Session, user_id: int) -> set[str]:
    rows = db.query(Item.category).filter(Item.owner_id == user_id).distinct().all()
    return {r[0] for r in rows}


def _has_event(db: Session, user_id: int, event_type: str) -> bool:
    return (
        db.query(UserEvent.id)
        .filter(UserEvent.user_id == user_id, UserEvent.event_type == event_type)
        .first()
        is not None
    )


def _event_days(db: Session, user_id: int, event_type: str, within_days: int = 30) -> int:
    since = utcnow() - timedelta(days=within_days)
    rows = (
        db.query(UserEvent.created_at)
        .filter(
            UserEvent.user_id == user_id,
            UserEvent.event_type == event_type,
            UserEvent.created_at >= since,
        )
        .all()
    )
    return len({r[0].strftime("%Y-%m-%d") for r in rows if r[0]})


def _has_override(db: Session, user_id: int) -> bool:
    return (
        db.query(Item.id)
        .filter(
            Item.owner_id == user_id,
            Item.override_mid_enc != "",
            Item.override_mid_enc.isnot(None),
        )
        .first()
        is not None
    )


def _has_cost_basis(db: Session, user_id: int) -> bool:
    items = db.query(Item).filter(Item.owner_id == user_id).all()
    return any(i.cost_basis is not None for i in items)


ACHIEVEMENTS: list[AchievementDef] = [
    AchievementDef("first_thing", "Первая вещь", "Портфель начался с одной позиции.", "plus", "Добавьте первую вещь"),
    AchievementDef("small_collection", "Малая коллекция", "Три вещи — уже картина имущества.", "portfolio", "Держите 3 вещи в портфеле"),
    AchievementDef("household", "Домашний учёт", "Пять позиций — привычка следить за ценностью.", "portfolio", "Держите 5 вещей в портфеле"),
    AchievementDef("phone_in", "Связь с рынком", "Смартфон в портфеле.", "phone", "Добавьте смартфон"),
    AchievementDef("laptop_in", "Рабочий инструмент", "Ноутбук учтён.", "laptop", "Добавьте ноутбук"),
    AchievementDef("car_in", "На колёсах", "Авто в балансе имущества.", "car", "Добавьте авто"),
    AchievementDef("full_spectrum", "Полный спектр", "Смартфон, ноут и авто — все категории MVP.", "spark", "Добавьте по вещи из каждой категории"),
    AchievementDef("cost_known", "Знаю, за сколько брал", "Указали цену покупки — виден личный P&L.", "chart", "Укажите цену покупки у вещи"),
    AchievementDef("condition_care", "Состояние под контролем", "Обновили бакет состояния — оценка честнее.", "refresh", "Измените состояние вещи"),
    AchievementDef("own_view", "Своя оценка", "Не согласились с рынком и задали override.", "spark", "Поставьте свою оценку на карточке вещи"),
    AchievementDef("week_habit", "Недельная привычка", "Открывали портфель в 3 разных дня за месяц.", "portfolio", "Заглядывайте в портфель несколько дней"),
    AchievementDef("alert_aware", "На пульсе цены", "Получили алерт о движении рынка.", "bell", "Дождитесь сдвига mid или запустите переоценку"),
    AchievementDef("digest_ready", "Недельный итог", "Появился дайджест имущества.", "chart", "Включите дайджест и дождитесь понедельника"),
    AchievementDef("data_steward", "Хозяин данных", "Скачали экспорт — контроль у вас.", "download", "Скачайте экспорт в аккаунте"),
]


ACHIEVEMENT_MAP = {a.id: a for a in ACHIEVEMENTS}


def _checkers() -> dict[str, Callable[[Session, int], bool]]:
    return {
        "first_thing": lambda db, uid: _item_count(db, uid) >= 1,
        "small_collection": lambda db, uid: _item_count(db, uid) >= 3,
        "household": lambda db, uid: _item_count(db, uid) >= 5,
        "phone_in": lambda db, uid: Category.SMARTPHONE.value in _categories(db, uid),
        "laptop_in": lambda db, uid: Category.LAPTOP.value in _categories(db, uid),
        "car_in": lambda db, uid: Category.CAR.value in _categories(db, uid),
        "full_spectrum": lambda db, uid: {
            Category.SMARTPHONE.value,
            Category.LAPTOP.value,
            Category.CAR.value,
        }.issubset(_categories(db, uid)),
        "cost_known": _has_cost_basis,
        "condition_care": lambda db, uid: _has_event(db, uid, "condition_update"),
        "own_view": _has_override,
        "week_habit": lambda db, uid: _event_days(db, uid, "portfolio_view", 30) >= 3,
        "alert_aware": lambda db, uid: (
            db.query(PriceAlert.id).filter(PriceAlert.user_id == uid).first() is not None
        ),
        "digest_ready": lambda db, uid: (
            db.query(WeeklyDigest.id).filter(WeeklyDigest.user_id == uid).first() is not None
        ),
        "data_steward": lambda db, uid: _has_event(db, uid, "data_export"),
    }


def unlocked_ids(db: Session, user_id: int) -> set[str]:
    rows = db.query(UserAchievement.achievement_id).filter(
        UserAchievement.user_id == user_id
    ).all()
    return {r[0] for r in rows}


def evaluate_achievements(db: Session, user_id: int) -> list[AchievementDef]:
    """Unlock any newly earned achievements. Returns only fresh unlocks."""
    have = unlocked_ids(db, user_id)
    checkers = _checkers()
    fresh: list[AchievementDef] = []
    for ach in ACHIEVEMENTS:
        if ach.id in have:
            continue
        check = checkers.get(ach.id)
        if not check:
            continue
        try:
            ok = check(db, user_id)
        except Exception:
            ok = False
        if ok:
            db.add(
                UserAchievement(
                    user_id=user_id,
                    achievement_id=ach.id,
                    seen=False,
                )
            )
            fresh.append(ach)
    if fresh:
        db.commit()
    return fresh


def unseen_achievements(db: Session, user_id: int) -> list[AchievementDef]:
    rows = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user_id, UserAchievement.seen.is_(False))
        .order_by(UserAchievement.unlocked_at.desc())
        .all()
    )
    return [ACHIEVEMENT_MAP[r.achievement_id] for r in rows if r.achievement_id in ACHIEVEMENT_MAP]


def mark_achievements_seen(db: Session, user_id: int) -> None:
    db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id,
        UserAchievement.seen.is_(False),
    ).update({"seen": True}, synchronize_session=False)
    db.commit()


def achievement_progress(db: Session, user_id: int) -> dict:
    have = unlocked_ids(db, user_id)
    items = []
    for ach in ACHIEVEMENTS:
        items.append(
            {
                "id": ach.id,
                "title": ach.title,
                "description": ach.description,
                "icon": ach.icon,
                "hint": ach.hint,
                "unlocked": ach.id in have,
            }
        )
    return {
        "unlocked_count": len(have),
        "total": len(ACHIEVEMENTS),
        "list": items,
    }


def seed_demo_achievements(db: Session, user: User) -> None:
    """Evaluate once for demo so the page isn't empty."""
    evaluate_achievements(db, user.id)
