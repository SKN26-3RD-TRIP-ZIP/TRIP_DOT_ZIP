from llm.graph.contracts import StateKeys
from llm.graph.state import TravelAgentState


def _has_place_context(state: TravelAgentState) -> bool:
    selected_places = state.get(StateKeys.SELECTED_PLACES, [])
    mapped_places = state.get(StateKeys.MAPPED_PLACES, [])
    return bool(selected_places or mapped_places)


def route_after_safety_check(state: TravelAgentState):
    if state.get(StateKeys.BLOCKED, False):
        return "blocked_response_node"
    return "summary_node"


def route_after_intent_node(state: TravelAgentState):
    """
    intent_router 이후 1차 분기

    중요:
    builder.py의 conditional edge key와 정확히 같은 문자열을 반환해야 한다.
    """

    route = state.get(StateKeys.ROUTE, "chat")

    # 전체 여행 일정 생성
    # -> 바로 place/scheduler로 가지 말고
    #    먼저 여행 조건 추출 노드로 보내야 함
    if route == "travel":
        return "extract_trip_requirements_node"

    # 날씨만 묻는 경우
    if route == "weather":
        return "weather_node"

    # 장소만 추천받는 경우
    if route == "place":
        return "place_node"

    # 일정만 요청하는 경우
    # 현재는 안정성을 위해 제외하거나,
    # 추후 place context 검증 후 활성화 권장
    if route == "schedule":
        return "response_node"

    # 일정 수정 요청
    if route == "modify":
        return "modify_node"

    # 일반 대화 / fallback
    return "response_node"


def route_after_missing_check(state: TravelAgentState):
    """
    여행 조건 추출 후 필수 정보 누락 여부를 확인한다.

    현재 builder.py에서는
    check_missing_info_node 이후 허용 key가
    - ask_user_node
    - weather_node
    두 개뿐이므로, 여기서도 그 둘만 반환해야 안전하다.
    """

    route = state.get(StateKeys.ROUTE, "chat")
    destination = state.get(StateKeys.DESTINATION)

    if route == "chat":
        return "response_node"

    print("[DEBUG] route_after_missing_check destination =", destination)

    # 목적지가 없으면 사용자에게 다시 질문
    if not destination:
        return "ask_user_node"

    # 목적지가 있으면 trip_plan 흐름에서는 무조건 날씨 조회로 이동
    return "weather_node"


def route_after_weather_node(state: TravelAgentState) -> str:
    """
    weather_node 실행 후 다음 노드를 결정한다.

    - weather_only: 날씨만 답변하면 되므로 response_node로 이동
    - trip_plan / place_only: 날씨 반영 후 장소 검색으로 이동
    """

    intent = state.get("intent")
    route = state.get("route")

    if intent == "weather_only" or route == "weather":
        return "response_node"

    if intent in ["trip_plan", "travel_recommendation", "place_search"] or route in [
        "travel",
        "place",
    ]:
        return "place_node"

    return "response_node"


def route_after_place_search_node(state):
    """
    place_search_node 실행 후 다음 노드를 결정한다.

    - place_only: 장소 추천만 응답하고 종료
    - trip_plan: 장소 선택 단계로 이동
    """

    intent = state.get("intent")
    route = state.get("route")

    if intent == "place_only" or route == "place":
        return "response_node"

    return "select_places_node"