import os
import json
from typing import List

from agent.tools_and_schemas import SearchQueryList, Reflection, ResearchPlan, LedgerEntry
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langgraph.types import Send
from langgraph.graph import StateGraph
from langgraph.graph import START, END
from langchain_core.runnables import RunnableConfig
from google.genai import Client

from agent.state import (
    OverallState,
    QueryGenerationState,
    ReflectionState,
    WebSearchState,
)
from agent.configuration import Configuration
from agent.prompts import (
    get_current_date,
    query_writer_instructions,
    web_searcher_instructions,
    reflection_instructions,
    answer_instructions,
    planning_instructions,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from agent.utils import (
    get_citations,
    get_research_topic,
    insert_citation_markers,
    resolve_urls,
)

load_dotenv()

if os.getenv("GEMINI_API_KEY") is None:
    raise ValueError("GEMINI_API_KEY is not set")

# Used for Google Search API
genai_client = Client(api_key=os.getenv("GEMINI_API_KEY"))


# Nodes
def generate_query(state: OverallState, config: RunnableConfig) -> QueryGenerationState:
    """LangGraph node that generates search queries based on the current research task from the plan."""
    configurable = Configuration.from_runnable_config(config)

    # check for custom initial search query count
    if state.get("initial_search_query_count") is None:
        state["initial_search_query_count"] = configurable.number_of_initial_queries

    # init Gemini 2.0 Flash
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(SearchQueryList)

    # New logic: prioritize generating queries based on current plan task
    plan = state.get("plan")
    pointer = state.get("current_task_pointer")
    if plan and pointer is not None and pointer < len(plan):
        research_topic = plan[pointer]["description"]
    else:
        # Fallback to user_query or messages
        research_topic = state.get("user_query") or get_research_topic(state["messages"])

    current_date = get_current_date()
    formatted_prompt = query_writer_instructions.format(
        current_date=current_date,
        research_topic=research_topic,
        number_queries=state["initial_search_query_count"],
    )
    result = structured_llm.invoke(formatted_prompt)
    return {"query_list": result.query}


def continue_to_web_research(state: QueryGenerationState):
    """LangGraph node that sends the search queries to the web research node.

    This is used to spawn n number of web research nodes, one for each search query.
    """
    return [
        Send("web_research", {"search_query": search_query, "id": int(idx)})
        for idx, search_query in enumerate(state["query_list"])
    ]


def web_research(state: WebSearchState, config: RunnableConfig) -> OverallState:
    """LangGraph node that performs web research using the native Google Search API tool.

    Executes a web search using the native Google Search API tool in combination with Gemini 2.0 Flash.

    Args:
        state: Current graph state containing the search query and research loop count
        config: Configuration for the runnable, including search API settings

    Returns:
        Dictionary with state update, including sources_gathered, research_loop_count, and web_research_results
    """
    # Configure
    configurable = Configuration.from_runnable_config(config)
    formatted_prompt = web_searcher_instructions.format(
        current_date=get_current_date(),
        research_topic=state["search_query"],
    )

    # Uses the google genai client as the langchain client doesn't return grounding metadata
    response = genai_client.models.generate_content(
        model=configurable.query_generator_model,
        contents=formatted_prompt,
        config={
            "tools": [{"google_search": {}}],
            "temperature": 0,
        },
    )
    # resolve the urls to short urls for saving tokens and time
    resolved_urls = resolve_urls(
        response.candidates[0].grounding_metadata.grounding_chunks, state["id"]
    )
    # Gets the citations and adds them to the generated text
    citations = get_citations(response, resolved_urls)
    modified_text = insert_citation_markers(response.text, citations)
    sources_gathered = [item for citation in citations for item in citation["segments"]]

    return {
        "sources_gathered": sources_gathered,
        "executed_search_queries": [state["search_query"]],
        "web_research_result": [modified_text],
    }


def reflection(state: OverallState, config: RunnableConfig) -> ReflectionState:
    """LangGraph node that identifies knowledge gaps and generates potential follow-up queries.

    Analyzes the current summary to identify areas for further research and generates
    potential follow-up queries. Uses structured output to extract
    the follow-up query in JSON format.

    Args:
        state: Current graph state containing the running summary and research topic
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including search_query key containing the generated follow-up query
    """
    configurable = Configuration.from_runnable_config(config)
    # Increment the research loop count and get the reasoning model
    state["research_loop_count"] = state.get("research_loop_count", 0) + 1
    reasoning_model = state.get("reasoning_model") or configurable.reflection_model

    # Format the prompt
    current_date = get_current_date()
    
    # 获取当前任务描述作为 research_topic
    plan = state.get("plan")
    pointer = state.get("current_task_pointer")
    if plan and pointer is not None and pointer < len(plan):
        research_topic = plan[pointer]["description"]
    else:
        research_topic = state.get("user_query") or get_research_topic(state["messages"])
    
    formatted_prompt = reflection_instructions.format(
        current_date=current_date,
        research_topic=research_topic,
        summaries="\n\n---\n\n".join(state["web_research_result"]),
    )
    # init Reasoning Model
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    result = llm.with_structured_output(Reflection).invoke(formatted_prompt)

    return {
        "is_sufficient": result.is_sufficient,
        "knowledge_gap": result.knowledge_gap,
        "follow_up_queries": result.follow_up_queries,
        "research_loop_count": state["research_loop_count"],
        "number_of_ran_queries": len(state["executed_search_queries"]),
    }


def evaluate_research(
    state: ReflectionState,
    config: RunnableConfig,
) -> OverallState:
    """LangGraph routing function that determines the next step in the research flow.

    Controls the research loop by deciding whether to continue gathering information
    or to complete the current task based on the configured maximum number of research loops.

    Args:
        state: Current graph state containing the research loop count
        config: Configuration for the runnable, including max_research_loops setting

    Returns:
        Send objects for continued research or routing to task completion
    """
    configurable = Configuration.from_runnable_config(config)
    max_research_loops = (
        state.get("max_research_loops")
        if state.get("max_research_loops") is not None
        else configurable.max_research_loops
    )
    if state["is_sufficient"] or state["research_loop_count"] >= max_research_loops:
        return "record_task_completion"
    else:
        return [
            Send(
                "web_research",
                {
                    "search_query": follow_up_query,
                    "id": state["number_of_ran_queries"] + int(idx),
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


def finalize_answer(state: OverallState, config: RunnableConfig):
    """LangGraph node that finalizes the research summary using accumulated findings from all completed tasks.

    Uses the ledger and global summary memory to create a comprehensive answer
    that synthesizes findings from all completed research tasks.

    Args:
        state: Current graph state containing accumulated research findings
        config: Configuration for the runnable

    Returns:
        Dictionary with state update, including final answer message and sources
    """
    configurable = Configuration.from_runnable_config(config)
    reasoning_model = state.get("reasoning_model") or configurable.answer_model

    # Format the prompt using accumulated knowledge
    current_date = get_current_date()
    research_topic = state.get("user_query") or get_research_topic(state["messages"])
    
    # Use accumulated findings from ledger and global memory
    ledger_entries = state.get("ledger", [])
    global_memory = state.get("global_summary_memory", [])
    
    # Prepare consolidated findings for the prompt
    if ledger_entries:
        # Use structured ledger entries for detailed findings
        consolidated_findings = "\n\n".join([
            f"Task: {entry['description']}\nFindings: {entry['findings_summary']}"
            for entry in ledger_entries
        ])
    elif global_memory:
        # Fallback to global memory if ledger is empty
        consolidated_findings = "\n\n".join(global_memory)
    else:
        # Final fallback to raw web research results
        consolidated_findings = "\n---\n".join(state.get("web_research_result", []))

    formatted_prompt = f"""Generate a comprehensive answer to the user's research question based on the accumulated findings from multiple research tasks.

Current date: {current_date}
Research question: {research_topic}

Accumulated research findings:
{consolidated_findings}

Please provide a well-structured, comprehensive answer that synthesizes all the findings above. Include proper citations where available and ensure the response directly addresses the original research question.

Final Answer:"""

    # Initialize reasoning model
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    result = llm.invoke(formatted_prompt)

    # Replace the short urls with the original urls and add all used urls to the sources_gathered
    unique_sources = []
    for source in state.get("sources_gathered", []):
        if source["short_url"] in result.content:
            result.content = result.content.replace(
                source["short_url"], source["value"]
            )
            unique_sources.append(source)

    return {
        "messages": [AIMessage(content=result.content)],
        "sources_gathered": unique_sources,
    }


def planner_node(state: OverallState, config: RunnableConfig) -> dict:
    """LangGraph node that generates a multi-step research plan based on the user's question."""
    configurable = Configuration.from_runnable_config(config)
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=0.7,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(ResearchPlan)

    # Get user query, prioritize from user_query, fallback to messages
    user_query = state.get("user_query") or get_research_topic(state["messages"])
    
    # Use centrally managed planning prompt
    formatted_prompt = planning_instructions.format(user_query=user_query)
    
    try:
        result = structured_llm.invoke(formatted_prompt)
        # Convert ResearchPlan to expected format
        plan = [{"id": task.id, "description": task.description, "info_needed": True, "source_hint": task.description, "status": "pending"} for task in result.tasks]
        
        return {
            "user_query": user_query,
            "plan": plan,
            "current_task_pointer": 0
        }
    except Exception as e:
        print(f"Planning failed: {e}")
        # Provide default single-task plan as fallback
        return {
            "user_query": user_query,
            "plan": [{"id": "task-1", "description": f"Research and answer: {user_query}", "info_needed": True, "source_hint": user_query, "status": "pending"}],
            "current_task_pointer": 0
        }


def record_task_completion_node(state: OverallState, config: RunnableConfig) -> dict:
    """LangGraph node that records completion of the current task and updates ledger and memory."""
    current_pointer = state.get("current_task_pointer", 0)
    plan = state.get("plan", [])
    
    if current_pointer >= len(plan):
        # This shouldn't happen, but handle gracefully
        return {"current_task_pointer": current_pointer}
    
    current_task = plan[current_pointer]
    
    # Generate task summary from web research results
    # For Day 2 simplification, use the most recent reflection insights
    task_findings_summary = _summarize_task_findings(
        current_task["description"], 
        state.get("web_research_result", []),
        config
    )
    
    # Create ledger entry
    ledger_entry = {
        "task_id": current_task["id"],
        "description": current_task["description"], 
        "findings_summary": task_findings_summary
    }
    
    # Update plan status
    updated_plan = list(plan)
    updated_plan[current_pointer]["status"] = "completed"
    
    # Increment task pointer
    next_pointer = current_pointer + 1
    
    return {
        "ledger": [ledger_entry],  # Will be appended via operator.add
        "global_summary_memory": [task_findings_summary],  # Will be appended via operator.add
        "plan": updated_plan,  # Replace the plan with updated status
        "current_task_pointer": next_pointer  # Move to next task
    }


def _summarize_task_findings(task_description: str, web_results: List[str], config: RunnableConfig) -> str:
    """Helper function to summarize web research results for a specific task."""
    if not web_results:
        return f"No specific findings available for task: {task_description}"
    
    # Use recent results (last 3 entries) to avoid overwhelming context
    recent_results = web_results[-3:] if len(web_results) > 3 else web_results
    context_to_summarize = "\n---\n".join(recent_results)
    
    configurable = Configuration.from_runnable_config(config)
    llm = ChatGoogleGenerativeAI(
        model=configurable.reflection_model,
        temperature=0.3,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    
    prompt = f"""Given the research task: "{task_description}"

And the following research findings:
{context_to_summarize}

Please provide a concise summary (1-2 sentences) of the key findings that directly address this specific task.

Task Summary:"""
    
    try:
        response = llm.invoke(prompt)
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        print(f"Task summarization failed: {e}")
        return f"Completed research for: {task_description}"


def decide_next_step_in_plan(state: OverallState) -> str:
    """Conditional edge function that determines whether to continue with next task or finalize."""
    current_pointer = state.get("current_task_pointer", 0)
    plan = state.get("plan", [])
    
    if current_pointer < len(plan):
        print(f"--- Moving to next task (pointer: {current_pointer}) ---")
        return "generate_query"
    else:
        print("--- All tasks completed. Finalizing answer ---")
        return "finalize_answer"


# Create our Agent Graph
builder = StateGraph(OverallState, config_schema=Configuration)

# Define the nodes we will cycle between
builder.add_node("planner", planner_node)
builder.add_node("generate_query", generate_query)
builder.add_node("web_research", web_research)
builder.add_node("reflection", reflection)
builder.add_node("record_task_completion", record_task_completion_node)  # New node for Day 2
builder.add_node("finalize_answer", finalize_answer)

# Set the entrypoint as `planner`
builder.add_edge(START, "planner")
builder.add_edge("planner", "generate_query")

# Add conditional edge to continue with search queries in a parallel branch
builder.add_conditional_edges(
    "generate_query", continue_to_web_research, ["web_research"]
)

# Reflect on the web research
builder.add_edge("web_research", "reflection")

# Evaluate the research - now routes to either more research or task completion
builder.add_conditional_edges(
    "reflection", evaluate_research, ["web_research", "record_task_completion"]
)

# After recording task completion, decide next step in plan (multi-task loop)
builder.add_conditional_edges(
    "record_task_completion", 
    decide_next_step_in_plan, 
    ["generate_query", "finalize_answer"]
)

# Finalize the answer
builder.add_edge("finalize_answer", END)

graph = builder.compile(name="pro-search-agent")
