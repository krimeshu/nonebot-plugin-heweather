import asyncio

from httpx import URL, AsyncClient, Response
from nonebot.log import logger

from .config import plugin_config
from .model import AirApi, DailyApi, HourlyApi, NowApi, WarningApi
from .types import APIError, CityNotFoundError, ConfigError
from .utils import get_jwt_token


class Weather:
    def __url__(self):
        self.host = URL(plugin_config.qweather_apihost)
        # self.url_geoapi = "https://geoapi.qweather.com/v2/city/"
        # if self.api_type == 2 or self.api_type == 1:
        #     self.url_weather_api = "https://api.qweather.com/v7/weather/"
        #     self.url_weather_warning = "https://api.qweather.com/v7/warning/now"
        #     self.url_air = "https://api.qweather.com/v7/air/now"
        #     self.url_hourly = "https://api.qweather.com/v7/weather/24h"

        #     logger.info("使用标准订阅API")

        # elif self.api_type == 0:
        #     self.url_weather_api = "https://devapi.qweather.com/v7/weather/"
        #     self.url_weather_warning = "https://devapi.qweather.com/v7/warning/now"
        #     self.url_air = "https://devapi.qweather.com/v7/air/now"
        #     self.url_hourly = "https://devapi.qweather.com/v7/weather/24h"

        #     logger.info("使用免费订阅API")
        # else:
        #     raise ConfigError(
        #         "api_type 必须是为 (int)0 -> 免费订阅, "
        #         "(int)1 -> 标准订阅, (int)2 -> 商业版"
        #         f"\n当前为: ({type(self.api_type)}){self.api_type}"
        #     )

    def _forecast_days(self):
        self.forecast_days = plugin_config.qweather_forecase_days
        if self.forecast_days:
            if self.api_type == 0 and not (3 <= self.forecast_days <= 7):
                raise ConfigError("api_type = 0 免费订阅 预报天数必须 3<= x <=7")

    def __init__(self, city_name: str, api_type: int = 0):
        self.city_name = city_name
        # self.apikey = api_key
        self.api_type = api_type
        self.__url__()

        self._forecast_days()

        # self.now: Optional[Dict[str, str]] = None
        # self.daily = None
        # self.air = None
        # self.warning = None
        self.__reference = "\n请参考: https://dev.qweather.com/docs/start/status-code/"

    async def load_data(self):
        location = await self._get_city_location()
        self.city_name = location["name"]
        self.city_id = location['id']
        self.city_lat = location['lat']
        self.city_lon = location['lon']
        (
            self.now,
            self.daily,
            self.air,
            self.warning,
            self.hourly,
        ) = await asyncio.gather(
            self._now,
            self._daily,
            self._air,
            self._warning,
            self._hourly,
        )
        self._data_validate()

    async def _get_data(self, url: URL, params: dict) -> Response:
        headers = {}

        if plugin_config.qweather_apikey:
            headers = {"X-QW-Api-Key": plugin_config.qweather_apikey}

        if plugin_config.qweather_use_jwt and not plugin_config.qweather_apikey:
            headers = {
                "Authorization": f"Bearer {get_jwt_token()}",
            }

        if not headers:
            raise ConfigError("请确保已经配置 apikey 或 jwt")

        async with AsyncClient() as client:
            res = await client.get(url, params=params, headers=headers)
        return res

    async def _get_city_location(self):
        url = self.host.join("/geo/v2/city/lookup")
        res = await self._get_data(
            url=url,
            params={"location": self.city_name, "number": 1},
        )

        res = res.json()

        if res["code"] == "404":
            raise CityNotFoundError()
        elif res["code"] != "200":
            raise APIError("错误! 错误代码: {}".format(res["code"]) + self.__reference)
        else:
            return res["location"][0]

    def _data_validate(self):
        if self.now.code == "200" and self.daily.code == "200":
            pass
        else:
            raise APIError(
                "错误! 请检查配置! "
                f"错误代码: now: {self.now.code}  "
                f"daily: {self.daily.code}  "
                # + "air: {}  ".format(self.air.code if self.air else "None")
                + "warning: {}".format(self.warning.code if self.warning else "None")
                + self.__reference
            )

    def _check_response(self, response: Response) -> bool:
        if response.status_code == 200:
            logger.debug(f"{response.json()}")
            return True
        else:
            raise APIError(f"Response code:{response.status_code}")

    @property
    async def _now(self) -> NowApi:
        url = self.host.join("/v7/weather/now")
        res = await self._get_data(
            url=url,
            params={"location": self.city_id},
        )
        self._check_response(res)
        return NowApi(**res.json())

    @property
    async def _daily(self) -> DailyApi:
        url = self.host.join(f"/v7/weather/{self.forecast_days}d")
        res = await self._get_data(
            url=url,
            params={"location": self.city_id},
        )
        self._check_response(res)
        return DailyApi(**res.json())

    @property
    async def _air(self) -> AirApi:
        url = self.host.join(f"/airquality/v1/current/{self.city_lat}/{self.city_lon}")
        res = await self._get_data(
            url=url,
            params={},
        )
        # self._check_response(res)
        if res.status_code != 200:
            logger.error(f"Air API Response code:{res.status_code}")
            return AirApi(code=str(res.status_code), now=None)
        raw = res.json()
        # print('air raw:', raw)
        def get_dict(key: str, code: str):
            dict_list = raw.get(key, [])
            for item in dict_list:
                if item.get('code', None) == code:
                    return item
            return {}
        base = raw.get('indexes', [])[0] or {}
        color = base.get('color', {})
        air_now = {
            'category': base.get('category', ''),
            'tag_color': f"rgba({color.get('red',0)},{color.get('green',0)},{color.get('blue',0)},{color.get('alpha',1)})" if color else None,
            'aqi': str(base.get('aqi', 0)),
            'pm2p5': str(get_dict('pollutants', 'pm2p5').get('concentration', {}).get('value', '')),
            'pm10': str(get_dict('pollutants', 'pm10').get('concentration', {}).get('value', '')),
            'o3': str(get_dict('pollutants', 'o3').get('concentration', {}).get('value', '')),
            'co': str(get_dict('pollutants', 'co').get('concentration', {}).get('value', '')),
            'no2': str(get_dict('pollutants', 'no2').get('concentration', {}).get('value', '')),
            'so2': str(get_dict('pollutants', 'so2').get('concentration', {}).get('value', '')),
        }
        air = {
            'code': res.status_code,
            'now': air_now,
        }
        # return AirApi(**res.json())
        return AirApi(**air)

    @property
    async def _warning(self) -> WarningApi | None:
        url = self.host.join("/v7/warning/now")
        res = await self._get_data(
            url=url,
            params={"location": self.city_id},
        )
        # self._check_response(res)
        if res.status_code != 200:
            logger.error(f"Warning API Response code:{res.status_code}")
            return None
        if res.json().get("code") == "204":
            return None
        return WarningApi(**res.json())

    @property
    async def _hourly(self) -> HourlyApi:
        url = self.host.join("/v7/weather/24h")
        res = await self._get_data(
            url=url,
            params={"location": self.city_id},
        )
        self._check_response(res)
        return HourlyApi(**res.json())
