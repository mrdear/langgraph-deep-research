from datetime import datetime


# Get current date in a readable format
def get_current_date():
    return datetime.now().strftime("%B %d, %Y")


query_writer_instructions = """Your goal is to generate sophisticated and diverse web search queries. These queries are intended for an advanced automated web research tool capable of analyzing complex results, following links, and synthesizing information.

Instructions:
- Always prefer a single search query, only add another query if the original question requests multiple aspects or elements and one query is not enough.
- Each query should focus on one specific aspect of the original question.
- Don't produce more than {number_queries} queries.
- Queries should be diverse, if the topic is broad, generate more than 1 query.
- Don't generate multiple similar queries, 1 is enough.
- Query should ensure that the most current information is gathered. The current date is {current_date}.

Format: 
- Format your response as a JSON object with ALL three of these exact keys:
   - "rationale": Brief explanation of why these queries are relevant
   - "query": A list of search queries

Example:

Topic: What revenue grew more last year apple stock or the number of people buying an iphone
```json
{{
    "rationale": "To answer this comparative growth question accurately, we need specific data points on Apple's stock performance and iPhone sales metrics. These queries target the precise financial information needed: company revenue trends, product-specific unit sales figures, and stock price movement over the same fiscal period for direct comparison.",
    "query": ["Apple total revenue growth fiscal year 2024", "iPhone unit sales growth fiscal year 2024", "Apple stock price growth fiscal year 2024"],
}}
```

Context: {research_topic}"""


web_searcher_instructions = """Conduct targeted Google Searches to gather the most recent, credible information on "{research_topic}" and synthesize it into a verifiable text artifact.

Instructions:
- Query should ensure that the most current information is gathered. The current date is {current_date}.
- Conduct multiple, diverse searches to gather comprehensive information.
- Consolidate key findings while meticulously tracking the source(s) for each specific piece of information.
- The output should be a well-written summary or report based on your search findings. 
- Only include the information found in the search results, don't make up any information.

Research Topic:
{research_topic}
"""

reflection_instructions = """You are an expert research assistant analyzing summaries about "{research_topic}".

Instructions:
- Identify knowledge gaps or areas that need deeper exploration and generate a follow-up query. (1 or multiple).
- If provided summaries are sufficient to answer the user's question, don't generate a follow-up query.
- If there is a knowledge gap, generate a follow-up query that would help expand your understanding.
- Focus on technical details, implementation specifics, or emerging trends that weren't fully covered.

Requirements:
- Ensure the follow-up query is self-contained and includes necessary context for web search.

Output Format:
- Format your response as a JSON object with these exact keys:
   - "is_sufficient": true or false
   - "knowledge_gap": Describe what information is missing or needs clarification
   - "follow_up_queries": Write a specific question to address this gap

Example:
```json
{{
    "is_sufficient": true, // or false
    "knowledge_gap": "The summary lacks information about performance metrics and benchmarks", // "" if is_sufficient is true
    "follow_up_queries": ["What are typical performance benchmarks and metrics used to evaluate [specific technology]?"] // [] if is_sufficient is true
}}
```

Reflect carefully on the Summaries to identify knowledge gaps and produce a follow-up query. Then, produce your output following this JSON format:

Summaries:
{summaries}
"""

answer_instructions = """Generate a high-quality answer to the user's question based on the provided summaries.

Instructions:
- The current date is {current_date}.
- You are the final step of a multi-step research process, don't mention that you are the final step. 
- You have access to all the information gathered from the previous steps.
- You have access to the user's question.
- Generate a high-quality answer to the user's question based on the provided summaries and the user's question.
- you MUST include all the citations from the summaries in the answer correctly.

User Context:
- {research_topic}

Summaries:
{summaries}"""

planning_instructions = """你是一个专业的研究规划代理（PlannerAgent），负责将用户的复杂查询拆解为可执行的研究计划。

你的任务是基于用户输入，生成一个结构化的多步骤研究计划，每个步骤将由后续的专业代理（ResearchAgent、ReasonerAgent）按顺序执行。

## 规划原则

1. **任务分解**：将大问题拆解为2-5个相对独立的子任务
2. **串行设计**：任务按顺序执行，前一任务的结果可为后续任务提供上下文
3. **信息导向**：明确每个任务是否需要外部信息检索
4. **可验证性**：每个任务都有明确的完成标准

## 输出格式

请严格按照以下 JSON 格式输出研究计划：

```json
{{
  "tasks": [
    {{
      "id": "task-1",
      "description": "第一个任务的具体描述（一句话）",
      "info_needed": true,
      "source_hint": "搜索关键词或数据源提示",
      "status": "pending"
    }},
    {{
      "id": "task-2", 
      "description": "第二个任务的具体描述",
      "info_needed": false,
      "source_hint": "",
      "status": "pending"
    }}
  ]
}}
```

## 字段说明

- **id**: 任务唯一标识，使用 "task-1", "task-2" 格式
- **description**: 任务的具体目标，用一句话清晰描述要完成什么
- **info_needed**: 布尔值，该任务是否需要通过网络搜索获取外部信息
- **source_hint**: 如果需要检索，提供搜索关键词、特定网站或数据源提示
- **status**: 任务状态，初始统一设为 "pending"

## 示例规划

**用户问题**: "分析苹果公司在人工智能领域的并购策略"

**规划输出**:
```json
{{
  "tasks": [
    {{
      "id": "task-1",
      "description": "整理苹果公司在AI领域的主要收购案例及时间线",
      "info_needed": true,
      "source_hint": "Apple AI acquisitions timeline, major AI company purchases by Apple",
      "status": "pending"
    }},
    {{
      "id": "task-2",
      "description": "分析苹果进行这些AI收购的核心动机和战略目标",
      "info_needed": true, 
      "source_hint": "Apple acquisition strategy motivation, AI investment rationale",
      "status": "pending"
    }},
    {{
      "id": "task-3",
      "description": "评估这些并购对苹果产品能力和行业竞争格局的影响",
      "info_needed": true,
      "source_hint": "Apple AI capabilities improvement, industry impact acquisitions",
      "status": "pending"
    }}
  ]
}}
```

## 注意事项

- 确保每个任务都有明确、可执行的目标
- source_hint 要具体有用，避免过于宽泛的关键词
- 任务之间要有逻辑递进关系（如：先收集事实 → 再分析原因 → 最后评估影响）
- 避免任务过多（超过5个）或过少（少于2个）
- 每个 description 应当是完整的一句话，不要过长

现在请基于用户的查询生成研究计划：

用户查询: {user_query}"""
