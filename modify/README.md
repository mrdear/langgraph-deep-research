# Gemini-fullstack-langgraph-quickstart 实施日志

## DAY 0（当前项目状态）

- 项目已成功运行，前后端联通。
- 基础的自动化研究代理功能已实现：
  - 用户可通过前端输入问题，后端基于 LangGraph 流程自动生成搜索查询，调用 Gemini API 进行网页检索。
  - 检索结果经过 LLM 处理，自动生成带引用的答案。
- 搜索与反思流程正常，引用链路可追溯。
- 支持多轮对话，历史消息可追溯。
- 依赖环境（uv/venv）、API Key 配置、前端构建等均已调通。

---

后续将以 DAY 1、DAY 2、DAY 3... 的方式，逐步记录每一次架构扩展、功能增强和关键变更。

- DAY 1：引入显式规划与任务化研究流程（详见 Day1.md，实施完成后将在此记录变更与测试结果）
- DAY 2：......
- DAY 3：......

> 本项目的长期目标是逐步实现 DeepResearch 方案（详见 Reference.md），每一步都确保可运行、可回滚。

---

## DAY 1（引入显式规划与任务化研究流程）

- 新增 planner_node 节点，基于用户问题自动生成结构化多步骤研究计划（plan），每步为一个可执行任务。
- 扩展 OverallState，增加 user_query、plan、current_task_pointer 字段，支持任务化流程。
- generate_query 节点改造为基于当前 plan 任务生成具体搜索查询。
- LangGraph 主流程调整为：planner_node -> generate_query -> web_research ...，为后续多任务循环奠定基础。

**修复与优化：**
- 修复了 planner_node 的异常问题，采用 `llm.with_structured_output(ResearchPlan)` 代替手动 JSON 解析。
- 优化了 user_query 字段的获取逻辑，支持从 messages 回退获取。
- 统一了字段名引用（search_query -> executed_search_queries），确保各节点间状态一致性。
- 修复了 reflection 和 finalize_answer 节点中的配置字段名错误（reasoning_model -> reflection_model/answer_model）。
- 修复了模型配置问题，将所有默认模型改为 gemini-2.0-flash（免费版本），避免配额限制错误。
- **深度优化 Planning Prompt**：基于 Reference.md 的 DeepResearch 架构设计，重新设计了专业的规划提示词，包含详细的任务分解原则、输出格式规范和示例，并将其统一管理到 prompts.py 中。
- 已本地测试通过，前后端联调无异常，单任务流程可用。
- 下一步将继续完善多任务循环与更复杂的推理流程。

## DAY 2 (Multi-Task Loop & Knowledge Accumulation)

- **Multi-Task Loop Implementation**: Fully implemented the multi-task iteration mechanism allowing the agent to process all tasks in the generated plan sequentially.
- **State Enhancements**: Extended OverallState with:
  - `ledger`: Structured records of completed task findings (LedgerEntry objects)
  - `global_summary_memory`: Cross-task memory accumulation for context preservation
- **New Nodes**:
  - `record_task_completion_node`: Records task completion, updates ledger and memory, increments task pointer
  - `decide_next_step_in_plan`: Conditional routing function determining whether to continue with next task or finalize
- **Flow Restructuring**: 
  - evaluate_research → record_task_completion → decide_next_step_in_plan
  - Conditional routing: next task (generate_query) or completion (finalize_answer)
- **Enhanced Final Answer**: finalize_answer now synthesizes accumulated findings from all completed tasks using ledger entries and global memory
- **Robust Task Summarization**: Each completed task generates a concise summary that feeds into the next iteration
- Successfully tested: Graph compiles without errors, multi-task flow logic verified
- Next: Advanced reasoning capabilities and dynamic task planning

**Hotfixes after initial testing**:
- Fixed loop termination issue: adjusted `max_research_loops` default from 2 to 3 (preventing excessive loops while allowing adequate research)
- Note: `gemini-2.5-flash-preview-04-17` is free tier with RPM limitations, working correctly for current usage
- Validated Day 2 implementation with simple weather query: ledger, global memory, and multi-task flow working correctly  
- Loop termination conditions: (1) LLM deems information sufficient OR (2) reaches max 3 research loops per task
- **Issue to investigate**: Test results showed `max_research_loops: 22` despite config default of 3, may be overridden by environment variable or runtime parameter

---
