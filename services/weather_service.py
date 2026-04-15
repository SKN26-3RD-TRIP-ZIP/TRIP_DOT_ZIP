# services/weather_tool.py

import json
import requests
import openai
from config import Settings
from llm.prompts import SYSTEM_PROMPT
from datetime import date, datetime


settings = Settings()
weather_api_key = settings.weather_api_key
openai_api_key = settings.openai_api_key
client = openai.OpenAI(api_key=openai_api_key)

# -----------------------------
# 도시명 변환용 맵
# 사용자에게는 한국어로 보여주고,
# API 호출할 때만 영어 표준명으로 변환
# -----------------------------
CITY_NAME_MAP = {
    "서울": "Seoul",
    "부산": "Busan",
    "전주": "Jeonju",
    "제주": "Jeju",
    "대구": "Daegu",
    "대전": "Daejeon",
    "광주": "Gwangju",
    "인천": "Incheon",
    "울산": "Ulsan",
    "수원": "Suwon",
    "경주": "Gyeongju",
    "여수": "Yeosu",
    "속초": "Sokcho",
    "강릉": "Gangneung",
    "춘천": "Chuncheon",
    "포항": "Pohang",
    "목포": "Mokpo",
    "도쿄": "Tokyo",
    "오사카": "Osaka",
    "후쿠오카": "Fukuoka",
    "교토": "Kyoto",
    "삿포로": "Sapporo",
}

def normalize_city_name_for_weather(city_name: str | None) -> str:
    if not city_name:
        return "Seoul"
    return CITY_NAME_MAP.get(city_name, city_name)


def get_current_weather(city_name: str = "Seoul", units: str = "metric") -> str:
    """
    OpenWeather API를 사용하여 사용자가 지정한 도시의 현재 날씨 정보를 가져오는 함수

    Args:
        city_name (str): 날씨 정보를 가져올 도시 이름. 가능하면 영어로 작성
        units (str): 온도 단위
            - metric: 섭씨(Celsius)
            - imperial: 화씨(Fahrenheit)
            - standard: 절대온도(Kelvin)

    Returns:
        str: JSON 문자열 형태의 현재 날씨 정보
    """
    if not weather_api_key:
        return json.dumps({
            "status": "error",
            "message": "weather_api_key가 설정되지 않았습니다."
        }, ensure_ascii=False)

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city_name,
        "appid": weather_api_key,
        "units": units,
        "lang": "kr"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if response.status_code == 200:
            weather_info = {
                "status": "success",
                "city": data.get("name", city_name),
                "country": data.get("sys", {}).get("country"),
                "description": data.get("weather", [{}])[0].get("description", "정보 없음"),
                "temperature": data.get("main", {}).get("temp"),
                "temperature_feels_like": data.get("main", {}).get("feels_like"),
                "temp_min": data.get("main", {}).get("temp_min"),
                "temp_max": data.get("main", {}).get("temp_max"),
                "humidity": data.get("main", {}).get("humidity"),
                "pressure": data.get("main", {}).get("pressure"),
                "wind_speed": data.get("wind", {}).get("speed"),
                "clouds": data.get("clouds", {}).get("all")
            }
        else:
            weather_info = {
                "status": "error",
                "city": city_name,
                "message": data.get("message", "날씨 정보를 찾을 수 없습니다."),
                "description": "Not Found",
                "temperature": None,
                "temperature_feels_like": None,
                "humidity": None
            }

        return json.dumps(weather_info, ensure_ascii=False)

    except requests.RequestException as e:
        return json.dumps({
            "status": "error",
            "city": city_name,
            "message": f"요청 중 오류 발생: {str(e)}"
        }, ensure_ascii=False)


tools_to_execute = {
    "get_current_weather": get_current_weather
}


client = openai.OpenAI(api_key=openai_api_key)


def run_conversation(user_prompt: str, model: str = "gpt-4.1-mini") -> str:
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "특정 도시의 현재 날씨 정보를 조회합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city_name": {
                            "type": "string",
                            "description": "도시 이름. 가능하면 영어로 작성. 예: Seoul, Busan, Tokyo"
                        },
                        "units": {
                            "type": "string",
                            "enum": ["metric", "imperial", "standard"],
                            "description": "온도 단위. metric=섭씨, imperial=화씨, standard=절대온도"
                        }
                    },
                    "required": ["city_name"]
                }
            }
        }
    ]

    response1 = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    response1_message = response1.choices[0].message
    tool_calls = response1_message.tool_calls

    if tool_calls:
        messages.append(response1_message)

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            print(f"[tool] {function_name} 호출 중...")
            function_to_execute = tools_to_execute[function_name]
            function_response = function_to_execute(**function_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": function_response
            })

        response2 = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response2.choices[0].message.content

    return response1_message.content

# ---------------------
# 날짜 판별
# ---------------------

def classify_trip_timing(travel_date: str | None = None) -> dict:
    """
    travel_date: '2026-05-20' 형식 가정
    """
    if not travel_date:
        return {
            "status": "unknown_date",
            "message": "여행 날짜 정보가 없습니다."
        }

    try:
        target = datetime.strptime(travel_date, "%Y-%m-%d").date()
        today = date.today()
        diff_days = (target - today).days

        if diff_days < 0:
            return {
                "status": "past_date",
                "message": "이미 지난 날짜입니다."
            }
        elif diff_days <= 5:
            return {
                "status": "current_weather_available",
                "message": "가까운 날짜이므로 현재/단기 날씨 기준으로 추천할 수 있습니다."
            }
        elif diff_days <= 30:
            return {
                "status": "forecast_maybe",
                "message": "가까운 미래 여행입니다."
            }
        else:
            return {
                "status": "too_far",
                "message": "정확한 날씨를 보기엔 너무 먼 날짜입니다."
            }
    except ValueError:
        return {
            "status": "invalid_date",
            "message": "날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식이어야 합니다."
        }

