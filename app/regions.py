"""CIS cities: geo for comps + regional price index vs Moscow baseline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityInfo:
    city: str
    region: str
    country: str
    currency: str
    price_index: float  # 1.0 = Moscow-like secondary market


# Popular CIS cities for Gen Z audience
CIS_CITIES: list[CityInfo] = [
    CityInfo("Москва", "Москва", "RU", "RUB", 1.00),
    CityInfo("Санкт-Петербург", "Санкт-Петербург", "RU", "RUB", 0.98),
    CityInfo("Казань", "Татарстан", "RU", "RUB", 0.93),
    CityInfo("Екатеринбург", "Свердловская область", "RU", "RUB", 0.94),
    CityInfo("Новосибирск", "Новосибирская область", "RU", "RUB", 0.91),
    CityInfo("Краснодар", "Краснодарский край", "RU", "RUB", 0.95),
    CityInfo("Ростов-на-Дону", "Ростовская область", "RU", "RUB", 0.92),
    CityInfo("Минск", "Минск", "BY", "BYN", 0.88),
    CityInfo("Гомель", "Гомельская область", "BY", "BYN", 0.84),
    CityInfo("Алматы", "Алматы", "KZ", "KZT", 0.96),
    CityInfo("Астана", "Астана", "KZ", "KZT", 0.95),
    CityInfo("Шымкент", "Шымкент", "KZ", "KZT", 0.90),
    CityInfo("Ташкент", "Ташкент", "UZ", "USD", 0.90),
    CityInfo("Бишкек", "Бишкек", "KG", "USD", 0.87),
    CityInfo("Тбилиси", "Тбилиси", "GE", "USD", 0.92),
    CityInfo("Ереван", "Ереван", "AM", "USD", 0.89),
    CityInfo("Баку", "Баку", "AZ", "USD", 0.94),
    CityInfo("Киев", "Киев", "UA", "UAH", 0.85),
    CityInfo("Харьков", "Харьков", "UA", "UAH", 0.82),
    CityInfo("Одесса", "Одесская область", "UA", "UAH", 0.83),
]

_CITY_MAP = {c.city: c for c in CIS_CITIES}


def city_info(city: str) -> CityInfo | None:
    return _CITY_MAP.get((city or "").strip())


def price_index_for(city: str, region: str = "") -> float:
    info = city_info(city)
    if info:
        return info.price_index
    # Rough regional fallback inside Russia
    r = (region or "").lower()
    if "моск" in r:
        return 1.0
    if "петербург" in r or "ленинград" in r:
        return 0.98
    if "татар" in r:
        return 0.93
    return 0.92


def default_currency_for_city(city: str) -> str:
    info = city_info(city)
    return info.currency if info else "RUB"


def city_choices() -> list[dict]:
    return [
        {
            "city": c.city,
            "region": c.region,
            "country": c.country,
            "currency": c.currency,
            "price_index": c.price_index,
        }
        for c in CIS_CITIES
    ]
