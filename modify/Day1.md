**背景介绍 (给 Cursor 的上下文):**

"Cursor，你目前正在处理一个基于 LangGraph 的 Python 项目，名为 "Gemini-fullstack-langgraph-quickstart"。这个项目的目标是实现一个自动化的研究代理，能够根据用户问题进行网页搜索、反思并生成答案。我们有一个更宏伟的蓝图，名为 "DeepResearch"（源自一份设计文档，但你不需要知道文档的具体内容，我会指导你），它构想了一个更复杂、功能更全面的多代理研究系统。

我们现在的任务是，**分阶段地**将 "DeepResearch" 的核心思想和功能，以 LangGraph 的 Node 和 Edge 的形式，逐步整合到现有的 "pro-search-agent" 项目中。我们不会一次性实现所有高级功能，而是采取迭代的方式，确保每一步完成后，项目都是可运行且功能得到有效增强的。

**当前阶段目标：引入显式规划与任务化研究流程**

本阶段的核心目标是：

1.  **引入一个显式的规划节点 (`planner_node`)**：取代或增强现有的 `generate_query`，使其能够根据用户问题生成一个结构化的多步骤研究计划 (`plan`)。
2.  **改造现有流程以支持按计划执行**：让后续的查询生成和网页搜索都围绕这个 `plan` 中的任务展开。
3.  **初步的状态扩展**：在 `OverallState` 中加入存储 `plan` 和当前任务指针的字段。

**思考与实施方向 (给 Cursor 的指导):**

1.  **状态 (State) 设计先行**：
    * 你需要修改 `agent/state.py` 中的 `OverallState` `TypedDict`。
    * **新增字段**：
        * `user_query: str`：用于存储用户最原始的问题。
        * `plan: Optional[List[Dict[str, Any]]]`：用于存储由 `planner_node` 生成的任务计划列表。每个任务可以是一个字典，至少包含 `id: str` 和 `description: str`。初期可以简化，后续再丰富任务结构（如 `info_needed`, `source_hint` 等）。
        * `current_task_pointer: int`：初始化为 0，用于指向 `plan` 中当前待执行的任务。
    * 思考：这些新字段如何与现有字段（如 `messages`）协同？`messages` 可以继续存储完整的对话历史，而 `user_query` 则聚焦于本次研究的核心问题。

2.  **创建 `planner_node`**：
    * 在 `agent/nodes.py` (或其他你组织节点的文件中) 创建一个新的函数 `planner_node(state: OverallState, config: RunnableConfig) -> Dict[str, Any]:`。
    * **功能**：
        * 接收 `state["user_query"]` (或从 `state["messages"]` 中提取)。
        * 利用 LLM (可以复用 `generate_query` 中的 `ChatGoogleGenerativeAI` 初始化逻辑) 和一个新的提示词 (参考 `query_writer_instructions` 的结构，但目标是生成多步骤计划，而不是直接的搜索查询) 来生成研究计划。
        * **提示词设计**：你的提示词应该引导 LLM 将用户问题分解为2-3个逻辑子任务/研究步骤，并为每个步骤生成一个简短的描述。LLM 的输出最好是结构化的，比如一个 JSON 列表，每个对象包含任务 `id` 和 `description`。
        * **结构化输出 (可选但推荐)**：可以定义一个新的 Pydantic 模型 (类似 `SearchQueryList`) 来规范 LLM 输出的计划结构，例如：
            ```python
            from pydantic import BaseModel, Field
            from typing import List

            class ResearchTask(BaseModel):
                id: str = Field(description="Unique identifier for the task.")
                description: str = Field(description="A concise description of what this research task aims to achieve.")
                # 未来可以添加: keywords: List[str], source_types: List[str] 等

            class ResearchPlan(BaseModel):
                tasks: List[ResearchTask] = Field(description="A list of research tasks to be executed.")
            ```
            然后使用 `llm.with_structured_output(ResearchPlan)`。
        * **返回值**：返回一个字典，如 `{"plan": llm_result.tasks, "current_task_pointer": 0}`。
    * 思考：这个节点如何替代或补充 `generate_query`？初期，`planner_node` 可以作为 `generate_query` 之前的步骤。

