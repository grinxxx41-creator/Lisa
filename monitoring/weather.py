"""Погода для островка: сервис Open-Meteo (без ключа и регистрации), только стандартная библиотека.

Запросы уходят в интернет, поэтому делаются лишь когда пользователь сам указал город в настройках
островка. Передаётся только название города (поиск координат) и сами координаты.
Функции здесь блокирующие — вызывать из фонового потока.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 8.0

# код погоды ВМО → (описание, значок: sun | partly | cloud | fog | rain | snow | storm)
_CODES = {
    0: ("Ясно", "sun"), 1: ("Малооблачно", "partly"), 2: ("Переменная облачность", "partly"),
    3: ("Пасмурно", "cloud"), 45: ("Туман", "fog"), 48: ("Изморозь", "fog"),
    51: ("Слабая морось", "rain"), 53: ("Морось", "rain"), 55: ("Сильная морось", "rain"),
    56: ("Ледяная морось", "rain"), 57: ("Ледяная морось", "rain"),
    61: ("Небольшой дождь", "rain"), 63: ("Дождь", "rain"), 65: ("Сильный дождь", "rain"),
    66: ("Ледяной дождь", "rain"), 67: ("Ледяной дождь", "rain"),
    71: ("Небольшой снег", "snow"), 73: ("Снег", "snow"), 75: ("Сильный снег", "snow"),
    77: ("Снежная крупа", "snow"), 80: ("Небольшой ливень", "rain"), 81: ("Ливень", "rain"),
    82: ("Сильный ливень", "rain"), 85: ("Снегопад", "snow"), 86: ("Сильный снегопад", "snow"),
    95: ("Гроза", "storm"), 96: ("Гроза с градом", "storm"), 99: ("Гроза с градом", "storm"),
}
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


class WeatherError(Exception):
    """Понятная пользователю причина, по которой погоды нет."""


@dataclass(frozen=True)
class Day:
    date: str            # ГГГГ-ММ-ДД
    t_min: float
    t_max: float
    code: int

    @property
    def weekday(self) -> str:
        try:
            return WEEKDAYS[time.strptime(self.date, "%Y-%m-%d").tm_wday]
        except ValueError:
            return self.date


@dataclass(frozen=True)
class Weather:
    city: str
    temp: float
    feels: float | None
    code: int
    wind: float | None          # м/с
    humidity: float | None      # %
    days: tuple[Day, ...] = ()
    fetched: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        return describe(self.code)[0]

    @property
    def icon(self) -> str:
        return describe(self.code)[1]


def describe(code: Any) -> tuple[str, str]:
    return _CODES.get(code if isinstance(code, int) else -1, ("Нет описания", "cloud"))


def format_temp(value: float | None) -> str:
    """«+7°», «−3°», «0°»; «—», если значения нет."""
    if value is None:
        return "—"
    rounded = int(round(value))
    return f"{'+' if rounded > 0 else '−' if rounded < 0 else ''}{abs(rounded)}°"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_geocode(data: Any) -> tuple[float, float, str] | None:
    """(широта, долгота, название) первого найденного места или None."""
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    place = results[0]
    lat, lon = _num(place.get("latitude")), _num(place.get("longitude"))
    if lat is None or lon is None:
        return None
    return lat, lon, str(place.get("name") or "")


def parse_forecast(data: Any, city: str) -> Weather:
    current = data.get("current") if isinstance(data, dict) else None
    temp = _num(current.get("temperature_2m")) if isinstance(current, dict) else None
    if temp is None:
        raise WeatherError("Сервис погоды вернул ответ без температуры")
    code = current.get("weather_code")
    days: list[Day] = []
    daily = data.get("daily")
    if isinstance(daily, dict):
        rows = zip(daily.get("time") or [], daily.get("temperature_2m_min") or [],
                   daily.get("temperature_2m_max") or [], daily.get("weather_code") or [])
        for date, t_min, t_max, day_code in rows:
            lo, hi = _num(t_min), _num(t_max)
            if isinstance(date, str) and lo is not None and hi is not None:
                days.append(Day(date, lo, hi, day_code if isinstance(day_code, int) else -1))
    return Weather(city, temp, _num(current.get("apparent_temperature")), code if isinstance(code, int) else -1,
                   _num(current.get("wind_speed_10m")), _num(current.get("relative_humidity_2m")), tuple(days))


def _get(url: str, params: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "SIRIUS"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:   # noqa: S310 — адреса заданы выше
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WeatherError("Нет связи с сервисом погоды") from exc
    except ValueError as exc:
        raise WeatherError("Сервис погоды вернул непонятный ответ") from exc


def geocode(city: str, timeout: float = TIMEOUT) -> tuple[float, float, str]:
    found = parse_geocode(_get(GEOCODE_URL, {"name": city, "count": 1, "language": "ru", "format": "json"}, timeout))
    if found is None:
        raise WeatherError(f"Город «{city}» не найден")
    return found


def fetch(lat: float, lon: float, city: str, timeout: float = TIMEOUT) -> Weather:
    data = _get(FORECAST_URL, {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "temperature_2m_min,temperature_2m_max,weather_code",
        "wind_speed_unit": "ms", "timezone": "auto", "forecast_days": 4,
    }, timeout)
    return parse_forecast(data, city)
