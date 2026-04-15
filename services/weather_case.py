import json
import requests
import openai
from config import Settings
from llm.prompts import SYSTEM_PROMPT
from datetime import date, datetime, timedelta


# -----------------------------
# 0. 설정
# -----------------------------
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


# -----------------------------
# 1. 현재 날씨 조회
# -----------------------------
def get_current_weather(city_name: str = "Seoul", units: str = "metric") -> str:
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
                "description": data.get("weather", [{}])[0].get("description"),
                "temperature": data.get("main", {}).get("temp"),
                "humidity": data.get("main", {}).get("humidity"),
                "wind_speed": data.get("wind", {}).get("speed"),
            }
        else:
            weather_info = {
                "status": "error",
                "message": data.get("message", "날씨 정보를 찾을 수 없습니다.")
            }

        return json.dumps(weather_info, ensure_ascii=False)

    except requests.RequestException as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)


tools_to_execute = {
    "get_current_weather": get_current_weather
}


# -----------------------------
# 2. 날짜 판별
# -----------------------------
def classify_trip_timing(travel_date: str | None = None) -> dict:
    if not travel_date:
        return {"status": "unknown_date", "message": "여행 날짜 없음"}

    try:
        target = datetime.strptime(travel_date, "%Y-%m-%d").date()
    except ValueError:
        return {"status": "invalid_date", "message": "날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)"}

    today = date.today()
    diff = (target - today).days

    if diff < 0:
        return {"status": "past_date", "message": "지난 날짜입니다."}
    elif diff <= 5:
        return {"status": "current_weather_available"}
    elif diff <= 30:
        return {"status": "forecast_maybe"}
    else:
        return {"status": "too_far"}


# -----------------------------
# 3. 날씨 판정
# -----------------------------
def classify_outdoor_condition(weather_data: dict) -> dict:
    temp = weather_data.get("temperature")
    humidity = weather_data.get("humidity")
    desc = (weather_data.get("description") or "").lower()

    if temp is None:
        return {"condition_level": "unknown", "route": "mixed"}

    if "비" in desc or "rain" in desc:
        return {"condition_level": "poor", "route": "indoor"}

    if temp <= 5 or temp >= 35:
        return {"condition_level": "poor", "route": "indoor"}

    if 18 <= temp <= 26 and 30 <= humidity <= 70:
        return {"condition_level": "good", "route": "outdoor"}

    return {"condition_level": "normal", "route": "mixed"}


# -----------------------------
# 4. 땃쥐 멘트
# -----------------------------
def get_ddatchwi_message(status: str) -> str:
    return {
        "too_far": "땃쥐가 곤란해해요… 너무 먼 미래라 날씨를 모르겠어요!",
        "poor": "땃쥐가 우산을 챙겼어요! 실내 추천!",
        "normal": "땃쥐가 고민 중이에요! 실내+야외 섞어요!",
        "good": "땃쥐 신남! 야외 가자!",
        "unknown": "땃쥐가 생각 중이에요..."
    }.get(status, "땃쥐 에러")


# -----------------------------
# 5. 최종 판단
# -----------------------------
def build_weather_based_route_decision(city_name: str, travel_date: str | None) -> dict:
    timing = classify_trip_timing(travel_date)

    if timing["status"] == "too_far":
        return {
            "status": "too_far",
            "message": get_ddatchwi_message("too_far"),
            "options": ["평균날씨", "월 기준", "다시입력"]
        }

    if timing["status"] == "unknown_date":
        return {
            "status": "need_date",
            "message": "땃쥐가 달력을 찾고 있어요! 여행 날짜를 알려주시면 더 정확하게 추천할 수 있어요."
        }

    if timing["status"] in ["invalid_date", "past_date"]:
        return timing

    weather_json = get_current_weather(city_name)
    weather = json.loads(weather_json)

    if weather.get("status") != "success":
        return weather

    cond = classify_outdoor_condition(weather)

    return {
        "status": "success",
        "weather": weather,
        "condition": cond,
        "message": get_ddatchwi_message(cond["condition_level"])
    }


# -----------------------------
# 6. LLM (Function Calling)
# -----------------------------
def run_conversation(user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    tools = [{
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_name": {"type": "string"}
                },
                "required": ["city_name"]
            }
        }
    }]

    res = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    msg = res.choices[0].message

    if msg.tool_calls:
        messages.append(msg)

        for call in msg.tool_calls:
            fn = call.function.name
            args = json.loads(call.function.arguments)
            result = tools_to_execute[fn](**args)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": fn,
                "content": result
            })

        res2 = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages
        )
        return res2.choices[0].message.content

    return msg.content


# -----------------------------
# 7. 날짜 계산 (상대 → 절대)
# -----------------------------
def resolve_travel_date(travel_date: str | None, relative_days: int | None) -> str | None:
    if travel_date:
        return travel_date

    if relative_days is not None:
        return (date.today() + timedelta(days=relative_days)).isoformat()

    return None


