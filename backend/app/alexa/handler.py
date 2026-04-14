from __future__ import annotations

import asyncio
import logging

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler,
    AbstractRequestHandler,
)
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_supported_interfaces, is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective

from app.alexa.apl import load_apl_document
from app.config import (
    get_active_route_name,
    get_active_route_type_name,
    get_active_station_name,
    settings,
)
from app.gbis.client import BusArrivalInfo, get_bus_arrival

logger = logging.getLogger(__name__)


def _get_route_type() -> str:
    """GBIS routeTypeName으로 버스 색상 결정
    - 빨간색: 직행좌석형시내버스, 좌석형시내버스
    - 파란색: 일반형시내버스 (간선)
    - 초록색: 마을버스
    """
    type_name = get_active_route_type_name()
    if "직행" in type_name or "좌석" in type_name or "광역" in type_name:
        return "red"
    if "마을" in type_name:
        return "green"
    return "blue"


def _build_apl_datasource(info: BusArrivalInfo) -> dict:
    return {
        "busData": {
            "routeName": info.route_name,
            "routeType": _get_route_type(),
            "stationName": info.station_name,
            "predictTime1": info.predict_time1,
            "predictTime2": info.predict_time2,
            "locationNo1": info.location_no1,
            "locationNo2": info.location_no2,
            "stationNm1": info.station_nm1,
            "stationNm2": info.station_nm2,
            "lowPlate1": info.low_plate1,
            "lowPlate2": info.low_plate2,
            "remainSeat1": info.remain_seat1,
            "remainSeat2": info.remain_seat2,
            "flag": info.flag,
            "crowded1": info.crowded1,
            "crowded2": info.crowded2,
            "lastUpdated": info.last_updated,
        }
    }


def _build_speech(info: BusArrivalInfo) -> str:
    if info.flag == "STOP" or (info.flag == "PASS" and info.predict_time1 is None):
        return f"{info.route_name}번 버스는 현재 운행이 종료되었습니다."
    if info.predict_time1 is None:
        return f"{info.route_name}번 버스 도착 정보가 없습니다."
    speech = f"{info.route_name}번 버스가 약 {info.predict_time1}분 후에 도착합니다."
    if info.predict_time2 is not None:
        speech += f" 그 다음 버스는 약 {info.predict_time2}분 후에 도착합니다."
    return speech


def _supports_apl(handler_input: HandlerInput) -> bool:
    try:
        supported = get_supported_interfaces(handler_input)
        return (
            supported is not None
            and supported.alexa_presentation_apl is not None
        )
    except (AttributeError, TypeError):
        return False


def _add_apl_directive(handler_input: HandlerInput, info: BusArrivalInfo) -> None:
    if not _supports_apl(handler_input):
        return
    handler_input.response_builder.add_directive(
        RenderDocumentDirective(
            token="busArrivalToken",
            document=load_apl_document("bus_arrival"),
            datasources=_build_apl_datasource(info),
        )
    )


async def _fetch_arrival() -> BusArrivalInfo:
    return await get_bus_arrival()


def _fetch_arrival_sync() -> BusArrivalInfo:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _fetch_arrival()).result()
    return asyncio.run(_fetch_arrival())


def _error_arrival_info() -> BusArrivalInfo:
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    return BusArrivalInfo(
        route_name=get_active_route_name(),
        station_name=get_active_station_name(),
        predict_time1=None,
        predict_time2=None,
        location_no1=None,
        location_no2=None,
        station_nm1="",
        station_nm2="",
        low_plate1="",
        low_plate2="",
        remain_seat1=None,
        remain_seat2=None,
        flag="ERROR",
        crowded1="",
        crowded2="",
        last_updated=datetime.now(KST).strftime("%H:%M"),
    )


# --- Handlers ---


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        try:
            info = _fetch_arrival_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival")
            info = _error_arrival_info()

        speech = _build_speech(info)
        _add_apl_directive(handler_input, info)

        return (
            handler_input.response_builder
            .speak(speech)
            .ask(" ")
            .set_should_end_session(False)
            .response
        )


class BusArrivalIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("BusArrivalIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        try:
            info = _fetch_arrival_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival")
            info = _error_arrival_info()

        speech = _build_speech(info)
        _add_apl_directive(handler_input, info)

        return (
            handler_input.response_builder
            .speak(speech)
            .ask(" ")
            .set_should_end_session(False)
            .response
        )


class RefreshEventHandler(AbstractRequestHandler):
    """APL SendEvent에서 보낸 자동 갱신 요청을 처리한다."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if is_request_type("Alexa.Presentation.APL.UserEvent")(handler_input):
            args = handler_input.request_envelope.request.arguments
            return args and args[0] == "refresh"
        return False

    def handle(self, handler_input: HandlerInput) -> Response:
        try:
            info = _fetch_arrival_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival on refresh")
            info = _error_arrival_info()

        _add_apl_directive(handler_input, info)

        return (
            handler_input.response_builder
            .set_should_end_session(False)
            .response
        )


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        station = get_active_station_name()
        route = get_active_route_name()
        speech = (
            f"이 스킬은 {station} 정류소의 "
            f"{route}번 버스 도착 정보를 보여줍니다. "
            "버스 도착 정보를 확인하려면 next bus 라고 말해보세요."
        )
        return (
            handler_input.response_builder
            .speak(speech)
            .ask("next bus 라고 말해보세요.")
            .set_should_end_session(False)
            .response
        )


class CancelStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or is_intent_name(
            "AMAZON.StopIntent"
        )(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder
            .speak("안녕히 가세요.")
            .set_should_end_session(True)
            .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        logger.exception("Unhandled exception")
        return (
            handler_input.response_builder
            .speak("오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
            .set_should_end_session(True)
            .response
        )


# --- Skill Builder ---

def build_skill() -> SkillBuilder:
    sb = SkillBuilder()
    sb.add_request_handler(LaunchRequestHandler())
    sb.add_request_handler(RefreshEventHandler())
    sb.add_request_handler(BusArrivalIntentHandler())
    sb.add_request_handler(HelpIntentHandler())
    sb.add_request_handler(CancelStopIntentHandler())
    sb.add_request_handler(SessionEndedRequestHandler())
    sb.add_exception_handler(CatchAllExceptionHandler())
    return sb
