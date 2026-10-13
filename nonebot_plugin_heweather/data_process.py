"""天气数据处理 (纯数据逻辑, 不依赖 nonebot)。

从 render_pic.py 抽离, 供正式渲染 (render_pic.py) 与离线渲染测试
(tests/weather_render.py) 共用。所有函数对普通 dict / list 结构原地处理并返回,
因此可在无 nonebot / 无浏览器环境下被直接调用, 避免逻辑在测试 mock 中重复维护。
"""

from datetime import datetime
import platform

# 与 model.HourlyType 保持一致: 1 = 当前 12 小时, 2 = 当前 24 小时
HOURLY_TYPE_12H = 1
HOURLY_TYPE_24H = 2


def add_hour_data(hourly: list[dict], hourly_type: int | None = None) -> list[dict]:
    """为逐小时数据补充展示用的 hour / hour_num 字段, 并按订阅类型裁剪。

    hourly_type 兼容传入 int 或 model.HourlyType (IntEnum 与其整数值相等);
    传 None 时不裁剪 (测试场景直接渲染全部 mock 数据)。
    """
    for hour in hourly:
        date_time = datetime.fromisoformat(hour["fxTime"])
        if platform.system() == "Windows":
            hour["hour"] = date_time.strftime("%#I%p")
        else:
            hour["hour"] = date_time.strftime("%-I%p")
        hour["hour_num"] = date_time.hour
    if hourly_type == HOURLY_TYPE_12H:
        hourly = hourly[:12]
    if hourly_type == HOURLY_TYPE_24H:
        hourly = hourly[::2]
    return hourly


def add_date(daily: list[dict]) -> list[dict]:
    """为逐日数据补充 week (周几) 与 date (M月D日) 字段。"""
    week_map = [
        "周日",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
    ]

    for day in daily:
        date = day["fxDate"].split("-")
        _year = int(date[0])
        _month = int(date[1])
        _day = int(date[2])
        week = int(datetime(_year, _month, _day, 0, 0).strftime("%w"))
        day["week"] = week_map[week] if day != 0 else "今日"
        day["date"] = f"{_month}月{_day}日"

    return daily


def add_tag_color(air: dict) -> dict:
    """根据空气质量等级给顶部标签着色。"""
    color = {
        "优": "#95B359",
        "良": "#A9A538",
        "轻度污染": "#E0991D",
        "中度污染": "#D96161",
        "重度污染": "#A257D0",
        "严重污染": "#D94371",
    }
    air["tag_color"] = color[air["category"]]
    return air


# 空气质量分指数 (IAQI) 计算, 依据 HJ 633-2012
# IAQI 分级阈值
_IAQI_LEVELS = [0, 50, 100, 150, 200, 300, 400, 500]
# 各污染物浓度限值 (CO 单位 mg/m³, 其余 μg/m³)
_AIR_BREAKPOINTS = {
    "pm2p5": [0, 35, 75, 115, 150, 250, 350, 500],
    "pm10": [0, 50, 150, 250, 350, 420, 500, 600],
    "o3": [0, 160, 200, 300, 400, 800, 1000, 1200],
    "co": [0, 2, 4, 14, 24, 36, 48, 60],
    "no2": [0, 40, 80, 180, 280, 565, 750, 940],
    "so2": [0, 50, 150, 475, 800, 1600, 2100, 2620],
}
# 展示顺序与名称 (name 含 HTML 下标, 模板用 |safe 渲染), 单位
_AIR_META = [
    ("pm2p5", "PM2.5", "μg/m³"),
    ("pm10", "PM10", "μg/m³"),
    ("o3", "O<sub>3</sub>", "μg/m³"),
    ("co", "CO", "mg/m³"),
    ("no2", "NO<sub>2</sub>", "μg/m³"),
    ("so2", "SO<sub>2</sub>", "μg/m³"),
]
# IAQI -> (等级, 颜色), 与 add_tag_color 配色体系一致
_AIR_LEVEL_COLOR = [
    (50, "优", "#95B359"),
    (100, "良", "#A9A538"),
    (150, "轻度", "#E0991D"),
    (200, "中度", "#D96161"),
    (300, "重度", "#A257D0"),
    (10**9, "严重", "#D94371"),
]
# 进度条满刻度对应的 IAQI (300 = 重度污染上限), 超出则填满
_AIR_BAR_SCALE = 300


def _calc_iaqi(key: str, value: float) -> float | None:
    bp = _AIR_BREAKPOINTS.get(key)
    if not bp:
        return None
    if value <= 0:
        return 0.0
    for i in range(len(bp) - 1):
        if bp[i] <= value <= bp[i + 1]:
            lo, hi = bp[i], bp[i + 1]
            ilo, ihi = _IAQI_LEVELS[i], _IAQI_LEVELS[i + 1]
            return (ihi - ilo) / (hi - lo) * (value - lo) + ilo
    return float(_IAQI_LEVELS[-1])  # 超出量表上限, 按最高分指数


def _iaqi_level(iaqi: float) -> tuple[str, str]:
    for limit, name, color in _AIR_LEVEL_COLOR:
        if iaqi <= limit:
            return name, color
    last = _AIR_LEVEL_COLOR[-1]
    return last[1], last[2]


def add_air_data(air: dict | None) -> dict | None:
    """计算每个污染物的 IAQI 分指数, 据此归一化进度条长度并分级配色,
    同时标记首要污染物 (IAQI 最高者), 结果挂到 air["pollutants"] 供模板循环渲染。"""
    if not air:
        return air

    pollutants: list[dict] = []
    primary_idx = -1
    primary_iaqi = -1.0
    for key, name, unit in _AIR_META:
        raw = air.get(key, "")
        try:
            value = float(raw)
            has_value = True
        except (TypeError, ValueError):
            value = 0.0
            has_value = False

        if has_value:
            iaqi = _calc_iaqi(key, value)
            iaqi_val = iaqi if iaqi is not None else 0.0
            level, color = _iaqi_level(iaqi_val)
            percent = max(3, min(100, round(iaqi_val / _AIR_BAR_SCALE * 100)))
            if iaqi_val > primary_iaqi:
                primary_iaqi = iaqi_val
                primary_idx = len(pollutants)
        else:
            iaqi = None
            level, color = "—", "#9aa0a6"
            percent = 0

        pollutants.append(
            {
                "key": key,
                "name": name,
                "unit": unit,
                "value": raw if has_value else "N/A",
                "iaqi": round(iaqi) if iaqi is not None else None,
                "percent": percent,
                "color": color,
                "level": level,
                "is_primary": False,
            }
        )

    if primary_idx >= 0:
        pollutants[primary_idx]["is_primary"] = True

    air["pollutants"] = pollutants
    return air
