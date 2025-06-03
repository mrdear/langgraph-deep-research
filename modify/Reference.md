# LangGraph多代理架构：从规划到内容合成全流程解析

```
从 Gemini 的 DeepResearch 为目标

1 | 入口：用户提示 & 作用域设定
任何 Deep Research 会话都从 自然语言提示（prompt）或上传的参考文件开始。
系统首先利用 2.5 Pro 的长上下文（1 M tokens）对输入做 主题澄清与范围推断，为后续规划提供语义框架。

2 | Planning：自动拆题与研究蓝图
Planner Agent 把问题拆解成「可执行子任务」并生成一个 multi-point research plan，随后把草案展示给用户；用户可增删修改，再点击 Run 批准。
规划准则：子任务应可并行时并行、需串行时保持顺序，并标注检索深度与预期证据类型（新闻、专利、学术等）。

3 | Searching / Browsing：大规模检索
Web Agent 依据蓝图调度 Google Search 与自建爬虫，最多一次浏览 “数百” 个网页。
过程中会动态 去重、质量评估与时间排序，确保抓到最近且权威的材料。
检索结果会流式写入共享状态（见下面的异步任务管理器）。

4 | Reasoning Loop：迭代推理与笔记
Think Panel 向用户实时暴露模型的链式推理：“已学到什么→下一步打算做什么”。
每完成一批检索，模型将摘要写入长上下文，并判断是否还需继续挖掘（缺口分析）。
依托 1 M-token context + RAG 缓冲区，模型能“记住”整个会话的笔记和来源，支持跨页追问。

5 | Reporting：多轮合成 & 自审
触发条件：系统判定已满足「信息充分」。
Synthesis Agent 多轮生成报告 → Critique Agent 自审→ 重写 → 最终版。
输出形式
章节化文档（Executive Summary + 目录 + 引用链接）。
可一键导出到 Docs 或在 Canvas 继续互动（加测验、交互组件）。
```

1. 架构总览与数据流
LangGraph多代理系统采用计划-执行-综合的流水线架构，将复杂任务拆解给不同职责的智能体串行处理。整个流程包括5个核心角色，每个角色分工明确、专注于特定阶段。各阶段严格顺序执行，不并行交叉，只有ResearchAgent内部针对多网页抓取时采用I/O并发以提升效率。这样的多代理分工方式充分利用LLM的推理、检索和生成能力，通过模块化协作提高性能和可靠性。
核心角色及职责如下：
- Planner（规划代理）：解析用户复杂查询或任务需求，产出一份有序的步骤清单（plan）。Planner 调用LLM根据用户输入生成JSON格式的任务列表，包括每步要做什么、需要哪些信息等。它相当于侦探制定调查计划，将大问题分解为若干可执行的子任务。输出的plan确定了后续执行的路线图。
- Supervisor（宏观监督者）：全局控制流程的调度代理。它顺序读取Planner生成的plan，逐步推进pointer指向的当前步骤。Supervisor负责根据当前步骤类型调用相应子代理（ResearchAgent或ReasonerAgent），协调它们的产出，并更新全局状态。它确保只有当当前步骤完成（或追加的后续步骤完成）后才进入下一步，最终在全部步骤完成后调度SynthesizerAgent进入内容生成阶段。
- ResearchAgent（检索代理）：面向需要外部信息支撑的步骤执行网络检索和数据抓取。ResearchAgent利用并行搜索和异步网页抓取来获取相关资料，是流程中唯一进行I/O并发的环节。它将检索到的内容存入向量索引和章节资料桶，并产出提炼的要点笔记（ledger条目）供后续推理和撰写使用。
- ReasonerAgent（推理代理）：对ResearchAgent获取的资料进行分析综合的代理。它读取当前步骤的新ledger条目，运用LLM对信息进行**“Map-Reduce”**式整合——逐条分析要点并归纳总结为章节摘要或结论，判断是否已充分解决该步骤需求。如发现信息不足，ReasonerAgent会生成补充任务建议，由Supervisor插入plan执行；如果满足要求，则标记当前任务完成，并将精炼结论写入全局memory以供后续步骤引用。在执行过程中，它也会将分析思路和关键结论推送到“思考面板”（Think Panel）供开发者或用户审阅。
- SynthesizerAgent（综合写作代理）：负责最终的内容合成输出。SynthesizerAgent读取整理后的资料（各章节要点摘要、全局memory等），调用LLM以流式方式逐章撰写完整的技术文档。在生成过程中，它会根据需要查询向量索引获取细节佐证，插入引用标注原始来源。SynthesizerAgent注重生成符合格式要求的Markdown内容，包括章节标题、列表、表格、代码块等，以及章节间的衔接和整体总结，最终输出一篇结构完善、引文清晰的完整文档。
下面的时序图展示了上述各代理的调度与数据流（其中ResearchAgent内部的网页抓取使用了异步并发）：
sequenceDiagram
    participant U as User
    participant P as Planner
    participant S as Supervisor
    participant R as ResearchAgent
    participant T as ReasonerAgent
    participant Y as SynthesizerAgent
    Note over R: 内部并行<br/>抓取网页
    U->>P: 提交查询或任务请求
    P->>S: 生成任务清单 plan（JSON）
    S->>S: pointer = 0（初始化）
    loop 遍历 plan 步骤 (pointer 顺序递增)
        alt 当前步骤需要外部信息 (info_needed = true)
            S->>R: 执行检索获取资料
            par 并发搜索与抓取
                R->>R: 批量搜索多个查询
                R-->>R: 异步抓取各网页内容
            end
            R->>S: 返回资料要点 (ledger 摘要)
        end
        S->>T: 分析资料完成当前任务
        T->>T: Map-Reduce 整合要点结论
        T->>S: 若信息不足则建议追加后续任务
        alt 产生了补充任务
            S->>S: 将新任务插入 plan (pointer 不变)
        else 完成当前任务
            S->>S: 标记当前任务完成，pointer += 1
        end
    end
    S->>Y: 所有任务完成，调度内容合成
    Y->>Y: 逐章组装 Markdown 文档
    Y->>U: 输出最终完整报告
[图片]

