from llm.graph.state import TravelAgentState
from llm.graph.contracts import StateKeys
from utils.db_retrieval import get_integrated_search_results


def place_search_node(state: TravelAgentState) -> dict:
    """
    State에 저장된 목적지(destination), 스타일(styles), 제약사항(constraints)을 조합하여
    ChromaDB에서 적합한 장소를 검색합니다.
    """
    # 1. 검색 쿼리 조합 (분석된 정보들 활용)
    destination = state.get(StateKeys.DESTINATION, "")
    styles = ", ".join(state.get(StateKeys.STYLES, []))
    constraints = ", ".join(state.get(StateKeys.CONSTRAINTS, []))

    # 1. 스타일 키워드 우선순위 재정렬
    # 일반적인 키워드 리스트 (나머지는 구체적 키워드로 간주하여 앞으로 배치)
    generic_keywords = {"맛집", "식당", "카페", "디저트", "관광", "명소"}

    specific_styles = [s for s in styles if s not in generic_keywords]
    generic_styles = [s for s in styles if s in generic_keywords]

    # 구체적 키워드를 앞쪽에 배치하여 쿼리 가중치 유도
    reordered_styles = ", ".join(specific_styles + generic_styles)

    # 2. 검색 쿼리 조합 (예: "부산 서핑, 액티비티, 맛집 실내 위주")
    search_query = f"{destination} {reordered_styles} {constraints}".strip()

    # 쿼리가 비어 있는 경우
    if not search_query:
        return {
            StateKeys.MAPPED_PLACES: [],
        }

    print(f"[DEBUG] place_search_node query: {search_query}")

    # 2. Self-Querying 검색 실행
    # k값은 select_places_node가 선택할 수 있도록 여유 있게(10개 정도) 가져옵니다.
    raw_results = get_integrated_search_results(search_query, k=10)

    # 3. 결과 저장 (mapped_places에 리스트 형태로 저장)
    return {StateKeys.MAPPED_PLACES: raw_results}