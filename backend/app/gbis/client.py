from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

KST = timezone(timedelta(hours=9))

import httpx

from app.config import (
    get_active_route_id,
    get_active_route_name,
    get_active_station_id,
    get_active_station_name,
    settings,
)

logger = logging.getLogger(__name__)


@dataclass
class BusArrivalInfo:
    route_name: str
    station_name: str
    predict_time1: int | None  # 첫 번째 도착 예정 (분)
    predict_time2: int | None  # 두 번째 도착 예정 (분)
    location_no1: int | None  # 첫 번째 버스 남은 정류소 수
    location_no2: int | None  # 두 번째 버스 남은 정류소 수
    station_nm1: str  # 첫 번째 버스 현재 위치 정류소
    station_nm2: str  # 두 번째 버스 현재 위치 정류소
    low_plate1: str  # 저상버스 여부 (0: 일반, 1: 저상)
    low_plate2: str
    remain_seat1: int | None  # 잔여 좌석
    remain_seat2: int | None
    flag: str  # RUN, PASS, STOP, WAIT
    crowded1: str  # 혼잡도
    crowded2: str
    last_updated: str


def _int_or_none(val: str) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def get_bus_arrival(
    station_id: int | None = None,
    route_id: int | None = None,
) -> BusArrivalInfo:
    """GBIS 버스도착정보항목조회 API를 호출하여 도착 정보를 반환한다."""
    sid = station_id or get_active_station_id()
    rid = route_id or get_active_route_id()
    active_station_name = get_active_station_name()
    active_route_name = get_active_route_name()

    url = f"{settings.gbus_api_url}/getBusArrivalItemv2"
    params = {
        "serviceKey": unquote(settings.public_data_api_key),
        "stationId": sid,
        "routeId": rid,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    header = data["response"]["msgHeader"]
    if header["resultCode"] != 0:
        raise RuntimeError(f"GBIS API error: {header['resultMessage']}")

    item = data["response"]["msgBody"]["busArrivalItem"]
    now = datetime.now(KST).strftime("%H:%M")

    return BusArrivalInfo(
        route_name=str(item.get("routeName", active_route_name)),
        station_name=active_station_name,
        predict_time1=_int_or_none(str(item.get("predictTime1", ""))),
        predict_time2=_int_or_none(str(item.get("predictTime2", ""))),
        location_no1=_int_or_none(str(item.get("locationNo1", ""))),
        location_no2=_int_or_none(str(item.get("locationNo2", ""))),
        station_nm1=str(item.get("stationNm1", "")),
        station_nm2=str(item.get("stationNm2", "")),
        low_plate1=str(item.get("lowPlate1", "")),
        low_plate2=str(item.get("lowPlate2", "")),
        remain_seat1=_int_or_none(str(item.get("remainSeatCnt1", ""))),
        remain_seat2=_int_or_none(str(item.get("remainSeatCnt2", ""))),
        flag=str(item.get("flag", "")),
        crowded1=str(item.get("crowded1", "")),
        crowded2=str(item.get("crowded2", "")),
        last_updated=now,
    )