#----------------------
# 야외 적합도 판별
#----------------------
def classify_outdoor_condition(weather_data: dict) -> dict:
    """
    weather_data 예:
    {
        "description": "맑음",
        "temperature": 22.1,
        "humidity": 55,
        "wind_speed": 2.3
    }
    """
    description = (weather_data.get("description") or "").lower()
    temperature = weather_data.get("temperature")
    humidity = weather_data.get("humidity")
    wind_speed = weather_data.get("wind_speed", 0)

    if temperature is None or humidity is None:
        return {
            "condition_level": "unknown",
            "route_recommendation": "mixed",
            "reason": "날씨 정보가 충분하지 않습니다."
        }

    bad_keywords = ["비", "눈", "폭우", "천둥", "storm", "rain", "snow", "thunder"]
    if any(keyword in description for keyword in bad_keywords):
        return {
            "condition_level": "poor",
            "route_recommendation": "indoor",
            "reason": "강수 가능성이 있어 야외 활동이 어렵습니다."
        }

    if temperature <= 5 or temperature >= 35:
        return {
            "condition_level": "poor",
            "route_recommendation": "indoor",
            "reason": "기온이 극단적이라 야외 활동이 어렵습니다."
        }

    if humidity >= 85 and temperature >= 28:
        return {
            "condition_level": "poor",
            "route_recommendation": "indoor",
            "reason": "덥고 습해서 야외 활동이 불편합니다."
        }

    if wind_speed >= 10:
        return {
            "condition_level": "poor",
            "route_recommendation": "indoor",
            "reason": "바람이 강해 야외 활동이 어렵습니다."
        }

    if 18 <= temperature <= 26 and 30 <= humidity <= 70 and wind_speed < 7:
        return {
            "condition_level": "good",
            "route_recommendation": "outdoor",
            "reason": "기온과 습도가 비교적 쾌적해 야외 활동에 적합합니다."
        }

    return {
        "condition_level": "normal",
        "route_recommendation": "mixed",
        "reason": "실내와 야외를 섞은 일정이 적절합니다."
    }


#----------------------
# 땃쥐 멘트
#----------------------
def get_ddatchwi_message(status: str) -> dict:
    message_map = {
        "too_far": {
            "character": "땃쥐가 곤란해해요…",
            "message": "아직 그 날짜의 정확한 날씨는 알기 어려워요.",
            "options": ["1년 평균 날씨 보기", "여행 월 기준으로 추천받기", "정확한 날짜 다시 입력하기"]
        },
        "poor": {
            "character": "땃쥐가 우산을 챙겼어요!",
            "message": "오늘은 실내 위주 코스가 더 잘 어울려요.",
            "options": []
        },
        "normal": {
            "character": "땃쥐가 지도를 펼쳤어요!",
            "message": "실내와 야외를 적절히 섞은 코스를 추천할게요.",
            "options": []
        },
        "good": {
            "character": "땃쥐가 신났어요!",
            "message": "오늘은 야외 활동하기 좋은 날씨예요.",
            "options": []
        }
    }
    return message_map.get(status, {
        "character": "땃쥐가 생각 중이에요…",
        "message": "조건을 다시 확인해볼게요.",
        "options": []
    })

#----------------------
# 최종 오케스트라
#----------------------
def build_weather_based_route_decision(city_name: str, travel_date: str | None = None) -> dict:
    timing_result = classify_trip_timing(travel_date)

    if timing_result["status"] == "too_far":
        ddatchwi = get_ddatchwi_message("too_far")
        return {
            "status": "too_far",
            "weather_mode": "average_or_monthly_needed",
            "ddatchwi": ddatchwi,
            "message": timing_result["message"]
        }

    weather_json = get_current_weather(city_name=city_name, units="metric")
    weather_data = json.loads(weather_json)

    if weather_data.get("status") != "success":
        return {
            "status": "error",
            "message": weather_data.get("message", "날씨 정보를 가져오지 못했습니다.")
        }

    condition_result = classify_outdoor_condition(weather_data)
    ddatchwi = get_ddatchwi_message(condition_result["condition_level"])

    return {
        "status": "success",
        "weather": weather_data,
        "condition": condition_result,
        "ddatchwi": ddatchwi
    }

if __name__ == "__main__":

    print("\n=== 1. 먼 날짜 테스트 ===")
    result1 = build_weather_based_route_decision(
        city_name="Busan",
        travel_date="2027-05-20"
    )
    print(json.dumps(result1, indent=2, ensure_ascii=False))


    print("\n=== 2. 오늘 날짜 테스트 ===")
    result2 = build_weather_based_route_decision(
        city_name="Seoul",
        travel_date=str(date.today())
    )
    print(json.dumps(result2, indent=2, ensure_ascii=False))


    print("\n=== 3. 날짜 없음 테스트 ===")
    result3 = build_weather_based_route_decision(
        city_name="Seoul",
        travel_date=None
    )
    print(json.dumps(result3, indent=2, ensure_ascii=False))