# -----------------------------
# 8. 날짜·도시 추출 (LLM)
# -----------------------------
def extract_trip_info_with_llm(user_prompt: str) -> dict:
    """사용자 입력에서 도시와 날짜 정보를 구조화해서 추출"""

    extraction_system_prompt = f"""
당신은 여행 정보 추출기입니다.
오늘 날짜는 {date.today().isoformat()} 입니다.

사용자 문장에서 아래 JSON 형식으로만 추출하세요.
설명 없이 JSON만 출력하세요.

규칙:
1. city_name은 가능하면 한국어 도시명으로 반환하세요. 예: 서울, 부산, 도쿄, 전주
2. 날짜가 YYYY-MM-DD처럼 명확하면 travel_date에 넣으세요.
3. '1주일 뒤', '3일 후', '내일', '모레'처럼 상대 날짜면 relative_days에 숫자로 넣으세요.
4. 날짜를 특정할 수 없으면 travel_date와 relative_days를 모두 null로 두세요.
5. "다음 주", "이번 여름", "가을쯤"처럼 애매하면 둘 다 null로 두세요.

출력 형식:
{{
  "city_name": "서울",
  "travel_date": null,
  "relative_days": null,
  "raw_date_text": null
}}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": extraction_system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    content = response.choices[0].message.content
    return json.loads(content)


# -----------------------------
# 9. 자연어 입력 → 최종 결과
# -----------------------------
def build_weather_route_from_user_prompt(user_prompt: str) -> dict:
    """사용자 자연어 입력을 받아 도시/날짜를 추출하고 최종 날씨 기반 추천 결과 반환"""

    extracted = extract_trip_info_with_llm(user_prompt)

    # 사용자에게 보여줄 도시명(한국어)
    display_city_name = extracted.get("city_name") or "서울"

    # API에 보낼 도시명(영어 표준명)
    api_city_name = normalize_city_name_for_weather(display_city_name)

    travel_date = resolve_travel_date(
        extracted.get("travel_date"),
        extracted.get("relative_days")
    )

    result = build_weather_based_route_decision(api_city_name, travel_date)

    # 화면 출력용 도시명 주입
    result["display_city_name"] = display_city_name

    return {
        "extracted": extracted,
        "display_city_name": display_city_name,
        "resolved_travel_date": travel_date,
        "result": result
    }


# -----------------------------
# 10. 결과 포맷
# -----------------------------
def format_weather_recommendation(result: dict) -> str:
    """build_weather_based_route_decision() 결과를 사람이 보기 좋은 문자열로 변환"""

    status = result.get("status")

    if status == "too_far":
        ddatchwi = result.get("message", "")
        options = result.get("options", [])
        option_text = "\n".join([f"- {opt}" for opt in options])
        return f"{ddatchwi}\n\n선택지:\n{option_text}"

    if status == "need_date":
        return result.get("message", "날짜를 알려주세요.")

    if status in ["invalid_date", "past_date", "error"]:
        return result.get("message", "오류가 발생했습니다.")

    if status == "success":
        weather = result.get("weather", {})
        message = result.get("message", "")
        display_city_name = result.get("display_city_name") or weather.get("city", "정보 없음")

        return (
            f"- 도시: {display_city_name}\n"
            f"- 설명: {weather.get('description', '정보 없음')}\n"
            f"- 온도: {weather.get('temperature', '정보 없음')}도\n"
            f"- 습도: {weather.get('humidity', '정보 없음')}%\n"
            f"- 바람: {weather.get('wind_speed', '정보 없음')}m/s\n"
            f"\n{message}"
        )

    return "결과를 표시할 수 없습니다."


# ==============================
# 테스트
# ==============================
if __name__ == "__main__":
    print("\n=== 먼 날짜 ===")
    print(format_weather_recommendation(
        build_weather_based_route_decision("Busan", "2027-05-20")
    ))

    print("\n=== 오늘 ===")
    print(format_weather_recommendation(
        build_weather_based_route_decision("Seoul", str(date.today()))
    ))

    print("\n=== 날짜 없음 ===")
    print(format_weather_recommendation(
        build_weather_based_route_decision("Seoul", None)
    ))

    print("\n=== 잘못된 날짜 ===")
    print(format_weather_recommendation(
        build_weather_based_route_decision("Seoul", "2026/05/20")
    ))

    print("\n=== 자연어 입력 ===")
    final_result = build_weather_route_from_user_prompt("전주로 1주일 뒤 여행 가는데 날씨 어때?")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))
    print("\n--- 최종 출력 ---")
    print(format_weather_recommendation(final_result["result"]))

    # print("\n=== LLM Function Calling 테스트 ===")
    # print(run_conversation("서울 날씨 어때?"))