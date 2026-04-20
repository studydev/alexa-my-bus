from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import httpx

from app.config import (
    get_active_weather_lat,
    get_active_weather_lon,
    settings,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# OpenWeatherMap icon code → emoji
_ICON_EMOJI = {
    "01d": "☀️", "01n": "🌙",
    "02d": "⛅", "02n": "☁️",
    "03d": "☁️", "03n": "☁️",
    "04d": "☁️", "04n": "☁️",
    "09d": "🌧️", "09n": "🌧️",
    "10d": "🌦️", "10n": "🌧️",
    "11d": "⛈️", "11n": "⛈️",
    "13d": "❄️", "13n": "❄️",
    "50d": "🌫️", "50n": "🌫️",
}


def _icon_to_emoji(icon: str) -> str:
    return _ICON_EMOJI.get(icon, "🌡️")


@dataclass
class ForecastPoint:
    time_label: str  # "15시"
    temp: float
    icon: str
    emoji: str
    pop: int = 0  # 강수확률 (%)


@dataclass
class WeatherInfo:
    temp: float
    feels_like: float
    temp_min: float  # 금일 min
    temp_max: float  # 금일 max
    description: str  # 한글 설명
    main: str  # Clear, Clouds ...
    icon: str
    emoji: str
    city: str
    humidity: int
    wind_speed: float
    clouds: int
    sunrise: str
    sunset: str
    pop_max: int
    forecast: list[ForecastPoint] = field(default_factory=list)
    last_updated: str = ""


async def _fetch_current(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.openweathermap_api_key,
        "units": "metric",
        "lang": "kr",
    }
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


async def _fetch_forecast(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.openweathermap_api_key,
        "units": "metric",
        "lang": "kr",
    }
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


async def get_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> WeatherInfo:
    """OpenWeatherMap current + 5-day/3h forecast를 결합하여 반환."""
    la = lat if lat is not None else get_active_weather_lat()
    lo = lon if lon is not None else get_active_weather_lon()

    async with httpx.AsyncClient(timeout=10.0) as client:
        cur = await _fetch_current(client, la, lo)
        fc = await _fetch_forecast(client, la, lo)

    main = cur.get("main", {})
    wind = cur.get("wind", {})
    clouds = cur.get("clouds", {})
    sys = cur.get("sys", {})
    weather0 = (cur.get("weather") or [{}])[0]
    icon = weather0.get("icon", "01d")

    sunrise_ts = sys.get("sunrise")
    sunset_ts = sys.get("sunset")
    sunrise = (
        datetime.fromtimestamp(sunrise_ts, tz=timezone.utc).astimezone(KST).strftime("%H:%M")
        if sunrise_ts
        else "--:--"
    )
    sunset = (
        datetime.fromtimestamp(sunset_ts, tz=timezone.utc).astimezone(KST).strftime("%H:%M")
        if sunset_ts
        else "--:--"
    )

    # 금일(KST 기준) 전체 예보 포인트에서 min/max 계산
    today_kst = datetime.now(KST).date()
    today_min: float | None = None
    today_max: float | None = None
    forecast_points: list[ForecastPoint] = []

    for entry in fc.get("list", []):
        dt_utc = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
        dt_kst = dt_utc.astimezone(KST)
        temp = float(entry["main"]["temp"])
        if dt_kst.date() == today_kst:
            today_min = temp if today_min is None else min(today_min, temp)
            today_max = temp if today_max is None else max(today_max, temp)

    # 현재 온도도 min/max 계산에 포함
    cur_temp = float(main.get("temp", 0.0))
    if today_min is None or cur_temp < today_min:
        today_min = cur_temp
    if today_max is None or cur_temp > today_max:
        today_max = cur_temp

    # 차트용: 다가오는 8개 포인트(=24시간)
    for entry in fc.get("list", [])[:8]:
        dt_kst = datetime.fromtimestamp(entry["dt"], tz=timezone.utc).astimezone(KST)
        w0 = (entry.get("weather") or [{}])[0]
        ic = w0.get("icon", "01d")
        pop_val = float(entry.get("pop", 0.0) or 0.0)
        forecast_points.append(
            ForecastPoint(
                time_label=f"{dt_kst.hour:02d}시",
                temp=float(entry["main"]["temp"]),
                icon=ic,
                emoji=_icon_to_emoji(ic),
                pop=int(round(pop_val * 100)),
            )
        )

    return WeatherInfo(
        temp=cur_temp,
        feels_like=float(main.get("feels_like", cur_temp)),
        temp_min=float(today_min if today_min is not None else cur_temp),
        temp_max=float(today_max if today_max is not None else cur_temp),
        description=str(weather0.get("description", "")),
        main=str(weather0.get("main", "")),
        icon=icon,
        emoji=_icon_to_emoji(icon),
        city=str(cur.get("name", "")),
        humidity=int(main.get("humidity", 0) or 0),
        wind_speed=float(wind.get("speed", 0.0) or 0.0),
        clouds=int(clouds.get("all", 0) or 0),
        sunrise=sunrise,
        sunset=sunset,
        pop_max=max((point.pop for point in forecast_points), default=0),
        forecast=forecast_points,
        last_updated=datetime.now(KST).strftime("%H:%M"),
    )