上述流程中，各代理通过共享的GraphState传递数据：Planner写入plan清单，Supervisor根据pointer调用ResearchAgent填充ledger和chapter_bucket，ReasonerAgent更新memory，最终SynthesizerAgent综合所有内容生成报告。整个架构采用中心监督式模式，由Supervisor充当单一控制中枢顺序调度各专能代理，避免了多头决策的复杂性。同时，通过ResearchAgent的异步I/O能力，既保证了任务执行的串行有序，又最大程度提高了外部数据获取阶段的并发效率。
2. 全局GraphState设计
该章节的基础只是来自langgraph 的GraphState,需要先了解概念。 A shared data structure that represents the current snapshot of your application. It can be any Python type, but is typically a TypedDict or Pydantic BaseModel.
https://langchain-ai.github.io/langgraph/concepts/low_level/
多代理协作依赖一个全局GraphState来共享状态和数据。GraphState可以理解为包含整个工作流上下文的字典结构（例如Python的TypedDict），所有代理在执行时都读写其中的字段。下面定义了GraphState中的主要字段及含义（括号中注明类型），并说明其产生和消费方式：
- plan (List[Task])：由Planner产出的任务计划列表。每个Task为一个字典对象，包含该步骤的id、description、info_needed、source_hint、status等信息。计划生成后写入GraphState.plan，Supervisor逐步读取并调度执行。运行过程中如果ReasonerAgent提出新任务，Supervisor会将其以Task形式插入此列表。SynthesizerAgent最终也会遍历plan用于组织章节结构。
- pointer (int)：当前正在执行的plan列表索引，由Supervisor维护。初始化为0（指向第一个任务），每当一个任务完成且无补充任务时，pointer加一指向下一个任务。若ReasonerAgent要求追加新任务，可能在当前位置插入任务后，pointer暂不递增，以便先执行新插入的任务。Pointer确保任务串行执行，直到遍历完plan或显式跳出。
- ledger (List[LedgerEntry])：知识记事本，用于存储每个已完成任务的关键信息摘要。ResearchAgent在完成检索后，将该步骤的主要发现提炼成约5条bullet要点，作为一条ledger记录追加到此列表中。每个LedgerEntry通常包含一个step_id标识关联的任务，以及该任务相关的要点列表（每条要点约300 token的摘要）和引用映射。ReasonerAgent读取最新ledger条目进行分析，并在任务完成后可能更新该条目状态（例如标记已验证）。SynthesizerAgent稍后会利用ledger中的要点作为撰写段落的依据和引用提示。
- chapter_bucket (Dict[int, List[Snippet]])：章节资料桶，按任务/章节划分存储原始资料片段的结构。ResearchAgent检索完成后，将与当前步骤高度相关的内容片段（如摘录的段落、数据等）存入该bucket，并与步骤id关联。可以将其理解为每个章节一个临时资料库，通常截取最多40条左右精炼片段（mini chunks）。这些片段用于SynthesizerAgent撰写时引用具体细节（如直接引用一句话或数据），避免LLM遗漏重要信息。Chapter_bucket也方便开发者调试时查看某章用到了哪些来源。
- vector_index (VectorStore)：全局向量索引，用于存储所有获取的全文内容块及其向量表示。ResearchAgent抓取网页后，将其正文按一定长度切分为若干片段（如每块几百tokens），通过Embedding模型将每块向量化并存入vector_index。这提供了一个可供语义查询的知识库：SynthesizerAgent在写作时可以对某段内容或概念向量检索，快速找到相关原文片段以核实细节或提取引文。Vector_index由ResearchAgent写入，SynthesizerAgent通过检索工具读取，其容量不限但每块内容大小受模型上下文限制。
- memory (str)：全局工作记忆，用于逐步累积整篇文档的核心结论或背景摘要。ReasonerAgent在每个任务完成后，将该任务的重要结论融入到memory中，可以采用将旧memory和新ledger要点一起输入LLM再压缩总结的方式更新（即对全局信息进行Reduce整合）。Memory旨在在不超出上下文长度的前提下，保存全局摘要（全局reduce）信息，供后续任务及最终写作时提供上下文。随着任务增多，memory可能会裁剪早期不再需要的细节，只保留对后续有用的信息，从而控制长度。例如，memory可能是一段数百字的文本，概括了前面所有章节已发现的要点，后面的SynthesizerAgent或ReasonerAgent可以将其作为额外提示，确保章节之间内容一致、有引用。
- draft_summary (Dict[int, str])：章节摘要草稿，为每个章节任务准备的凝练小结。ReasonerAgent在任务完成时，除了写入ledger要点外，还会生成该章节更连贯的自然语言总结（相比bullet要点更像一段话），存入draft_summary对应章节的条目。每条章节摘要可能约100~200 tokens，高度概括了该章节应包含的内容。这个摘要草稿用于SynthesizerAgent撰写时作为提示，使模型更好地按照既定思路撰写段落。Draft_summary基本上是对ledger要点的进一步串联和润色，保证生成的章节内容连贯流畅。若某章节无需外部信息（info_needed=false），ReasonerAgent也可以直接将已有信息组织成简短摘要存入。
- user_files (List[Document])：用户提供的文件或文本列表。用户在提问时可能附加了一些参考资料（PDF、DOCX、网页等），这些会在流程开始时被载入GraphState.user_files。例如在Planner或Research阶段，可将user_files作为已提供知识，让代理优先利用。这些文件通常由ResearchAgent首先处理：例如将其内容也向量化存入vector_index，或提取摘要加入ledger，使系统能将用户提供的信息与网上检索的信息结合起来。SynthesizerAgent写作时也可引用user_files中的内容并标明来源。总之，user_files确保用户给定的背景材料能融入最终输出。
(上述GraphState可以根据具体实现扩展，例如还可以包括citation_map、current_step之类辅助字段，但核心概念如上。所有代理共享此状态，各自只读/更新自己相关的部分：Planner写入plan，Supervisor更新pointer和plan状态，ResearchAgent扩充chapter_bucket/ledger/vector_index，ReasonerAgent更新ledger状态和memory/draft_summary，SynthesizerAgent读取所有内容生成draft并输出结果等。持久化的GraphState也方便在中途暂停/恢复流程或进行审查。)
3. PlanningAgent 详解
PlanningAgent（规划代理）负责接收用户输入的问题或任务说明，并产出解决该任务的分步计划。这通常通过一个提示（prompt）模板引导LLM完成：提示会要求模型严格按照指定JSON格式输出计划列表，以确保后续流程易于解析。PlanningAgent的提示模板通常包括对用户请求的重述、要求模型列出步骤以及每步需要的字段说明。
以下是一个示例提示模板，指导模型生成计划（为清晰起见采用英文字段名，实际实现中可根据需要使用中英文结合）：
以下提示词仅是逻辑！！！
系统角色：你是一个擅长任务分解的AI规划助手。
用户输入：{user_input}  （这是用户提出的问题或课题）
你的任务：请根据用户需求，将任务拆解为若干连续步骤，并以JSON格式输出一个名为"plan"的列表。每个步骤应包含：
- "id": 步骤编号，从1开始顺序递增
- "description": 对该步骤要完成内容的简要描述
- "info_needed": 布尔值，表示该步骤是否需要通过网络搜索/工具来获取外部信息
- "source_hint": 如果需要检索，可提供一些搜索关键词或来源提示，如特定网站或数据源
- "status": 初始状态，设为 "pending"
请确保严格输出JSON格式，不要附加额外说明。
示例输出：假设用户询问的是“调查 Apple 公司在人工智能领域的并购案，并提供详细分析和引用资料”，PlanningAgent可能返回如下JSON结构的计划：
{
  "plan": [
    {
      "id": 1,
      "description": "列出苹果公司在人工智能领域的重要收购及时间线",
      "info_needed": true,
      "source_hint": "Apple AI acquisitions timeline, major AI company purchases by Apple",
      "status": "pending"
    },
    {
      "id": 2,
      "description": "分析苹果进行这些AI收购的动机和战略目的",
      "info_needed": true,
      "source_hint": "Apple acquisition strategy AI rationale",
      "status": "pending"
    },
    {
      "id": 3,
      "description": "评估这些并购对苹果自身及行业产生的影响",
      "info_needed": true,
      "source_hint": "impact of Apple AI acquisitions on industry, Apple AI capabilities",
      "status": "pending"
    }
  ]
}
上述plan以JSON数组形式给出了3个步骤，每一步都有清晰描述和标签。其中info_needed字段指导后续流程：为true表示需要通过ResearchAgent检索资料支持；source_hint提供了检索方向上的提示关键词；status初始为"pending"表示尚未完成。需要注意，为了确保串行执行，所有步骤默认不可并行（因此未设置任何parallelizable字段或将其视为false）。Supervisor将按此清单顺序执行任务，每完成一步可将其status更新为“completed”。如果执行过程中有新的子任务插入，需确保赋予唯一的id并妥善插入plan相应位置。
通过PlanningAgent模块，复杂的问题被逐步细化为一个有序的行动列表。这一步非常关键——它决定了后续信息检索和内容产出的范围和方向。如果计划不合理，后面再充分的检索和分析也难以得到满意结果。因此通常会针对PlanningAgent的prompt进行仔细设计，甚至加入示例Few-Shot或约束，以生成高质量、无歧义的任务计划。例如，可以要求步骤不要过于泛泛（确保每步可以相对独立完成）、步骤数合理（避免过多或遗漏关键步骤）等。Planner的输出直接写入GraphState.plan，Supervisor据此开始整个执行流程。

附一个严肃的提示词模板（注意，和上面的示例没关系）
SYSTEM: You are **PlannerAgent**. Your job is to transform a user research
query into an executable research plan for downstream LangGraph nodes.

=== OUTPUT FORMAT ===
Return a single JSON array inside ```PLAN``` fences.  
Each element must contain the following fields **in this order**:

{
  "id":             "<kebab-case unique slug>",
  "description":    "<one concise sentence>",
  "info_needed":    ["<bullet 1>", "<bullet 2>", …],
  "keywords":       ["term1", "term2", …],
  "source_types":   ["academic", "news", …],
  "parallelizable": true | false,
  "depends_on":     ["id_of_step_a", …],
  "cost_estimate":  "low" | "medium" | "high"
}

If a list is empty, return an empty array (`[]`).  
No additional keys are allowed.

=== REQUIREMENTS ===
1. Deeply analyze the query; identify core objectives, scope, and assumptions.  
2. If clarity is insufficient, write clarifying questions.  
3. Produce a multi-step plan following the field definitions above.  
4. Total top-level steps ≤ 10. Combine or nest if needed.  
5. Output **only** the JSON array inside ```PLAN``` fences.  
6. If you asked clarifying questions, put them in a separate ```QUESTIONS``` block
   (array of strings); otherwise omit that block.  
