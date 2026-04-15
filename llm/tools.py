from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain.tools import tool

from services.place_search_tool import search_place_tool
from services.scheduler_service import create_schedule
from services.weather_service import (
    build_weather_based_route_decision,
    normalize_city_name_for_weather,
)


class WeatherInput(BaseModel):
    city_name: str = Field(description="날씨를 확인할 도시명. 예: 부산, 서울, 도쿄")
    travel_date: Optional[str] = Field(
        default=None,
        description="여행 날짜. YYYY-MM-DD 형식. 없으면 null"
    )


@tool("get_weather", args_schema=WeatherInput)
def get_weather_tool(city_name: str, travel_date: Optional[str] = None) -> dict:
    """
    도시와 여행 날짜를 기준으로 날씨와 실내/야외 추천 여부를 반환한다.
    날짜가 너무 멀면 정확한 날씨 대신 제한 사항을 알려준다.
    """
    try:
        normalized_city = normalize_city_name_for_weather(city_name)
        result = build_weather_based_route_decision(
            city_name=normalized_city,
            travel_date=travel_date
        )

        # 사용자용 도시명도 같이 실어주면 후처리에 편함
        result["display_city_name"] = city_name
        result["normalized_city_name"] = normalized_city

        return result

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "display_city_name": city_name,
            "normalized_city_name": None
        }


class MakeScheduleInput(BaseModel):
    places: List[Dict[str, Any]] = Field(description="장소 리스트")
    start_time: str = Field(default="09:00", description="일정 시작 시각, HH:MM 형식")
    mode: str = Field(default="transit", description="이동 수단: transit, walking, driving")
    optimize_route: bool = Field(default=True, description="최적 동선 여부")


@tool("make_schedule", args_schema=MakeScheduleInput)
def make_schedule_tool(
    places: List[Dict[str, Any]],
    start_time: str = "09:00",
    mode: str = "transit",
    optimize_route: bool = True,
) -> dict:
    """
    장소 리스트를 기반으로 시간대별 일정을 생성한다.
    """
    try:
        result = create_schedule(
            places=places,
            start_time_str=start_time,
            mode=mode,
            optimize_route=optimize_route,
        )

        if isinstance(result, dict) and result.get("status") == "error":
            return result

        return {
            "status": "success",
            "data": {
                "start_time": start_time,
                "mode": mode,
                "optimize_route": optimize_route,
                "itinerary": result,
            },
            "error": None,
            "meta": {"tool_name": "make_schedule"},
        }

    except Exception as e:
        return {
            "status": "error",
            "data": None,
            "error": str(e),
            "meta": {"tool_name": "make_schedule"},
        }


TOOLS = [
    get_weather_tool,
    search_place_tool,
    make_schedule_tool,
]