3.  **修改 `generate_query` 节点**：
    * **功能调整**：它不再直接基于 `state["messages"]` (或 `user_query`) 生成查询。而是读取 `state["plan"][state["current_task_pointer"]].description` (即当前计划任务的描述)，并基于这个描述来生成具体的搜索查询列表 (`query_list`)。
    * **输入依赖**：明确依赖 `state["plan"]` 和 `state["current_task_pointer"]`。
    * **返回值**：保持不变，仍然是 `{"query_list": result.query}`。
    * 思考：如果 `plan` 为空或 `current_task_pointer` 越界，应该如何处理？（初期可以假设 `planner_node` 总能成功生成计划）。

4.  **调整图 (Graph) 的边 (Edges)**：
    * 在 `agent_graph.py` (或主流程定义文件) 中：
        * 将 `START` 节点连接到新的 `planner_node`。
        * `planner_node` 完成后，连接到 `generate_query` 节点。
        * `generate_query` 之后的流程 (`continue_to_web_research` -> `web_research` -> `reflection` -> `evaluate_research`) **暂时保持不变**，它们现在是针对 `plan` 中的单个任务执行的。
    * **引入循环的思考 (为下一阶段做准备，本阶段不完全实现)**：目前，我们只处理 `plan` 中的第一个任务。你需要开始思考，当一个任务（包括其搜索、反思）完成后，如何让流程回到 `generate_query` 来处理 `plan` 中的下一个任务 (`current_task_pointer + 1`)，直到所有任务完成，才进入 `finalize_answer`。这通常涉及到在 `evaluate_research` 或其后的某个地方添加条件逻辑。
        * **本阶段简化**：可以先硬编码只执行 `plan` 中的第一个任务。或者，在 `evaluate_research` 返回 "finalize_answer" 之前，简单地打印出 "所有任务已处理完毕" (如果 `current_task_pointer` 已到达 `plan` 的末尾)。

**代码参考 (片段，用于启发 Cursor):**

**1. `agent/state.py` (修改 `OverallState`)**
```python
# ... 其他导入 ...
from typing import List, Dict, Any, Optional # 确保这些已导入

class OverallState(TypedDict):
    messages: Annotated[list, add_messages]
    # --- 新增字段 ---
    user_query: Optional[str] # 或者 str，取决于初始化逻辑
    plan: Optional[List[Dict[str, Any]]] # 或者更具体的 Task 类型
    current_task_pointer: Optional[int] # 或者 int
    # --- 现有字段 ---
    query_list: Optional[List[str]] # 注意: generate_query 的输出是 query_list，不是 search_query
    web_research_result: Annotated[list, operator.add]
    sources_gathered: Annotated[list, operator.add]
    initial_search_query_count: Optional[int] # 注意: 你的 generate_query 用了这个
    max_research_loops: Optional[int] # 你的 evaluate_research 用了这个
    research_loop_count: Optional[int] # 你的 reflection 和 evaluate_research 用了这个
    reasoning_model: Optional[str] # 你的 reflection 和 finalize_answer 用了这个
    # 以下字段由 reflection 节点产生，并被 evaluate_research 使用
    is_sufficient: Optional[bool]
    knowledge_gap: Optional[str]
    follow_up_queries: Optional[List[str]]
    number_of_ran_queries: Optional[int]
    # search_query: Annotated[list, operator.add] # 你的 web_research 返回了这个
    # 检查一下字段名称是否一致，例如 web_research 返回的是 "search_query": [state["search_query"]]
    # 而 generate_query 返回的是 "query_list". OverallState 中最好统一或分别定义。
    # 假设我们保留 executed_search_queries 来累积所有实际执行的搜索
    executed_search_queries: Annotated[List[str], operator.add]

```
*Cursor 请注意：仔细检查现有代码中所有被读取和写入 `OverallState` 的键，确保它们在新/旧定义中都得到妥善处理。例如，`generate_query` 原来设置 `initial_search_query_count`，并且返回 `query_list`。`web_research` 返回 `search_query` (作为列表项), `sources_gathered`, `web_research_result`。`reflection` 返回 `is_sufficient`, `knowledge_gap`, `follow_up_queries`, `research_loop_count`, `number_of_ran_queries`。确保 `OverallState` 包含所有这些。*

