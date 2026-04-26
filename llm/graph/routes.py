from llm.graph.contracts import StateKeys
from llm.graph.state import TravelAgentState


def _has_place_context(state: TravelAgentState) -> bool:
    selected_places = state.get(StateKeys.SELECTED_PLACES, [])
    mapped_places = state.get(StateKeys.MAPPED_PLACES, [])
    return bool(selected_places or mapped_places)


def should_continue(state: TravelAgentState):
    route = state.get(StateKeys.ROUTE, "chat")

    if route == "weather":
        return "weather_node"

    if route in ["place", "travel"]:
        return "place_node"

    if route == "schedule":
        if not _has_place_context(state):
            return "place_node"
        return "scheduler_node"

    if route == "modify":
        return "modify_node"

    return "response_node"


def route_after_missing_check(state: TravelAgentState):
    route = state.get(StateKeys.ROUTE, "chat")
    destination = state.get(StateKeys.DESTINATION)

    if route == "chat":
        return "response_node"

    print("[DEBUG] route_after_missing_check destination =", destination)

    if not destination:
        return "ask_user_node"

    return should_continue(state)


def route_after_safety_check(state: TravelAgentState):
    if state.get(StateKeys.BLOCKED, False):
        return "blocked_response_node"
    return "summary_node"


def route_after_intent_node(state: TravelAgentState):
    print("[DEBUG] [start] route_after_intent_node")
    print(state)
    print("[DEBUG] [end]")
    return state["route"]


def route_after_weather_node(state: TravelAgentState) -> str:
    """
    weather_node 실행 후 다음 노드를 결정한다.

    - weather_only: 날씨만 답변하면 되므로 response_node로 이동
    - trip_plan / travel / place_only 등: 날씨 정보를 반영해서 장소 검색으로 이동
    """

    intent = state.get("intent")
    route = state.get("route")

    # 날씨만 묻는 요청
    if intent == "weather_only" or route == "weather":
        return "response_node"

    # 여행 일정 생성 요청은 날씨 조회 후 장소 검색으로 진행
    if intent in ["trip_plan", "travel_recommendation", "place_search"] or route in [
        "travel",
        "place",
    ]:
        return "place_node"

    # 애매한 경우에는 안전하게 최종 응답 생성
    return "response_node"


def route_after_place_search_node(state):
    """
    place_search_node 실행 후 다음 노드를 결정한다.

    - place_only: 장소만 답변하면 되므로 response_node로 이동
    """
    intent = state.get("intent")
    route = state.get("route")

    if intent == "place_only" or route == "place":
        return "response_node"

    # place_only가 아닌 경우 장소 선정 노드로 이동
    return "select_places_node"