7. Do **NOT** proceed to execution until the user replies **APPROVED**.

USER_QUERY:
{user query here}
4. Macro-Supervisor 机制
**Macro-Supervisor（宏观监督代理）**充当整个多代理流程的“大脑和调度者”。它以GraphState.plan作为待办任务队列，仅执行pointer指向的当前步骤，严格按照顺序推进。Supervisor自身不调用LLM执行推理任务，而是根据步骤需要决定调用哪个子代理，并管理状态切换和任务插入。其运作机制可以用伪代码描述如下：
pointer = 0
while pointer < len(plan):
    task = plan[pointer]
    if task["info_needed"] is True:
        # 需要外部信息，调用ResearchAgent检索
        ResearchAgent.execute(task)
    # 无论是否检索，都调用ReasonerAgent进行分析
    result = ReasonerAgent.analyze(task)
    if result.new_task:
        # Reasoner建议有缺口，需要插入后续任务
        new_task = result.new_task  # 包含id/description等
        plan.insert(pointer+1, new_task)
        # （pointer不变，以便先执行新插入任务）
        task["status"] = "pending-followup"
    else:
        # 当前任务完成，更新状态，pointer移动到下一步
        task["status"] = "completed"
        pointer += 1
# 所有任务完成后，调用SynthesizerAgent产出最终报告
SynthesizerAgent.generate_output()
如上所示，Supervisor的核心是一個循環：读取当前任务，根据其属性选择下一行动。状态切换机制如下：
- 如果当前任务需要检索（info_needed=true），Supervisor会调用ResearchAgent执行外部搜索和数据获取。ResearchAgent完成后会将资料和摘要写入GraphState（例如ledger增加新条目、chapter_bucket填充内容），然后返回控制权给Supervisor。
- 无论当前任务是否经过检索，Supervisor接着调用ReasonerAgent对该任务的信息进行分析综合。ReasonerAgent处理后会给出结果，通常包括分析是否充分、总结性的内容，以及（可能）一个“后续步骤”建议。
- Supervisor检查ReasonerAgent结果：如果Reasoner判定信息不完整，需要follow-up，则会从结果中提取出新的任务（通常包含description和source_hint等），将其插入plan紧邻当前任务之后。这种插入方式确保了补充任务在当前任务未完成前马上执行。插入后，Supervisor不会立刻增加pointer（pointer仍指向当前任务的下一个，即新插入任务的位置），相当于“暂停”原任务流程去先完成补充任务。为区分状态，Supervisor可以将当前任务标记为“pending-followup”或类似状态，表示其完成依赖后续任务的结果。
- 如果ReasonerAgent结果显示当前任务已完成（信息充分），则Supervisor将当前任务状态标记为“completed”，然后pointer加1指向plan中的下一个主任务。
- 循环继续，Supervisor读取下一任务……依此直到pointer越过plan结尾，表示所有任务都处理完毕。
当所有步骤都完成或没有更多新任务时，Supervisor最后调用SynthesizerAgent开始内容合成阶段。此时GraphState中已经积累了完成撰写所需的所有信息：每步的ledger要点、章节摘要、全局memory、外部资料索引等。Supervisor将这些通过函数参数或上下文传递给SynthesizerAgent，并监听其输出流以整合成为最终文档格式。
需要强调，Supervisor在整个过程中起到单线程调度的作用：它保证永远只专注处理当前pointer指向的一项任务，不会并发启动多个任务的执行。这避免了多个代理同时修改共享状态的竞态问题，简化了流程控制。同时，Supervisor也承担了错误监控和恢复的职责：如果某一子代理调用失败或返回结果异常，Supervisor可以根据情况选择重试该步骤、跳过或中止流程，并将错误信息记录在GraphState或日志中供调试。
Supervisor机制的设计使我们能够在需要时灵活插入新的任务节点、调整流程顺序，甚至实现人在环（human-in-the-loop）干预：例如开发者可在Reasoner阶段暂停，让人工检查当前ledger和结论，再决定是否继续。LangGraph框架对这种运行时插入和跳转提供了良好支持，使得Supervisor可以轻松地增删节点并继续执行。总之，Macro-Supervisor串起了规划、检索、推理和写作各环节，确保流程按照设计的顺序和逻辑稳健运行。
5. 支持并行任务的 ResearchAgent
ResearchAgent（研究代理）专门负责执行外部信息检索，是整个流程中唯一在内部实现并发操作的环节。它的目标是在尽可能短的时间内获取全面且相关的资料填充当前任务需求。ResearchAgent典型的执行步骤如下：
1. 解析检索需求：读取当前任务的description和source_hint，确定检索的主题范围和关键词。如果source_hint提供了特定网站或数据源（例如要求在学术论文、官方博客中查找），ResearchAgent会据此调整搜索策略。必要时，它还可以调用LLM将任务描述改写为更有效的查询词。
2. 批量搜索：构造一个或多个查询向搜索引擎API发送。ResearchAgent可以根据任务复杂度制定并行查询策略，例如同时向不同搜索引擎（Google、必应等）查询，或对同一问题采用不同关键词措辞平行搜索。这样可以覆盖更广的信息源。搜索结果返回后，提取每个结果的标题、摘要和URL等。
3. 并发抓取网页：对于选中的若干重要结果（例如排名前5的链接），ResearchAgent启动异步HTTP请求并行抓取其全文内容。借助Python的asyncio库或多线程/多进程，能够同时向多个URL发出请求而不必串行等待，从而显著缩短总耗时。每个网页响应获取后，立即解析正文文本（去除HTML标签、脚本等），得到纯文本内容。
4. 内容处理与存储：将抓取到的文本进行预处理，如按段落或固定token长度切分为小块（chunks）。每个内容块（通常几十到几百字）随即通过Embedding模型向量化，添加进全局vector_index中。同时，ResearchAgent可以挑选其中与当前任务最相关的部分（比如包含了直接答案或重要事实的段落），存入chapter_bucket[current_step]列表中备用。这个过程中也会记录文档来源（URL或标题）以备引用。
5. 生成资料要点（ledger摘要）：在完成资料收集后，ResearchAgent会调用LLM或使用启发式方法，将收集到的信息提炼成约5条关键要点。通常它会将章节资料桶（chapter_bucket）中的精选段落或片断作为输入，上下文附加任务描述，对LLM下指令：“请基于以上资料，总结出5个与当前任务最相关的重要发现，用简洁bullet点形式表达，每点不超过一两句话。” LLM生成的结果就是该任务的初步知识摘要。例如，对于“苹果公司的AI收购时间线”任务，可能得到如下要点：
  - Apple在2010年收购了Siri公司，为其日后的语音助手奠定基础【来源1】
  - 2016年Apple以2亿美元收购Turi，加强其机器学习平台能力【来源2】
  - …（其余省略）…