**2. `agent/tools_and_schemas.py` (新增 Pydantic 模型 - 可选)**
```python
from pydantic import BaseModel, Field
from typing import List

class ResearchTask(BaseModel):
    id: str = Field(description="Unique identifier for the task, e.g., 'task-1'.")
    description: str = Field(description="A concise description of what this research task aims to achieve.")
    # Optional: Add keywords or source_hints if your planner LLM can generate them
    # keywords: List[str] = Field(default_factory=list, description="Keywords relevant to this task.")

class ResearchPlan(BaseModel):
    tasks: List[ResearchTask] = Field(description="A list of research tasks to be executed.")

# ... 现有 SearchQueryList, Reflection ...
```

**3. `planner_node` 实现思路 (新节点)**
```python
# (在你的节点定义文件中)
from agent.tools_and_schemas import ResearchPlan # 如果使用 Pydantic
# ... 其他导入 ...

def planner_node(state: OverallState, config: RunnableConfig) -> Dict[str, Any]:
    configurable = Configuration.from_runnable_config(config)
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model, # 或专门的 planner_model
        temperature=0.7, # 规划可能需要一些创造性但也要结构化
        # ... 其他 LLM 配置 ...
    )
    # structured_llm = llm.with_structured_output(ResearchPlan) # 如果使用 Pydantic

    # 设计新的提示词，引导 LLM 将 state["user_query"] 分解为步骤
    # planner_prompt_template = """User Query: {user_query}
    # Based on the user query, create a multi-step research plan.
    # Each step should be a clear, actionable task.
    # Output a JSON objecttroops with a key "tasks", where "tasks" is a list of objects,
    # each with an "id" (e.g., "task-1", "task-2") and "description".
    # Example:
    # User Query: "What are the impacts of AI on climate change?"
    # {{
    #   "tasks": [
    #     {{"id": "task-1", "description": "Research positive impacts of AI on climate change mitigation."}},
    #     {{"id": "task-2", "description": "Research negative impacts or risks of AI related to climate change (e.g., energy consumption)."}},
    #     {{"id": "task-3", "description": "Summarize findings and identify key areas of ongoing debate or future research."}}
    #   ]
    # }}
    # User Query: {user_query}
    # Research Plan:
    # """ # 这是一个非常简化的提示词示例，你需要优化它

    # user_query = state.get("user_query") or get_research_topic(state["messages"]) # 获取用户查询
    # formatted_prompt = planner_prompt_template.format(user_query=user_query)

    # response = structured_llm.invoke(formatted_prompt) # response 会是 ResearchPlan 实例
    # plan_for_state = [{"id": task.id, "description": task.description} for task in response.tasks]

    # ---- 如果不立即使用 Pydantic，可以先让 LLM 返回简单 JSON 字符串，然后解析 ----
    planner_prompt_template = f"""
    User Query: {state['user_query']}
    Based on the user query, create a multi-step research plan.
    Each step should be a clear, actionable task.
    Output a JSON list of objects, where each object has an "id" (e.g., "task-1", "task-2") and "description".
    Example:
    [
        {{"id": "task-1", "description": "Research positive impacts of AI on climate change mitigation."}},
        {{"id": "task-2", "description": "Research negative impacts or risks of AI related to climate change (e.g., energy consumption)."}}
    ]

    Your JSON research plan:
    """ # 确保 LLM 严格按此格式输出
    raw_response = llm.invoke(planner_prompt_template)
    # 在这里你需要健壮地解析 raw_response.content (它可能是字符串形式的 JSON)
    import json
    try:
        parsed_plan = json.loads(raw_response.content)
        if not isinstance(parsed_plan, list) or not all(isinstance(item, dict) and "id" in item and "description" in item for item in parsed_plan):
            raise ValueError("LLM did not return a valid plan structure.")
        plan_for_state = parsed_plan
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing plan from LLM: {e}")
        # 兜底策略：可以生成一个默认的单步计划或返回错误
        plan_for_state = [{"id": "task-default", "description": state['user_query']}]


    return {"plan": plan_for_state, "current_task_pointer": 0}
```

