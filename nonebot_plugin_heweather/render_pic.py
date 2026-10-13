from pathlib import Path

from nonebot_plugin_htmlrender import template_to_pic

from .config import plugin_config
from .data_process import add_air_data, add_date, add_hour_data
from .weather_data import Weather


def _to_dict(obj) -> dict:
    """把 pydantic 模型 (v1/v2 兼容) 转为普通 dict, 供 data_process 原地处理。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return dict(obj)


async def render(weather: Weather) -> bytes:
    template_path = str(Path(__file__).parent / "templates")

    # 数据处理逻辑统一收敛到 data_process (与 tests/weather_render.py 共用),
    # 此处先把待处理的模型转成 dict, 其余字段 (now/warning) 模板可直接访问。
    days = [_to_dict(d) for d in weather.daily.daily]
    hours = [_to_dict(h) for h in weather.hourly.hourly]
    air_now = weather.air.now if weather.air else None
    air = _to_dict(air_now) if air_now else None

    return await template_to_pic(
        template_path=template_path,
        template_name="weather.html",
        templates={
            "now": weather.now.now,
            "days": add_date(days),
            "city": weather.city_name,
            "warning": weather.warning,
            "air": add_air_data(air),
            "hours": add_hour_data(hours, plugin_config.qweather_hourlytype),
        },
        pages={
            "viewport": {"width": 1000, "height": 300},
            "base_url": f"file://{template_path}",
        },
    )
