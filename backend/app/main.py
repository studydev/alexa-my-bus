import json
import logging
from pathlib import Path
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ask_sdk_webservice_support.webservice_handler import WebserviceSkillHandler

from app.alexa.handler import build_skill
from app.config import (
    get_active_route_id,
    get_active_route_name,
    get_active_station_id,
    get_active_station_name,
    load_dynamic_settings,
    save_dynamic_settings,
    settings,
)
from app.gbis.client import get_bus_arrival
from app.tts.client import OUTPUT_DIR
from app.weather.client import get_weather

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BusWatch Home", version="0.2.0")

# 정적 파일 서빙
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# TTS MP3 출력 디렉토리 서빙
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# Alexa Skill
skill = build_skill().create()
webservice_handler = WebserviceSkillHandler(
    skill=skill, verify_signature=False, verify_timestamp=False
)


@app.post("/alexa")
async def alexa_endpoint(request: Request) -> Response:
    body = await request.body()
    headers = dict(request.headers)
    alexa_response = webservice_handler.verify_request_and_dispatch(
        http_request_headers=headers, http_request_body=body
    )
    if isinstance(alexa_response, dict):
        alexa_response = json.dumps(alexa_response)
    return Response(content=alexa_response, media_type="application/json")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "station_id": get_active_station_id(),
        "station_name": get_active_station_name(),
        "route_id": get_active_route_id(),
        "route_name": get_active_route_name(),
    }


@app.get("/api/bus-arrival")
async def bus_arrival_debug():
    """개발·디버깅용: GBIS API 직접 호출 결과를 반환한다."""
    try:
        info = await get_bus_arrival()
        return {
            "route_name": info.route_name,
            "station_name": info.station_name,
            "flag": info.flag,
            "predict_time1": info.predict_time1,
            "predict_time2": info.predict_time2,
            "location_no1": info.location_no1,
            "location_no2": info.location_no2,
            "station_nm1": info.station_nm1,
            "station_nm2": info.station_nm2,
            "low_plate1": info.low_plate1,
            "low_plate2": info.low_plate2,
            "remain_seat1": info.remain_seat1,
            "remain_seat2": info.remain_seat2,
            "crowded1": info.crowded1,
            "crowded2": info.crowded2,
            "last_updated": info.last_updated,
        }
    except Exception as e:
        logger.exception("Bus arrival API error")
        return {"status": "error", "message": str(e)}


@app.get("/api/weather")
async def weather_debug():
    """개발·디버깅용: OpenWeatherMap 호출 결과를 반환한다."""
    try:
        w = await get_weather()
        return {
            "temp": w.temp,
            "feels_like": w.feels_like,
            "temp_min": w.temp_min,
            "temp_max": w.temp_max,
            "description": w.description,
            "main": w.main,
            "icon": w.icon,
            "emoji": w.emoji,
            "city": w.city,
            "humidity": w.humidity,
            "wind_speed": w.wind_speed,
            "clouds": w.clouds,
            "sunrise": w.sunrise,
            "sunset": w.sunset,
            "pop_max": w.pop_max,
            "last_updated": w.last_updated,
            "forecast": [
                {
                    "time": p.time_label,
                    "temp": p.temp,
                    "icon": p.icon,
                    "emoji": p.emoji,
                    "pop": p.pop,
                }
                for p in w.forecast
            ],
        }
    except Exception as e:
        logger.exception("Weather API error")
        return {"status": "error", "message": str(e)}


# --- Settings Frontend & API ---


@app.get("/settings")
async def settings_page():
    return FileResponse(str(_STATIC_DIR / "settings.html"))


@app.get("/preview")
async def preview_page():
    """APL 레이아웃 로컬 미리보기 (실시간 데이터)."""
    return FileResponse(str(_STATIC_DIR / "preview.html"))


@app.get("/api/settings")
async def get_settings_api():
    dyn = load_dynamic_settings()
    return {
        "station_id": dyn.get("station_id", settings.station_id),
        "station_name": dyn.get("station_name", settings.station_name),
        "route_id": dyn.get("route_id", settings.route_id),
        "route_name": dyn.get("route_name", settings.route_name),
        "route_type_name": dyn.get("route_type_name", ""),
        "tts_engine": dyn.get("tts_engine", "alexa"),
    }


@app.put("/api/settings")
async def update_settings_api(request: Request):
    data = await request.json()
    allowed = {
        "station_id", "station_name", "route_id", "route_name", "route_type_name",
        "weather_lat", "weather_lon", "tts_engine",
    }
    filtered = {k: v for k, v in data.items() if k in allowed}
    # Validate types
    for int_key in ("station_id", "route_id"):
        if int_key in filtered:
            try:
                filtered[int_key] = int(filtered[int_key])
            except (ValueError, TypeError):
                return Response(
                    content=f'{{"error":"{int_key} must be an integer"}}',
                    status_code=400,
                    media_type="application/json",
                )
    for float_key in ("weather_lat", "weather_lon"):
        if float_key in filtered:
            try:
                filtered[float_key] = float(filtered[float_key])
            except (ValueError, TypeError):
                return Response(
                    content=f'{{"error":"{float_key} must be a number"}}',
                    status_code=400,
                    media_type="application/json",
                )
    for str_key in ("station_name", "route_name", "route_type_name"):
        if str_key in filtered and not isinstance(filtered[str_key], str):
            return Response(
                content=f'{{"error":"{str_key} must be a string"}}',
                status_code=400,
                media_type="application/json",
            )
    if "tts_engine" in filtered:
        if filtered["tts_engine"] not in ("alexa", "azure", "azure_ko"):
            return Response(
                content='{"error":"tts_engine must be alexa, azure, or azure_ko"}',
                status_code=400,
                media_type="application/json",
            )
    save_dynamic_settings(filtered)
    return {"status": "ok", "saved": filtered}


@app.get("/api/stations/search")
async def search_stations(keyword: str):
    """정류소 검색 (이름 또는 번호)"""
    url = f"{settings.gbus_station_api_url}/getBusStationListv2"
    params = {"serviceKey": unquote(settings.public_data_api_key), "keyword": keyword}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    body = data["response"]["msgBody"]
    stations = body.get("busStationList", [])
    if isinstance(stations, dict):
        stations = [stations]
    return [
        {
            "stationId": s["stationId"],
            "stationName": s["stationName"],
            "mobileNo": s.get("mobileNo", "").strip(),
            "regionName": s.get("regionName", ""),
            "x": s.get("x"),
            "y": s.get("y"),
        }
        for s in stations
    ]


@app.get("/api/stations/{station_id}/routes")
async def station_routes(station_id: int):
    """정류소 경유 노선 목록"""
    url = f"{settings.gbus_station_api_url}/getBusStationViaRouteListv2"
    params = {"serviceKey": unquote(settings.public_data_api_key), "stationId": station_id}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    body = data["response"]["msgBody"]
    routes = body.get("busRouteList", [])
    if isinstance(routes, dict):
        routes = [routes]
    return [
        {
            "routeId": r["routeId"],
            "routeName": str(r["routeName"]),
            "routeTypeName": r.get("routeTypeName", ""),
            "routeDestName": r.get("routeDestName", ""),
        }
        for r in routes
    ]