6. 每条要点力求涵盖一个核心事实或结论，并在内部标注出数据来源。
7. 构建引用映射（citation_map）：ResearchAgent会建立要点与原始资料来源的映射关系。例如上面的bullet中【来源1】对应某篇新闻文章URL及段落位置，【来源2】对应另一报告。这种映射可以存在ledger条目的内部结构中，或者作为GraphState中一个独立的citation_map字典。其作用是在后续写作阶段，当SynthesizerAgent引用某条bullet内容时，可以快速找到对应来源用于插入引用标注。如果LLM在生成要点时已包含来源标注，ResearchAgent可直接利用；否则可以通过匹配要点中的关键词在已抓取文本中定位，确定引用。
8. 写入GraphState：ResearchAgent将最终得到的LedgerEntry写入全局状态：如向GraphState.ledger列表追加一条记录，内容包含当前步骤id、该步骤bullet要点列表以及citation_map（或来源列表）等。同时，GraphState.chapter_bucket[current_step]已填充了原文片段列表，GraphState.vector_index则扩充了所有文档向量。ResearchAgent完成后，将控制返回Supervisor并附带一个简要结果（例如新ledger索引或成功标志）。
通过上述流程，ResearchAgent在单个任务内部实现了高度的并行效率。它批量搜索加异步爬取让等待时间显著减少，同时利用LLM对海量文本进行摘要提炼，将关键信息浓缩成有限的要点。这样既避免将冗长全文直接传递给后续LLM造成上下文超载，又为ReasonerAgent提供了聚焦的材料。ResearchAgent的实现应考虑网络可靠性和容错，例如对抓取失败的链接可重试或跳过，并在要点中注明可能的信息缺口，以便ReasonerAgent决定是否追加其他搜索。总的来说，ResearchAgent使得整个系统能够动态地从网络和用户资料中获取知识，扮演了多代理中的“情报收集专家”角色。
6. ReasonerAgent
ReasonerAgent（推理代理）承接ResearchAgent提供的要点和资料，对其进行分析、验证和整合，以确保当前任务的需求得到满足。它相当于人类研究员在阅读完资料后的思考过程：判断信息是否充分可信，提炼结论，找出尚未解答的问题。ReasonerAgent运行时，会读取GraphState中最新写入的ledger条目（对应当前任务的5条要点），以及该任务的原始描述和可能的期望输出。其工作可以分为几个阶段：
- 理解任务目标：ReasonerAgent首先明确当前步骤在整体计划中的定位。例如，任务要求“分析苹果进行AI收购的动机”，它会识别此任务需要回答的是“苹果为何收购这些AI公司”这一问题。任务描述和前序步骤提供的背景（全局memory中可能含有上一章节的总结）会作为提示的一部分，帮助Reasoner把握要解决的问题是什么。
- 审查检索要点：接下来ReasonerAgent仔细阅读ResearchAgent提供的ledger要点列表。这些要点是未经深度加工的信息碎片，Reasoner需要评估它们与任务问题的相关性和充分性。例如，要点可能列出了苹果收购了哪些公司及一些表面原因，但Reasoner要检查这是否已经直接解释了“动机”。如果有的要点不直接相关或显得多余，Reasoner会有选择地忽略或淡化它们；如果要点中提及的数据存在矛盾或存疑之处，也会标记出来以备后续确认。
- 综合归纳（Map-Reduce）：ReasonerAgent使用LLM对这些要点执行Map-Reduce式总结。具体而言，Map阶段可以视为对每条要点做局部推理或扩充：LLM逐条阅读要点，也许在内部思考“这条信息说明了什么？对于任务问题有何意义？”。Reduce阶段则让LLM将所有要点串联考虑，得出一个凝练的结论或摘要。例如，对于动机分析任务，如果要点提供了多个角度（获取人才、获取技术、布局未来产品等），ReasonerAgent可能将其汇总成一句话：“苹果公司收购AI初创公司的核心动机包括获取关键技术与人才以增强自身产品，以及防止潜在竞争威胁。” 这样的输出比原始要点更加贴近任务提问，形成章节摘要草稿。ReasonerAgent会将此总结结果写入GraphState.draft_summary当前任务对应条目。
- 完整性检查：ReasonerAgent还负责判断当前知识是否足以回答任务。如果通过综合，他认为已有资料可以回答用户提问的该部分，则认为任务完成；但如果发现一些未解答的细节或缺失，则需提出后续行动建议。例如，当分析动机时，要点里可能没有提到某些关键收购案例或者遗漏了竞争对手动态，那么ReasonerAgent会将这些视为信息缺口。在LLM提示设计中，可以引导模型列出未回答的问题：“以上信息中是否有尚未解释的方面？如果有，请提出新的研究问题。”模型若生成了新的问题（如“苹果是否也出于专利考虑进行收购？”），Supervisor就可以将其作为新任务插入plan继续检索。
- 输出决策：根据完整性检查结果，ReasonerAgent向Supervisor返回一个结构化的结果。例如：result = {"status": "complete", "summary": "<总结文本>"}表示信息充分完成任务，或者result = {"status": "incomplete", "new_task": {"description": "...", ...}}表示需追加任务。Supervisor据此采取不同操作（见前章Macro-Supervisor逻辑）。通过这种协议，ReasonerAgent有效地在流程中充当质量把关角色，防止不完整或不正确的信息进入最终报告。
- Think Panel推送：当ReasonerAgent完成分析后，它还会将思考过程和结论记录推送到“Think Panel”（思考面板）。这个面板可以理解为调试或用户可见的中间输出区域，其中显示了ReasonerAgent的主要结论、判断依据甚至Chain-of-Thought。如果系统UI有该功能，用户或开发者可以在Think Panel中看到例如：“任务2分析：已确认苹果收购动机包括获取技术和人才，但尚未找到是否有专利考虑，建议进一步检索。” 这样做提高了系统透明度和可解释性，便于在结果有偏差时追溯中间步骤。
- 更新Memory：最后，ReasonerAgent会将当前任务的重要结论写入全局memory，以供后续步骤参考。通常做法是累积摘要：将之前的memory内容与本任务的新总结一起输入LLM，要求其压缩成新的memory。这保证memory保留前面所有章节的核心要点，但长度控制在合理范围，没有重复冗余。更新后的memory写回GraphState.memory字段。例如，完成“动机分析”任务后memory可能变为“一系列收购充实了苹果AI团队和技术储备，为Siri等产品提供了支持，同时削弱潜在竞争对手在相关领域的发展势头。” 这句话融合了时间线章节和动机章节的精华内容。若后面还有章节如“影响评估”，就可以结合前两章的memory作为上下文提示，防止SynthesizerAgent输出与前文矛盾的分析。
综上，ReasonerAgent通过对检索结果的深入思考，保证了知识的正确性和完整性，并将结构化知识转化为自然语言总结（为最终撰写做好准备）。它在多代理架构中扮演智囊和质检角色，使得每章内容在进入最终报告前都得到审视和完善。例如LangChain等框架中常见的反思和自我纠错机制，在此由ReasonerAgent体现出来。有了ReasonerAgent，系统可以更自信地产出高质量答案，同时也更容易定位问题出在哪个环节（通过Think Panel的记录）。
7. Memory 与上下文裁剪
在多代理长流程中，如何管理海量上下文是关键挑战。LangGraph架构通过划分不同粒度的存储（ledger、bucket、vector index、memory等）并在需要时裁剪上下文，来平衡信息保留与模型上下文长度限制。下面进一步解释各存储在上下文管理中的角色，以及上下文载入策略：
- Ledger（逐步知识卡片）：Ledger是逐任务的中等粒度摘要集合，每张卡片约300 tokens，涵盖该任务最重要的知识点。Ledger记录按任务顺序积累下来，构成了过程中的知识库索引。由于每张卡已是提炼结果，ledger的规模相对可控，例如10个任务约3000 tokens。如果需要把所有任务的要点提供给模型，ledger往往能放下。在实际上下文使用中，ReasonerAgent通常只需要最近一个任务的ledger来分析当前信息，不必每次都读入全部ledger。而SynthesizerAgent有时会用到所有ledger来确保不遗漏点，但如果任务很多也可以选择更精练的memory代替。总的来说，ledger扮演“阶段性成果存档”角色，其条目可以根据需要有选择地加载到prompt中。
- Chapter_bucket（章节资料片段）：Chapter_bucket存储细粒度的资料片段（mini chunks），每个片段可能只是一句话或一小段文本，但包含具体细节、数据或引文。每个章节bucket最多保留几十条高度相关的片段，以避免噪音。SynthesizerAgent在撰写对应章节内容时，会将该bucket作为候选引用池：当模型需要具体细节支撑时，可以方便地从中选择句子引用。而在非对应章节时，这些片段通常不进入上下文，避免干扰。上下文裁剪策略上，bucket使我们按需加载：只有当前正在撰写的章节，其bucket内容才会加入prompt（并且通常也是经过筛选后的一部分，比如最相关的几条）。这样每次生成时，模型看到的细节都是当前主题相关的，不会因为别章细节干扰。生成完一章后，下一个章节会使用自己的bucket内容。
- Vector_index（全文向量索引）：vector_index提供随机存取的大型知识库支持，通常不直接融入prompt上下文，而是通过工具调用或后台查询来提供内容。也就是说，SynthesizerAgent并不会把整个向量库内容读入；相反，它会根据需要检索。例如当模型生成某句话觉得需要验证，会发起一个向量查询（这在LangChain中可作为一个Tool调用），找到匹配的原始文本然后将其插入输出或者参考。这是一种懒加载策略：大部分时间向量库只是静静存在，不消耗上下文，但一旦需要任何细节，都能通过语义搜索即取即用。这种方案确保即便抓取了上百万字符的文本，也不会导致LLM提示长达上百万字符；模型只会看到和当前内容强相关的那一两段文字。因此vector_index可以视为外部记忆，用空间换时间，减少对prompt长度的占用。
- Draft_summary（章节摘要）：Draft_summary是面向生成的压缩上下文。每章的draft_summary通常不到原始ledger的一半长度，却以流畅语句总结了该章要传达的内容。这些摘要在SynthesizerAgent撰写章节时会作为主要上下文提供给模型，相当于指导模型“这一章你要写的要点有哪些”。相比直接给模型5条离散bullet，让它自己组织成文，提供一段预先整合的摘要更能保证写作质量和连贯性。因此SynthesizerAgent每次开始生成某章节时，会加载：该章节的draft_summary（让模型明白要写哪些点）、必要时该章节ledger bullets（作为补充核对）以及global memory（提供大局背景）。Draft_summary由ReasonerAgent生成，已经在很大程度上裁剪掉冗余，只保留当前章节核心内容，因而非常适合作为prompt的一部分。通过控制draft_summary长度（例如不超过150 tokens），可以确保即使章节较多，总的输入也不会爆炸。
- Memory（全局记忆）：Memory是最高抽象层次的上下文，只保留贯穿全文的关键结论或背景。一方面，Memory作为后续章节的背景输入，可以让模型知道之前章节的大概内容，避免前后矛盾；另一方面，Memory也可用于SynthesizerAgent生成引言或结论部分，或者在跨章节引用时使用。例如，如果最后需要总结“综上，苹果公司的AI并购策略表明……”，memory中早已包含所有章节浓缩的信息，可用来生成结论段落。Memory通常在每次ReasonerAgent完成后更新，因此始终反映最新完整知识。在上下文加载时，我们一般在每个章节prompt的开头附加一小段Memory文本（可能50100 tokens），提供上下文过渡语气和背景。例如SynthesizerAgent写第3章前，prompt可能包含：“（上一章总结：苹果收购AI公司的动机主要是获取技术和人才）现在继续写第三章：……”。这样模型就在理解上下文的情况下写作，章节衔接自然且不会重复已有结论。Memory长度随着章节增加可能增长，但由于每次都reduce压缩，它增长趋于缓慢，会稳定在某个大小（比如全篇总结200300 tokens）。如果章节特别多，Memory也可只保留最新几章的要点和更高层结论以控制长度。
上下文构成与载入节奏：综合以上，各阶段使用上下文各不相同：
- Planner阶段：输入只有用户提供的 query 和 user_files摘要（如果有）——没有其它上下文。
- Research阶段：主要使用任务的source_hint等来触发搜索，不涉及LLM大量上下文。
- Reasoner阶段：输入包括该任务 ledger bullets + （必要时）global memory + 任务描述。通常不需要别的章节ledger，以免混淆当前分析。产出draft_summary并更新memory。
- Synthesizer阶段：逐章调用LLM，每章输入由 global memory + 当前章 draft_summary + 当前章 bucket 细节 组成。Global memory在每章写作时提供背景（过去章节大意），draft_summary提供本章待写要点列表，bucket提供随取随用的引用素材。如果当前章需要引用前面章节内容，也可以通过memory了解大概再用vector_index搜索具体细节。例如第3章写作时，如需引用第1章的一个数据，模型可根据memory知道第1章有那方面内容，然后通过向量检索找到具体语句插入引用。每章生成完毕后，SynthesizerAgent再移至下一章，重复相似过程（memory此时也包含了已写章节的概要，可提供衔接）。
- Critique阶段（如果有）：输入是整篇草稿，或者分章节审查，每次上下文载入整个章节内容及其引用进行检查。这步如使用LLM，则模型上下文需涵盖全文，为避免超长，通常CritiqueAgent会按章节或主题分块审核，逐块处理上下文。
通过对上下文的分层存储和渐进式载入，LangGraph架构实现了对超长任务的支持。一方面，充分的资料通过vector store保存，不遗漏任何信息；另一方面，不同阶段各取所需，LLM每次只看到与当前任务或章节高度相关的内容，从而既不超出上下文窗口，又提高了回复准确性。这种方法类似人类写论文：前期做大量笔记和收藏资料（vector_index），写作时按提纲逐节写，每节只参考当节的笔记和必要的引用，全篇完成后再整体润色。通过Memory和ledger的配合，我们避免了LLM在长流程中遗忘前文或重复啰嗦，从而使最终输出既连贯又信息丰富。
8. SynthesizerAgent
SynthesizerAgent（合成代理）接管所有准备好的资料和摘要，执行最终的内容创作，将之前阶段的成果编织成完整的技术文档输出。它采用流式逐章写作的方式，以保证每章内容质量和整体结构清晰，同时方便长文分段生成。SynthesizerAgent的工作重点包括内容生成、格式排版和引用插入几个方面：
- 逐章流式生成：SynthesizerAgent按照GraphState.plan中步骤的顺序，一章一章地生成文稿。对于每个章节（对应plan中的一个任务），它会将该章的draft_summary和相关背景提供给LLM，并生成该章节的正文文本。在实际实现中，可以通过流式输出（streaming）逐字逐句地接收LLM生成，以便及时呈现给用户或检测内容。例如，当模型在生成一段较长文本时，可以边出边显示。同时，这种按章节调用LLM的方法还能让我们在每章之间稍作调整或检查：例如在第一章生成后，可以插入一些基于memory的过渡句再开始第二章，或者在每章完成后利用CritiqueAgent快速审核后再继续。总之，章节粒度的流式生成提高了系统的可控性和稳定性。
- 利用章节要点和全局背景：为确保生成内容与前面收集的知识一致，SynthesizerAgent会在prompt中明确提供该章要包含的要点（即ReasonerAgent准备的draft_summary）以及必要的全局信息（memory）。模型因此能“心中有数”地撰写该章节：既不会偏题，也能自然过渡。例如，在撰写“苹果AI收购的动机”章节时，prompt包含了该章的3条概要动机（技术、人才、竞争等）以及memory中上一章的收购列表。模型据此会依次展开说明每个动机点，并提及前章收购实例作为支撑。这种受控生成方式，比起让模型自己去回忆或推理所有细节更可靠，避免了内容遗漏或编造。在实际实现时，这种prompt通常以说明方式出现，如：“根据以下要点撰写本节：1）… 2）…；背景：苹果在2010-2020年收购了多家AI公司…，请展开成段落。”
- 检索细节并插入引用：SynthesizerAgent在生成过程中，会充分利用向量索引和章节资料桶来引用原始资料。当模型产生日常说明性的内容时，仅靠记忆和摘要即可完成；但当涉及具体事实（年份、公司名称、报价等）时，系统会引导模型插入准确的引用。例如，模型可能生成句子：“2016年，苹果收购了机器学习初创公司Turi，以加强其AI技术能力”，此时SynthesizerAgent会调用vector_index检索与“2016 Apple Turi acquisition”相关的文档片段，找出支持这句话的来源（比如新闻报道），并在句末附上引用标记。如果ResearchAgent在ledger bullet中已经给出了来源映射，则SynthesizerAgent可直接使用该映射：例如它知道“Turi收购”这条bullet对应【来源2】，就在句子末尾放上【2】或类似引用编号。
- 引用的插入可以通过LLM提示或后处理实现。有一种方式是在prompt里要求模型在生成内容时附上引用编号，然后由系统将编号映射到真正的文献列表。另一方式是在模型输出文本后，程序根据citation_map插入相应的Markdown链接或文末引用。例如模型输出了“不久后，Apple 又收购了XYZ公司”，系统检测到XYZ出现在资料映射中，即自动在句末添加【3】并在文末引用列表加入来源3的信息。这确保最终文档的每一重要论断都有据可依，让读者可以查证。SynthesizerAgent通过这种人机结合的方式将强大的生成能力和精准的检索结果融合，达到了“生成内容+参考出处”的效果。
- 格式化输出：作为面向程序员和终端用户的交付，SynthesizerAgent严格按照Markdown等指定格式排版输出内容。它会根据plan结构使用合适的标题级别（如章节使用## 标题），列表和表格根据需要插入，并保持段落简洁可读（每段3-5句左右）。代码示例或伪代码则放入代码块中高亮显示。这些格式规范在prompt或系统预设中就已告知模型，或者由后处理程序完成。例如，可以在SynthesizerAgent开始时固定生成文档标题# ...，然后每章以“## 第N章 …”开头，内容中如有清单则用-符号。由于LangGraph支持Token流式输出，我们可以实时将模型输出直接写入Markdown文件或缓冲区，这样在执行结束时就已经得到了排版完整的Markdown内容。
- 章节间衔接：SynthesizerAgent确保各章节逻辑连贯，避免各自为政的割裂感。这通过Memory提供的背景和模型自身的上下文记忆来实现。例如模型知道上一章讲了收购列表，所以在下一章开头自然而然地总结一句“基于以上对苹果过往收购的梳理，我们接下来分析其背后的动机。” 从而实现章间过渡。如果Memory指出某前章内容需要在后章引用，模型也会用适当方式提及，如“正如第二章所述，苹果在这些收购中往往注重人才获取…”。这种跨章节引用增加了报告的整体性。当然模型并不具体知道章节编号内容，但Memory摘要给了它线索去引用。对于更精确的章节引用，可以在最终文档定稿时手动/程序后处理，如将“第二章”替换为具体标题或超链接。
- 总结构建：SynthesizerAgent完成各章节正文后，还可以生成引言和结论等总结性部分。一种做法是在正式章节生成前，先根据整体plan和memory生成一段绪论介绍全文结构；结尾再让模型基于memory输出全文总结和展望。这些也通过prompt实现：例如在章节开始前插入任务0：“撰写引言概述本文内容”，在所有章节结束后插入任务N+1：“总结全文并给出结论”。SynthesizerAgent会将这些特殊任务当作章节来生成内容（引言没有引用，结论可能也没有新的引用）。最终输出的Markdown文档就包含：标题、引言、各章节正文和结论。引言能帮助读者快速了解文章目的，结论则升华主题或重申重点。这些部分的生成使用Memory中全局信息，不需要额外检索。
SynthesizerAgent的实现需要注意流畅度与忠实度的平衡：既要充分发挥LLM语言生成流畅自然的优势，又要确保不脱离之前的事实依据。通过事先提供摘要和在关键处检索引用，SynthesizerAgent基本达到了两全其美：输出文本专业、连贯，同时每个论断都有来源证明。一份最终文档样例可能是这样的：
# 苹果公司AI并购案研究报告

