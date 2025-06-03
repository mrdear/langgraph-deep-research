from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import add_messages
from typing_extensions import Annotated


import operator
from dataclasses import dataclass, field
from typing_extensions import Annotated


class OverallState(TypedDict):
    messages: Annotated[list, add_messages]
    user_query: str  # 新增，存储用户原始问题
    plan: list  # 新增，存储由 planner_node 生成的任务计划
    current_task_pointer: int  # 新增，指向当前 plan 的任务索引
    executed_search_queries: Annotated[list, operator.add]  # 原 search_query 字段重命名
    web_research_result: Annotated[list, operator.add]
    sources_gathered: Annotated[list, operator.add]
    initial_search_query_count: int
    max_research_loops: int
    research_loop_count: int
    reasoning_model: str


class ReflectionState(TypedDict):
    is_sufficient: bool
    knowledge_gap: str
    follow_up_queries: Annotated[list, operator.add]
    research_loop_count: int
    number_of_ran_queries: int


class Query(TypedDict):
    query: str
    rationale: str


class QueryGenerationState(TypedDict):
    query_list: list[Query]


class WebSearchState(TypedDict):
    search_query: str
    id: str


@dataclass(kw_only=True)
class SearchStateOutput:
    running_summary: str = field(default=None)  # Final report
