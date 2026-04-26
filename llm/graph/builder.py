from langchain_openai import ChatOpenAI

from langgraph.graph import StateGraph, END

from llm.graph.state import TravelAgentState
from llm.graph.routes import (
    route_after_missing_check, 
    route_after_safety_check,
    route_after_intent_node,
    route_after_weather_node,
    route_after_place_search_node
)
from llm.nodes.intent_nodes import intent_node
from llm.nodes.trip_nodes import (
    extract_trip_requirements_node,
    check_missing_info_node,
    ask_user_for_missing_info_node,
    select_places_node,
    modify_trip_requirements_node,
)
from llm.nodes.weather_nodes import weather_node
from llm.nodes.response_nodes import build_response_node, blocked_response_node
from llm.nodes.place_node import place_node
from llm.nodes.place_search_node import place_search_node
from llm.nodes.schedule_nodes import scheduler_node
from llm.nodes.validate_node import validate_travel_plan_node, route_after_validation
from llm.nodes.safety_nodes import safe_input_node
from llm.nodes.summary_nodes import summary_node

# --------------------------------------------------
# 그래프 상태 머신 초기화
# --------------------------------------------------
workflow = StateGraph(TravelAgentState)


# --------------------------------------------------
# 공용 LLM 생성
# --------------------------------------------------
shared_llm = ChatOpenAI(model="gpt-4.1", temperature=1.0)

# LLM을 사용하는 intent node 인스턴스 생성
intent_node_instance = intent_node(shared_llm)


# --------------------------------------------------
# 노드 등록
# --------------------------------------------------
workflow.add_node("safe_input_node", safe_input_node)
workflow.add_node("blocked_response_node", blocked_response_node)
workflow.add_node("summary_node", summary_node)

workflow.add_node("intent_router", intent_node_instance)

workflow.add_node("extract_trip_requirements_node", extract_trip_requirements_node)
workflow.add_node("check_missing_info_node", check_missing_info_node)
workflow.add_node("ask_user_node", ask_user_for_missing_info_node)

workflow.add_node("weather_node", weather_node)

workflow.add_node("place_node", place_node)
workflow.add_node("place_search_node", place_search_node)
workflow.add_node("select_places_node", select_places_node)

workflow.add_node("scheduler_node", scheduler_node)
workflow.add_node("modify_node", modify_trip_requirements_node)
workflow.add_node("validate_node", validate_travel_plan_node)

workflow.add_node("response_node", build_response_node)


# --------------------------------------------------
# 시작 노드
# --------------------------------------------------
workflow.set_entry_point("safe_input_node")


# --------------------------------------------------
# 1. 안전성 검사
# blocked면 바로 차단 응답 후 종료
# safe면 summary_node로 이동
# --------------------------------------------------
workflow.add_conditional_edges(
    "safe_input_node",
    route_after_safety_check,
    {
        "blocked_response_node": "blocked_response_node",
        "summary_node": "summary_node",
    },
)

workflow.add_edge("blocked_response_node", END)


# --------------------------------------------------
# 2. 요약 / 대화 히스토리 정리 후 intent 분류
# --------------------------------------------------
workflow.add_edge("summary_node", "intent_router")


# --------------------------------------------------
# 3. intent에 따른 1차 분기
#
# 중요:
# - trip_plan 계열은 바로 place/scheduler로 보내지 말고
#   extract_trip_requirements_node로 보내야 함
# - weather_only는 weather_node로 바로 보낼 수 있음
# - 일반 대화는 response_node로 보냄
#
# route_after_intent_node 함수가 아래 key 중 하나를 반환해야 함:
# - extract_trip_requirements_node
# - weather_node
# - place_node
# - scheduler_node
# - modify_node
# - response_node
# --------------------------------------------------
workflow.add_conditional_edges(
    "intent_router",
    route_after_intent_node,
    {
        "extract_trip_requirements_node": "extract_trip_requirements_node",
        "weather_node": "weather_node",
        "place_node": "place_node",
        "scheduler_node": "scheduler_node",
        "modify_node": "modify_node",
        "response_node": "response_node",
        "ask_user_node": "ask_user_node",
    },
)


