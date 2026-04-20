import json
from pathlib import Path

from pydantic_settings import BaseSettings

_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.json"


class Settings(BaseSettings):
    # GBIS API
    gbus_api_url: str = "https://apis.data.go.kr/6410000/busarrivalservice/v2"
    gbus_route_api_url: str = "https://apis.data.go.kr/6410000/busrouteservice/v2"
    gbus_station_api_url: str = "https://apis.data.go.kr/6410000/busstationservice/v2"
    public_data_api_key: str

    # BusWatch Home 타겟 (기본값, settings.json으로 오버라이드 가능)
    station_id: int = 224000050
    station_name: str = "목감중심상업지구"
    route_id: int = 216000047
    route_name: str = "5602"

    # 갱신 간격 (밀리초)
    refresh_interval_ms: int = 60000

    # OpenWeatherMap
    openweathermap_api_key: str = ""
    weather_lat: float = 37.3885  # 목감중심상업지구 기본값
    weather_lon: float = 126.8615

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()


def load_dynamic_settings() -> dict:
    if _SETTINGS_FILE.exists():
        return json.loads(_SETTINGS_FILE.read_text("utf-8"))
    return {}


def save_dynamic_settings(data: dict) -> None:
    current = load_dynamic_settings()
    current.update(data)
    _SETTINGS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), "utf-8")


def get_active_station_id() -> int:
    return load_dynamic_settings().get("station_id", settings.station_id)


def get_active_route_id() -> int:
    return load_dynamic_settings().get("route_id", settings.route_id)


def get_active_station_name() -> str:
    return load_dynamic_settings().get("station_name", settings.station_name)


def get_active_route_name() -> str:
    return load_dynamic_settings().get("route_name", settings.route_name)


def get_active_route_type_name() -> str:
    return load_dynamic_settings().get("route_type_name", "")


def get_active_weather_lat() -> float:
    return float(load_dynamic_settings().get("weather_lat", settings.weather_lat))


def get_active_weather_lon() -> float:
    return float(load_dynamic_settings().get("weather_lon", settings.weather_lon))