## 引言
苹果公司在过去十多年中通过多起对人工智能领域公司的并购，加强了自身技术能力...（引言略）

## 1. 苹果在AI领域的主要并购概览
苹果公司自2010年以来进行了多次与AI相关的并购：
- **2010年**，收购语音识别初创公司Siri Inc，为日后推出Siri语音助手奠定基础【1†】。
- **2016年**，以约2亿美元收购机器学习平台公司Turi，用于强化其机器学习研发能力【2†】。
- **2020年**，收购Edge AI初创企业Xnor.ai，将高效边缘AI算法引入其设备端应用【3†】。
...（其余并购列表）

上述并购构成了苹果在AI领域布局的时间线，从早期专注移动端AI到近年侧重于核心技术获取【1†】【3†】。

## 2. 苹果进行AI收购的战略动机
苹果进行上述收购的主要动因包括：
1. **获取关键技术与人才**：通过收购，苹果能够将新兴AI技术据为己有，并将顶尖AI人才纳入麾下，以推动自身产品创新【4†】。例如对Turi的收购既获得了机器学习算法，也获得其创始团队为苹果效力。
2. **整合生态和提升产品**：...（阐述苹果如何将收购成果整合进产品）
3. **防范竞争威胁**：苹果有时出于防御目的收购公司，防止竞争对手得到关键技术，从而巩固自身市场地位【5†】。
...（动机的进一步分析）