# --------------------------------------------------
# 4. 여행 조건 추출
# 예: 지역, 날짜, 여행 기간, 동행, 테마 등
# --------------------------------------------------
workflow.add_edge("extract_trip_requirements_node", "check_missing_info_node")


# --------------------------------------------------
# 5. 필수 정보 누락 검사
#
# 중요:
# 여행 일정 생성에서는 날짜/지역 등이 필수이므로,
# 정보가 부족하면 ask_user_node에서 질문하고 종료.
#
# 정보가 충분하면 무조건 weather_node로 이동하도록
# route_after_missing_check 쪽도 맞춰주는 것이 좋음.
#
# 권장 반환값:
# - ask_user_node: 필수 정보 부족
# - weather_node: 필수 정보 충분
# --------------------------------------------------
workflow.add_conditional_edges(
    "check_missing_info_node",
    route_after_missing_check,
    {
        "ask_user_node": "ask_user_node",
        "weather_node": "weather_node",
    },
)


# --------------------------------------------------
# 6. 누락 정보 질문은 해당 턴에서 종료
# 다음 사용자 응답이 들어오면 다시 safe_input_node부터 시작
# --------------------------------------------------
workflow.add_edge("ask_user_node", END)


# --------------------------------------------------
# 7. 날씨 조회 후 분기
#
# weather_only:
#   weather_node -> response_node -> END
#
# trip_plan:
#   weather_node -> place_node -> place_search_node ...
# --------------------------------------------------
workflow.add_conditional_edges(
    "weather_node",
    route_after_weather_node,
    {
        "response_node": "response_node",
        "place_node": "place_node",
    },
)


# --------------------------------------------------
# 8. 수정 요청 처리
#
# 기존 일정/조건을 수정한 뒤,
# 다시 장소 검색부터 진행
# 필요하면 modify_node 이후 weather_node로 보내도 됨.
# 현재는 수정된 조건으로 장소 재검색하는 구조.
# --------------------------------------------------
workflow.add_edge("modify_node", "place_node")


# --------------------------------------------------
# 9. 장소 검색
# --------------------------------------------------
workflow.add_edge("place_node", "place_search_node")

# --------------------------------------------------
# 10. 장소 검색 이후 분기
#
# place_only:
#   place_node
#   -> place_search_node
#   -> response_node
#   -> END
#
# trip_plan:
#   place_node
#   -> place_search_node
#   -> select_places_node
#   -> scheduler_node
#   -> validate_node
#   -> response_node
#   -> END
# --------------------------------------------------
workflow.add_conditional_edges(
    "place_search_node",
    route_after_place_search_node,
    {
        "response_node": "response_node",
        "select_places_node": "select_places_node",
    },
)


# --------------------------------------------------
# 11. 일정 생성 및 검증
# --------------------------------------------------
workflow.add_edge("select_places_node", "scheduler_node")
workflow.add_edge("scheduler_node", "validate_node")


# --------------------------------------------------
# 12. 검증 결과에 따른 재시도 또는 최종 응답
#
# - place_node: 장소가 부적절하면 장소 재검색
# - scheduler_node: 일정만 다시 짜면 되는 경우
# - response_node: 검증 통과 후 최종 응답
# --------------------------------------------------
workflow.add_conditional_edges(
    "validate_node",
    route_after_validation,
    {
        "place_node": "place_node",
        "scheduler_node": "scheduler_node",
        "response_node": "response_node",
    },
)


# --------------------------------------------------
# 13. 최종 응답 후 종료
# --------------------------------------------------
workflow.add_edge("response_node", END)


# --------------------------------------------------
# 그래프 컴파일
# --------------------------------------------------
app = workflow.compile()