**4. `generate_query` 修改思路**
```python
# (在你的节点定义文件中)
def generate_query(state: OverallState, config: RunnableConfig) -> Dict[str, Any]: # 返回类型 QueryGenerationState 只是个提示，实际返回 Dict
    # ... (LLM 初始化等不变) ...
    plan = state.get("plan")
    pointer = state.get("current_task_pointer")

    if not plan or pointer is None or pointer >= len(plan):
        # 处理计划为空或指针越界的情况，例如返回空查询列表或抛出错误
        # 或者，如果 plan 就是空，可以直接基于 user_query 生成查询作为回退
        research_topic_description = state.get("user_query") or get_research_topic(state["messages"])
        if not research_topic_description:
             return {"query_list": []} # 或者其他错误处理
    else:
        current_task = plan[pointer]
        research_topic_description = current_task["description"]

    # ... (复用现有 query_writer_instructions 和 LLM 调用逻辑) ...
    # 注意：query_writer_instructions 的 {research_topic} 现在应该用 research_topic_description 填充
    # {number_queries} 仍可从 state["initial_search_query_count"] 获取

    formatted_prompt = query_writer_instructions.format(
        current_date=get_current_date(),
        research_topic=research_topic_description, # 使用当前任务的描述
        number_queries=state.get("initial_search_query_count", configurable.number_of_initial_queries), # 确保有默认值
    )
    result = structured_llm.invoke(formatted_prompt) # structured_llm 是 generate_query 中原有的
    # 返回的字典中，key 应该与 OverallState 中定义的字段对应
    # 如果 OverallState 中用的是 query_list，这里就用 query_list
    return {"query_list": result.query} # 假设 SearchQueryList 有 .query 属性
```

**5. 图的边调整思路**
```python
# (在你的图定义文件中)
# builder = StateGraph(OverallState, ...)

# --- 新增 planner_node ---
# builder.add_node("planner", planner_node) # "planner" 是节点名
# builder.add_node("generate_query", generate_query)
# ... 其他节点定义 ...

# builder.add_edge(START, "planner")
# builder.add_edge("planner", "generate_query")
# generate_query -> continue_to_web_research (条件边) 保持不变
# ... 其他边定义 ...

# --- 对于循环 (为下一阶段准备，本阶段可选简化实现) ---
# 你可能需要一个新的条件边函数，在 reflection 完成后决定是：
# A) 结束当前任务，递增 pointer，然后检查 plan 是否完成。若未完成，回到 generate_query (或 planner 前的某个分发节点)。
# B) 如果 reflection 产生了 follow_up_queries，则先处理这些 (Send 到 web_research)。
# C) 如果 plan 完成，则到 finalize_answer。

# 简化版：可以先让流程在处理完第一个任务后直接到 finalize_answer，
# 或者在 evaluate_research 中添加一个简单的判断：
# if state["current_task_pointer"] >= len(state["plan"]) -1:
#     # 所有任务已处理 (或这是最后一个任务且已充分)
#     return "finalize_answer"
# else:
#     # 准备处理下一个任务 (这里简化，实际需要更新 pointer 并回到 generate_query)
#     # 本阶段可以直接 return "finalize_answer" 或一个特殊的结束信号
#     # 或者，更简单的方式是，先不修改 evaluate_research，让它完成单个任务后就尝试 finalize。
#     # 重点是先把 planner -> generate_query -> web_research (for one task) 跑通。
```

Cursor，请专注于以上改动。确保在修改 `OverallState` 时考虑到所有现有节点对其的读写，避免引入 `KeyError`。提示词工程（尤其是 `planner_node` 的）将是关键。先让基于计划的单个任务流程能跑通，我们下一阶段再完善多任务循环和更复杂的推理逻辑。祝编码顺利！"