## 3. 并购带来的影响和效果
...（第3章内容）

## 结论
通过本研究可以看出，苹果公司在AI领域的并购策略卓有成效...（结论略）
(上例为SynthesizerAgent可能生成的Markdown节选，可以看到各章节内容详实，有条理地引用了来源【1†】【2†】等，格式上使用了标题、粗体、列表等提高可读性。实际输出将更为完整。)
在生成完成后，SynthesizerAgent将各部分内容汇总（通常已经在过程中按顺序输出到缓冲区，即无需额外拼接），得到最终的Markdown文档字符串，并将其存入例如GraphState.final_draft或直接通过接口提供给用户。至此，多代理协同的规划->检索->推理->写作流程实现了端到端闭环。
9. CritiqueAgent / TTS / 导出
在SynthesizerAgent完成初稿后，LangGraph架构还可以附加复审与分发环节，以进一步打磨内容质量，并将成果以多种形式交付。这部分通常包含CritiqueAgent（评估代理）、TTS（文本转语音）以及导出模块等。
- CritiqueAgent（评论/审校代理）：这是一个可选的LLM代理，用于自动复审SynthesizerAgent生成的文稿。CritiqueAgent从质量和准确性两方面检查：语言上，它会审阅全文的连贯性、措辞、逻辑是否清晰，有无语法或格式错误；内容上，则核对是否存在前后矛盾、引用错误或潜在的不当言论等。如果发现问题，CritiqueAgent可以给出修改建议或直接提出修正稿。例如，它可能指出某章节重复前文内容、某引用与文本不符，或者建议在结论中加强某观点。这通常通过让LLM以“审稿人”身份阅读Markdown文本并输出评语或修订。开发者可以选择自动应用这些修改（如小的措辞调整自动替换），或将CritiqueAgent的反馈呈现给人工以决定取舍。通过CritiqueAgent的把关，最终报告质量更有保障，尤其在较敏感或要求严谨的场景下可避免疏漏。当然，在许多应用中，SynthesizerAgent输出已经足够好时，可以不启用CritiqueAgent以节省资源。
- TTS（Text-to-Speech，文本转语音）：为了提高内容的可及性或满足特定需求，系统可以将最终文档转换为语音朗读。这对那些喜欢听报告的人或有视力障碍的用户非常有用。TTS模块通常利用现有的语音合成服务或库：例如调用Google Cloud Text-to-Speech、Amazon Polly，或本地部署的TTS引擎。实现上，将Markdown文档去除格式标记后送入TTS引擎，选择合适的语音和语言（如中文女声），生成音频文件（MP3或WAV）。还可以对不同章节生成不同音频文件方便跳转，或整合成一个长音频。生成完毕后，系统可以提供音频的播放或下载链接给用户。这个过程通常不涉及LLM，所以并行执行不影响系统主要流水线。最终用户可以一边阅读报告一边听语音讲解，提高了交付体验。
- 导出到多格式：最终成果往往需要以用户期望的格式交付或存档。除了默认的Markdown（适合开发者和简单预览），系统可支持一键导出到以下格式：
  - Google Docs 文档：通过Google Docs API，系统可以创建一个Google文档，并按段落将Markdown内容转成Docs格式。包括将Markdown标题转换为文档的标题样式，粗体/斜体等富文本保留，列表和表格也对应转换。此外，将引用部分加入文档的脚注或尾注。导出后，可以返回一个可共享的Docs链接给用户。在企业应用中，也可以选择输出到Microsoft Word文档（DOCX）类似方法。
  - PDF 文件：利用Markdown到PDF的转换库（如Pandoc、WeasyPrint、LaTeX模板等），将报告渲染为版式固定的PDF。这需要处理好分页、目录、页眉页脚和图片引用等。LangGraph框架下也可通过先转Google Docs再由Google提供PDF导出，或使用ReportLab等直接生成PDF。PDF格式便于打印和发送邮件附件，是常用的交付形式。我们会确保PDF中目录和标题层级清晰，引用以尾注形式呈现。
  - 幻灯片（PPT/Slides）：将长篇报告转为演示幻灯片需要对内容进行浓缩和分段。一种方式是自动按章节提取要点生成每页幻灯的项目符号列表。例如每章用几条bullet列出核心结论，一页幻灯对应一章。也可以调用LLM总结每章成一句话标题和若干要点。之后，通过Google Slides API或PPTX生成库（如python-pptx），程序化地产出一组幻灯片：标题页、引言页、各章要点页、结论页等。这些幻灯可供快速汇报使用。当然，此步骤需要一定的模板设计以确保美观，例如统一的背景、字体和配色，也可在导出后再由人工调整。
  - HTML 网页：Markdown 转 HTML 是最直接的，可以通过静态站点生成器或前端渲染Markdown库来实现。导出时，会将Markdown解析为HTML片段，配以基本的CSS样式，使其在浏览器中良好呈现。这对于需要在内部知识库发布报告或生成在线文章的场景很有用。HTML版本可保留所有格式，包括标题、列表和链接，对于引用则可以做成本页脚注或超链接形式。
