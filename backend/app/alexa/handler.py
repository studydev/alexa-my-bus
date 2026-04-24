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
    get_active_tts_engine,
    settings,
)
from app.gbis.client import BusArrivalInfo, get_bus_arrival
from app.tts.client import synthesize_speech
from app.weather.client import WeatherInfo, get_weather

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


def _build_weather_payload(weather: WeatherInfo | None) -> dict | None:
    if weather is None:
        return None
    # 온도 상대 위치를 0~60dp 스페이서로 변환 (더울수록 위 = 작은 paddingTop)
    temps = [p.temp for p in weather.forecast]
    if temps:
        lo, hi = min(temps), max(temps)
        span = max(hi - lo, 1.0)
    else:
        lo, hi, span = 0.0, 1.0, 1.0
    points = []
    for p in weather.forecast:
        ratio = (p.temp - lo) / span  # 0..1 (1=가장 더움)
        top_pad = int(round((1 - ratio) * 60))  # 0..60dp
        if p.temp <= 0:
            temp_color = "#42A5F5"
        elif p.temp >= 25:
            temp_color = "#FF7043"
        else:
            temp_color = "#FFFFFF"
        points.append({
            "time": p.time_label,
            "temp": round(p.temp),
            "emoji": p.emoji,
            "pop": p.pop,
            "topPadding": top_pad,
            "tempColor": temp_color,
        })
    return {
        "temp": round(weather.temp),
        "feelsLike": round(weather.feels_like),
        "tempMin": round(weather.temp_min),
        "tempMax": round(weather.temp_max),
        "tomorrowMin": round(weather.tomorrow_min) if weather.tomorrow_min is not None else None,
        "tomorrowMax": round(weather.tomorrow_max) if weather.tomorrow_max is not None else None,
        "description": weather.description,
        "emoji": weather.emoji,
        "city": weather.city,
        "humidity": weather.humidity,
        "windSpeed": round(weather.wind_speed, 1),
        "clouds": weather.clouds,
        "sunrise": weather.sunrise,
        "sunset": weather.sunset,
        "popMax": weather.pop_max,
        "lastUpdated": weather.last_updated,
        "forecast": points,
    }


def _build_apl_datasource(info: BusArrivalInfo, weather: WeatherInfo | None) -> dict:
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
        },
        "weatherData": _build_weather_payload(weather),
    }


def _build_speech(info: BusArrivalInfo, weather: WeatherInfo | None = None) -> str:
    if info.flag == "STOP" or (info.flag == "PASS" and info.predict_time1 is None):
        speech = f"{info.route_name}번 버스는 현재 운행이 종료되었습니다."
    elif info.predict_time1 is None:
        speech = f"{info.route_name}번 버스 도착 정보가 없습니다."
    else:
        speech = f"{info.route_name}번 버스가 약 {info.predict_time1}분 후에 도착합니다."
        if info.predict_time2 is not None:
            speech += f" 그 다음 버스는 약 {info.predict_time2}분 후에 도착합니다."

    if weather is not None:
        speech += _build_weather_speech(weather)
    return speech


def _build_weather_speech(weather: WeatherInfo) -> str:
    desc = weather.description or "알 수 없음"
    will_rain = False
    # 현재 강수 관련 상태 또는 예보 pop > 30% 이상이면 비 예보로 간주
    rain_keywords = ("비", "소나기", "이슬비", "진눈깨비", "눈")
    if any(k in desc for k in rain_keywords):
        will_rain = True
    else:
        try:
            if (weather.pop_max or 0) >= 30:
                will_rain = True
        except Exception:
            pass

    rain_sentence = (
        " 금일은 비가 올 수도 있습니다."
        if will_rain
        else " 금일은 비가 오지 않을 예정입니다."
    )
    return (
        f" 현재 날씨는 {desc}입니다."
        f"{rain_sentence}"
        f" 현재 온도는 {round(weather.temp)}도,"
        f" 금일 최고 온도는 {round(weather.temp_max)}도,"
        f" 최저 온도는 {round(weather.temp_min)}도입니다."
    )


def _supports_apl(handler_input: HandlerInput) -> bool:
    try:
        supported = get_supported_interfaces(handler_input)
        return (
            supported is not None
            and supported.alexa_presentation_apl is not None
        )
    except (AttributeError, TypeError):
        return False


def _wrap_speech_with_azure_tts(speech_text: str) -> str:
    """Azure TTS로 MP3를 생성하고 SSML <audio> 태그로 감싸 반환한다.
    실패 시 원본 텍스트를 그대로 반환한다 (Alexa 기본 TTS 폴백).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                filename = pool.submit(asyncio.run, synthesize_speech(speech_text)).result()
        else:
            filename = asyncio.run(synthesize_speech(speech_text))
    except Exception:
        logger.exception("Azure TTS 생성 실패, Alexa 기본 음성 사용")
        return speech_text

    if filename is None:
        return speech_text

    audio_url = f"{settings.tts_base_url}/output/{filename}"
    return f'<audio src="{audio_url}"/>'


def _add_apl_directive(
    handler_input: HandlerInput,
    info: BusArrivalInfo,
    weather: WeatherInfo | None,
) -> None:
    if not _supports_apl(handler_input):
        return
    handler_input.response_builder.add_directive(
        RenderDocumentDirective(
            token="busArrivalToken",
            document=load_apl_document("bus_arrival"),
            datasources=_build_apl_datasource(info, weather),
        )
    )


async def _fetch_all() -> tuple[BusArrivalInfo, WeatherInfo | None]:
    results = await asyncio.gather(
        get_bus_arrival(),
        _safe_get_weather(),
        return_exceptions=True,
    )
    bus_result, weather_result = results
    if isinstance(bus_result, BaseException):
        logger.exception("Failed to fetch bus arrival", exc_info=bus_result)
        bus_info = _error_arrival_info()
    else:
        bus_info = bus_result
    if isinstance(weather_result, BaseException):
        weather_info = None
    else:
        weather_info = weather_result
    return bus_info, weather_info


async def _safe_get_weather() -> WeatherInfo | None:
    try:
        return await get_weather()
    except Exception:
        logger.exception("Failed to fetch weather")
        return None


def _fetch_all_sync() -> tuple[BusArrivalInfo, WeatherInfo | None]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _fetch_all()).result()
    return asyncio.run(_fetch_all())


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
            info, weather = _fetch_all_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival")
            info = _error_arrival_info()
            weather = None

        speech = _build_speech(info, weather)
        if get_active_tts_engine() == "azure":
            speech = _wrap_speech_with_azure_tts(speech)
        _add_apl_directive(handler_input, info, weather)

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
            info, weather = _fetch_all_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival")
            info = _error_arrival_info()
            weather = None

        speech = _build_speech(info, weather)
        if get_active_tts_engine() == "azure":
            speech = _wrap_speech_with_azure_tts(speech)
        _add_apl_directive(handler_input, info, weather)

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
            info, weather = _fetch_all_sync()
        except Exception:
            logger.exception("Failed to fetch bus arrival on refresh")
            info = _error_arrival_info()
            weather = None

        _add_apl_directive(handler_input, info, weather)

        return (
            handler_input.response_builder
            .ask(" ")
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
