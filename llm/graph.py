"""
에이전트의 전체 실행 그래프를 정의하는 파일.

각 노드와 엣지의 연결 관계를 구성하여,
LLM 호출, tool 실행, 상태 전이를 하나의 흐름으로 관리한다.
에이전트의 동작 순서와 분기 구조를 담당한다.
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from llm.prompts import SYSTEM_PROMPT
from llm.tools import TOOLS

from openai import OpenAI
from config import Settings


def build_trip_agent():
    llm = init_chat_model(
        model="gpt-4.1-mini",
        temperature=0
    )

    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
    return agent

def get_openai_clients(settings: Settings | None = None) -> OpenAI:
    s = settings or Settings()
    return OpenAI(api_key=s.openai_api_key)