- 在导出过程中，一个重要任务是保持文档结构和引用：无论何种格式，我们都会生成内容目录（TOC）以方便导航，引用则根据格式不同或转为超链接、或编号注释。例如在PDF/Docs中通常采用页末编号参考文献列表，在HTML中可以将引用标记链接到文末参考资料区域。用户上传的图片或本地截图等也在允许范围内嵌入到导出文件中。整个导出模块应设计成与主流程解耦，不影响代理执行。在SynthesizerAgent完成Markdown输出后，导出可以在后台并行完成，最终把相应文件提供给用户。
通过CritiqueAgent审校、TTS语音和多格式导出，LangGraph多代理架构从内容生产拓展到质量保障和多样化交付。这使得系统交付物不仅限于纯文本对话，还可以成为正式的报告文档、听觉内容，甚至演示资料，极大提高了AI助理的实用价值和专业度。
10. 端到端案例：以“调研 Apple AI 并购案”为例
最后，我们通过一个完整示例来串联上述各环节，加深对LangGraph多代理架构流程的理解。假设用户提出请求：“请调研苹果公司在人工智能领域的并购案例，并撰写一份详细报告（包含分析和引用）。” 用户还上传了一份包含苹果收购列表的PDF作为参考资料。下面按步骤展示系统的运作：
1. 用户输入与Planner规划：用户的问题较为宏大，涉及罗列案例和分析。Planner首先读取用户提供的PDF文件（其中可能列出了一些收购事件），将其摘要纳入考虑。随后Planner调用LLM生成解决方案：它输出了一个JSON plan，例如：
- 步骤1：列出苹果在AI领域的主要收购及时间（需要info_needed=true，因为尽管用户给了PDF，Planner仍希望通过网络验证/补充最新收购信息）。
- 步骤2：分析苹果进行这些收购的主要动机（info_needed=true，需要查找分析性资料）。
- 步骤3：评估这些收购对苹果公司和整个行业的影响（info_needed=true，需要查找行业报道或评论）。
- （Planner假设3步足以覆盖要求，如果LLM判断需要更多细分也可能列出4、5步，例如“介绍苹果公司AI战略背景”之类，但此例中简化为3步。）
GraphState.plan现在包含上述3个任务，pointer初始为0，Supervisor即将按顺序执行。
2. 执行步骤1 - ResearchAgent并发检索：当前pointer=0，任务1是“列出现有案例及时间线”，Supervisor看到info_needed为true，于是调用ResearchAgent。ResearchAgent根据任务描述和source_hint（假如是“Apple AI acquisitions list timeline”）构造查询。它可能进行两个并行查询：一个针对通用搜索引擎获取新闻/维基信息，另一个在用户PDF内容中搜索关键字确保不漏掉PDF已有的信息。搜索引擎返回了若干结果：如维基百科“苹果公司并购列表”，科技新闻网站的文章“苹果在AI领域的重要收购盘点”，以及用户PDF提取的文本片段。ResearchAgent异步抓取维基页面和新闻文章全文，同时解析用户PDF的内容（利用OCR或PDF解析库）提取其中的收购列表数据。
几秒内，ResearchAgent拿到了相关内容：包括苹果自2010年至2023年的AI相关收购列表（例如2010:Siri, 2014:Novauris, 2016:Turi, 2020:Xnor.ai, 2023:WaveOne等）及每项简要介绍。它将这些数据向量化存入vector_index，并挑选其中最重要的事件加入chapter_bucket[1]。接着调用LLM总结要点：由于资料较多，它让LLM列出5条覆盖整个时间线的关键收购。Ledger条目1生成，包含可能如下5个bullet：
- 2010年4月，Apple收购Siri初创公司，将语音助手技术纳入iPhone生态【来源: WSJ 2010】。
- 2016年，Apple以约2亿美元收购机器学习公司Turi，获取数据建模技术及人才【来源: TechCrunch】。
- 2020年1月，Apple收购了专注边缘AI的初创公司Xnor.ai，增强设备端AI处理能力【来源: CNBC】。
- 此外，Apple还收购了几家与AR/计算机视觉相关的AI公司（如2015年收购FaceShift；2018年收购Silk Labs）扩展AI应用领域【来源: Wiki】。
- 截至2023年，Apple在AI领域累计并购超过20家企业，显示出持续投入以保持技术领先【来源: Bloomberg】。
每条都附带了来源引用（ResearchAgent根据抓取文章确定，比如WSJ华尔街日报、TechCrunch等）。ResearchAgent将此ledger[0]写入GraphState。Supervisor标记ResearchAgent完成。
3. 执行步骤1 - ReasonerAgent分析：Supervisor接手后，调用ReasonerAgent处理步骤1结果。ReasonerAgent加载任务描述“列出案例及时间”，以及ledger[0]这5条要点。它检查这些要点是否全面：发现提及了2010、2016、2020年的例子，还有一些泛指和统计。这基本涵盖了主要收购，但Reasoner注意到可能漏了最新的2023年收购具体名字（WaveOne没在bullet明确提）。于是ReasonerAgent在输出时做两件事：(a) 综合整理时间线摘要，(b) 提出补充请求。首先它用LLM把5条要点糅合成一段章节总结：“自2010年收购Siri起，苹果陆续并购了二十多家AI相关公司，包括2016年的Turi和2020年的Xnor.ai等，持续借助收购来加强其AI技术储备。” 然后，Reasoner检查是否需要新信息——它觉得缺少2023年的具体收购案细节，于是生成一个new_task建议：“请补充苹果在2021-2023年期间的AI收购详情”。它将status设为incomplete并连同new_task返回给Supervisor，并将章节总结写入draft_summary[1]。Memory也更新记录下“苹果2010以来AI收购>20起”等简述。
4. Supervisor插入 follow-up 任务：收到Reasoner结果，Supervisor看到有new_task。于是Supervisor将此新任务插入plan紧接当前任务之后作为步骤2（原有步骤2和3顺延变成步骤3、4）。新任务描述为“补充苹果2021-2023年的AI收购案例细节”，info_needed当然为true。Supervisor将当前任务1标记为“pending-followup”（因为还需补充），pointer保持不变（仍指向插入的任务，即现在的步骤2）。这样系统将在完成补充任务后再回到主线。
5. 执行补充任务（新步骤2）：Supervisor调用ResearchAgent处理新插入的步骤2。ResearchAgent针对“2021-2023 苹果 AI 收购”展开快速搜索。它找到了一些新闻汇总提到苹果最近收购了AI初创公司WaveOne（2023年，用于视频压缩AI）、Vilynx（2020年末，视频AI）、以及对其他AI团队的小型收购。由于这些属于最新内容，用户PDF未涵盖，但网上新闻有提及。ResearchAgent抓取相关报道，很快得到WaveOne和Vilynx两个案例详述以及统计数字更新。它生成ledger条目2，bullet可能有：
- 2020年末，Apple收购了视频AI公司Vilynx，据报道价格约5000万美元，用于提升Apple的软件智能【来源: Axios】。
- 2023年，Apple收购了AI视频压缩初创公司WaveOne，持续深化其在人工智能和媒体处理领域的布局【来源: TechCrunch】。
- ...（如有其他近年案例一并列出）...
- 这些近年的收购进一步证明苹果在AI领域的收购步伐并未放缓，而是聚焦于关键技术（如高效AI算法）【来源: TechCrunch】。
ResearchAgent将此ledger写入，Supervisor再调ReasonerAgent分析。ReasonerAgent看到这是补充信息，作用是完善之前的时间线章节，所以它会更新draft_summary[1]或补充说明。可能Reasoner将这些新bullet综合后，更新先前memory的统计：“直到2023年苹果仍有针对AI的新收购（如WaveOne），持续保持投入。” 它认定此补充任务完成了缺口，因此返回status=complete，无新任务。Supervisor因此把这补充任务标记completed，pointer向前进1。现在pointer又指回原主线的步骤1（因为任务1还未真正完结）。
6. 完成步骤1：Supervisor在补充任务完成后，回到任务1上下文。现在关于“收购时间线”的信息已经完整（包含到2023）。Supervisor可以再次调用ReasonerAgent更新任务1的状态，或者直接判断补充信息已加入draft_summary[1]。通常，可以设计为ReasonerAgent在补充任务完成时就去更新主任务1的draft_summary，使其包含全部信息。最终Supervisor将任务1标记为completed，pointer递增，指向原步骤2（现在是plan中的步骤3，任务“分析动机”）。
7. 执行步骤3（原步骤2）- ResearchAgent：现在任务是分析苹果收购动机。Supervisor调用ResearchAgent。ResearchAgent据source_hint搜索相关分析文章，例如科技媒体对苹果收购战略的解读、专家评论苹果为何收购AI公司等。它并行抓取到一篇Forbes的分析文章、一篇彭博社的评论，以及苹果官方发布的一些收购声明等。综合这些，ResearchAgent产出ledger：
- 苹果收购AI公司的主要目的之一是将新技术整合到自身产品中，提升功能和用户体验【来源: Forbes】。
- 收购也被苹果用来获取AI人才（Acqui-hire），在竞争激烈的人才市场快速组建强大团队【来源: Wired】。
- 部分收购具有防御性质，防止潜在竞争对手抢占关键技术或市场先机【来源: Bloomberg】。
- ...（可能还有其他动机如数据获取、生态扩张）...
- 苹果高层多次强调通过收购“小型创新公司”来加速产品开发，这是其整体战略的一部分【来源: Apple 官方声明】。
ResearchAgent写入ledger[任务3]，Supervisor再调ReasonerAgent。
8. 执行步骤3 - ReasonerAgent：ReasonerAgent读取动机分析的要点，LLM进行推理：这些点是否回答了“主要动机”？基本涵盖技术、人才、竞争、防御。Reasoner可能觉得足够全面，无明显缺口，于是将这些点整合为段落：“苹果进行AI收购主要出于三方面考虑：一是获取新技术和人才以保持产品创新；二是将收购作为战略防御以防竞争威胁；三是加速构建自己的AI能力生态。” 它写入draft_summary[3]这样一段话。Memory更新加入“苹果收购动机=技术+人才+防御”要素。由于信息充分，Reasoner返回status=complete，无新任务。Supervisor将任务3标记completed，pointer前进。
9. 执行步骤4（原步骤3）- ResearchAgent：最后任务是评估影响。Supervisor调用ResearchAgent。ResearchAgent搜索新闻和报告，看苹果这些年收购AI公司对自身产品（如Siri改进、iPhone功能增强）以及对AI行业（并购竞争、初创生态）有何影响。获取到资料后产出ledger：
- 苹果的收购加速了其产品AI功能的发展，如Siri通过Siri公司的技术成为智能助手领域的标杆【来源: TechCrunch】。
- 苹果大规模AI并购在行业内引发“抢购”风潮，其他科技巨头也纷纷通过收购布局AI，初创公司估值水涨船高【来源: MIT Tech Review】。
- 有观点认为苹果的封闭生态加上收购，会使一些AI技术不公开分享，可能放缓开源AI社区的进展【来源: VentureBeat】。
- 苹果通过并购在人工智能芯片、边缘计算等领域建立了领先优势，巩固了其市场地位，同时其竞争对手被迫提高投入【来源: Bloomberg】。
- ...（可能还提行业监管者对此类并购的关注，但若非重点可略）...
ReasonerAgent随即分析这些要点：
- 它综合出结论：“苹果的AI并购为其产品注入了关键技术，使其AI能力提升；同时在行业层面引发连锁反应，推动AI领域投资加速，但也引来关于创新封闭的讨论。”
- 检查有无缺失：大体全面，无新任务。写入draft_summary[4]，memory更新“影响=苹果产品增强+行业跟进效仿+引发讨论”之类。
Supervisor标记任务4完成，pointer越过最后任务。
10. SynthesizerAgent 写作输出：现在GraphState已具备：每章的draft_summary、引用资料、global memory等。Supervisor调用SynthesizerAgent开始组稿。SynthesizerAgent先生成引言（可选）：根据memory，它知道本文涉及苹果AI并购的概览、动机、影响，于是写一段总引：“本报告将探讨苹果公司在人工智能领域的并购历程，分析其背后动机及由此产生的影响。” 引言完成后，进入章节生成：
- 第1章（并购概览）：SynthesizerAgent加载memory和draft_summary[1]（时间线总结）以及chapter_bucket[1]（主要收购事件片段）。然后生成文字：列出2010起的关键收购及年份，用列表呈现，每条后附上ResearchAgent提供的来源引用标记。例如“Siri【1】、Turi【2】、Xnor.ai【3】…”等。它确保按照时间顺序，语言流畅并引用恰当。由于ReasonerAgent的summary提到“超过20家”，SynthesizerAgent在结尾加一句总结强调数量与趋势【1†】【3†】。系统使用citation_map将【1】映射成例如WSJ 2010的文献，在最终Markdown里作为脚注引用。
- 第2章（收购动机）：SynthesizerAgent加载memory（含第一章大概）和draft_summary[3]（动机总结），再加上bucket[3]（可能包括苹果CEO访谈片段等）。模型据此撰写第二章。它将三大动机逐条详述，用小序号或小标题组织段落，使结构清晰。同时引用前面ResearchAgent找到的证据来源，如苹果高管的话或业界分析报告。例如写到获取人才时，引用Wired文章【4】；写到防御性收购时引用彭博社【5】。生成文本过程中模型根据需要调用vector_index工具找到相关语句填充，比如加入一句苹果高管在某发布会说过的话并标注来源。最终第二章较为完整地解释了苹果的战略意图。
- 第3章（影响评估）：SynthesizerAgent同理使用draft_summary[4]和bucket[4]内容撰写。它平衡描述积极影响（产品进步、领先优势）和潜在负面（对行业格局影响），并援引先前找的行业评论作为支撑。例如引用MIT Tech Review关于投资热潮的分析【6】、VentureBeat关于开源影响的评论【7】等。末尾总结苹果的并购对自身和行业的综合影响，引用两三个权威结论。
- 结论：SynthesizerAgent最后基于memory撰写结论段落。它重申苹果通过持续收购巩固了AI版图，并指出这可能预示未来科技巨头在AI领域竞争仍以并购为策略之一。这个结论与引言呼应，给读者以完整闭环。
整个写作过程中，每当模型给出某一具体事实句子，系统就查找对应来源并标注引用，从而边写边引。随着各章文本陆续生成，SynthesizerAgent将它们组装起来，加上开头的标题和目录（如需要，可自动插入目录MD语法），形成最终的Markdown文档流。CritiqueAgent复审：在得到完整初稿后，系统让CritiqueAgent快速浏览一遍。比如CritiqueAgent检查引用匹配，发现第1章Bullet里“FaceShift”那条未列引用，它建议补充来源；又或者发现第二章第三点措辞稍显重复，给出修改意见。系统应用了这些小改动，确保每条事实都有引用，语言更顺畅。
11. 导出与呈现：最终Markdown定稿后，系统执行多格式导出：生成一个PDF文件和对应的参考文献页码；创建一个Google Docs文档方便协作编辑；同时生成简报幻灯的初稿（比如10页的要点PPT）。用户在界面上收到报告文本（富文本渲染的Markdown），可以点击下载PDF或打开Google Docs链接查看，也可以播放语音朗读整份报告。报告开头有引言概述，正文按要求详细分析了苹果的AI收购案例并插入了丰富的来源引用。用户如果对某点细节有疑问，可以查看对应引用文献，例如点击【2】跳转到TechCrunch文章原文片段。这种透明的引文让报告更具可信度。整个案例流程从用户提出问题到拿到高质量报告，仅需用户等待几分钟，所有繁琐的信息查找、筛选、写作都由LangGraph多代理体系自动完成。

---
通过以上案例，可以直观地看到LangGraph多代理架构如何协同工作：Planner拆解任务、ResearchAgent快搜快找、ReasonerAgent深思补漏、SynthesizerAgent妙笔生花，最后CritiqueAgent再把关优化，每一步各尽其职又互相补充。正是这种模块化串联和智能调度，使得AI能够胜任复杂的调研写作任务，并产出专业水准的交付成果。这套架构对于需要自动化深入研究、报告生成的应用（如市场分析、技术白皮书撰写等）具有普遍参考价值。开发者也可以根据本架构基础，定制各代理的实现细节或增加特殊功能（例如加入一个针对数据的ChartAgent绘制图表等），以适应不同场景需求。总之，LangGraph多代理架构为复杂任务的AI求解提供了清晰的流程范式和强大的扩展能力。