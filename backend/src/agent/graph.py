import os
import json
from typing import List
from datetime import datetime

from agent.tools_and_schemas import SearchQueryList, Reflection, ResearchPlan, LedgerEntry
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langgraph.types import Send
from langgraph.graph import StateGraph
from langgraph.graph import START, END
from langchain_core.runnables import RunnableConfig
from google.genai import Client
import tiktoken  # 需确保环境已安装 tiktoken

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
    
    return {
        "query_list": result.query,
        "plan": state.get("plan", []),
        "current_task_pointer": state.get("current_task_pointer", 0)
    }


def continue_to_web_research(state: QueryGenerationState):
    """LangGraph node that sends the search queries to the web research node.

    This is used to spawn n number of web research nodes, one for each search query.
    """
    # Get current task info
    plan = state.get("plan", [])
    current_pointer = state.get("current_task_pointer", 0)
    current_task_id = "unknown"
    
    if plan and current_pointer < len(plan):
        current_task_id = plan[current_pointer]["id"]
    
    return [
        Send("web_research", {
            "search_query": search_query, 
            "id": int(idx),
            "current_task_id": current_task_id
        })
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
    try:
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
        
        # Error handling for empty response
        if not response.candidates or not response.candidates[0].grounding_metadata:
            current_task_id = state.get("current_task_id", "unknown")
            error_content = f"No results found for query: {state['search_query']}"
            
            detailed_finding = {
                "task_id": current_task_id,
                "query_id": state["id"],
                "content": error_content,
                "source": None,
                "timestamp": datetime.now().isoformat()
            }
            
            task_specific_result = {
                "task_id": current_task_id,
                "content": error_content,
                "sources": [],
                "timestamp": datetime.now().isoformat()
            }
            
            return {
                "sources_gathered": [],
                "executed_search_queries": [state["search_query"]],
                "web_research_result": [error_content],
                "current_task_detailed_findings": [detailed_finding],
                "task_specific_results": [task_specific_result]
            }

        # resolve the urls to short urls for saving tokens and time
        resolved_urls = resolve_urls(
            response.candidates[0].grounding_metadata.grounding_chunks, state["id"]
        )
        
        # Gets the citations and adds them to the generated text
        citations = get_citations(response, resolved_urls)
        modified_text = insert_citation_markers(response.text, citations)
        sources_gathered = [item for citation in citations for item in citation["segments"]]

        # Create detailed findings entry with task ID
        current_task_id = state.get("current_task_id", "unknown")
        detailed_finding = {
            "task_id": current_task_id,
            "query_id": state["id"],
            "content": modified_text,
            "source": sources_gathered[0] if sources_gathered else None,
            "timestamp": datetime.now().isoformat()
        }

        # Add task-specific metadata to the research result
        task_specific_result = {
            "task_id": current_task_id,
            "content": modified_text,
            "sources": sources_gathered,
            "timestamp": datetime.now().isoformat()
        }

        return {
            "sources_gathered": sources_gathered,
            "executed_search_queries": [state["search_query"]],
            "web_research_result": [modified_text],
            "current_task_detailed_findings": [detailed_finding],
            "task_specific_results": [task_specific_result]
        }
    except Exception as e:
        # Error handling for API or processing errors
        current_task_id = state.get("current_task_id", "unknown")
        error_message = f"Error during web research: {str(e)}"
        
        detailed_finding = {
            "task_id": current_task_id,
            "query_id": state["id"],
            "content": error_message,
            "source": None,
            "timestamp": datetime.now().isoformat()
        }
        
        task_specific_result = {
            "task_id": current_task_id,
            "content": error_message,
            "sources": [],
            "timestamp": datetime.now().isoformat()
        }
        
        return {
            "sources_gathered": [],
            "executed_search_queries": [state["search_query"]],
            "web_research_result": [error_message],
            "current_task_detailed_findings": [detailed_finding],
            "task_specific_results": [task_specific_result]
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
        "plan": state.get("plan", []),
        "current_task_pointer": state.get("current_task_pointer", 0)
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
        # Get current task info
        plan = state.get("plan", [])
        current_pointer = state.get("current_task_pointer", 0)
        current_task_id = "unknown"
        
        if plan and current_pointer < len(plan):
            current_task_id = plan[current_pointer]["id"]
        
        return [
            Send(
                "web_research",
                {
                    "search_query": follow_up_query,
                    "id": state["number_of_ran_queries"] + int(idx),
                    "current_task_id": current_task_id
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


def split_by_tokens(texts, max_tokens=100000, encoding_name="cl100k_base"):
    """将文本列表按最大token数分批。"""
    enc = tiktoken.get_encoding(encoding_name)
    batches = []
    current_batch = []
    current_tokens = 0
    for text in texts:
        tokens = len(enc.encode(text))
        if current_tokens + tokens > max_tokens and current_batch:
            batches.append(current_batch)
            current_batch = [text]
            current_tokens = tokens
        else:
            current_batch.append(text)
            current_tokens += tokens
    if current_batch:
        batches.append(current_batch)
    return batches


def finalize_answer(state: OverallState, config: RunnableConfig) -> dict:
    """Generate the final research report by synthesizing all task findings, using batch generation for detailed content."""
    try:
        configurable = Configuration.from_runnable_config(config)
        llm = ChatGoogleGenerativeAI(
            model=configurable.answer_model,
            temperature=0.7,
            max_retries=2,
            api_key=os.getenv("GEMINI_API_KEY"),
        )

        plan = state.get("plan", [])
        ledger = state.get("ledger", [])
        task_specific_results = state.get("task_specific_results", [])
        if not plan or not ledger:
            return {
                "messages": [AIMessage(content="Error: No research plan or findings available")],
                "final_report_markdown": "No research findings available."
            }

        ledger_map = {entry["task_id"]: entry for entry in ledger}
        task_results_map = {}
        for result in task_specific_results:
            task_id = result["task_id"]
            if task_id not in task_results_map:
                task_results_map[task_id] = []
            task_results_map[task_id].append(result)

        report_sections = []
        
        # Introduction
        intro_prompt = f"""Write ONLY a comprehensive introduction for a research report. Do not include any meta-text, instructions, or commentary.

Research Topic: {state.get('user_query', 'Not specified')}
Research Areas: {[task['description'] for task in plan]}

Write a formal introduction that:
1. States the research topic and its importance
2. Outlines the main areas of investigation  
3. Previews the key findings
4. Uses a formal, academic style

IMPORTANT: Output only the introduction text. Do not include phrases like "here is the introduction" or any meta-commentary."""

        try:
            introduction = llm.invoke(intro_prompt).content
            # Clean any potential meta-text from the response
            if introduction.lower().startswith(("here", "this is", "the following", "好的", "根据")):
                # Extract actual content after meta-text
                lines = introduction.split('\n')
                introduction = '\n'.join([line for line in lines if not any(meta in line.lower() for meta in ["here is", "this is", "好的", "根据", "以下是"])])
            report_sections.append(f"# {state.get('user_query', 'Research Report')}\n\n{introduction}\n")
        except Exception as e:
            report_sections.append(f"# {state.get('user_query', 'Research Report')}\n\n*Error generating introduction: {str(e)}*\n")

        # Section batching and generation
        for task in plan:
            task_id = task["id"]
            task_description = task["description"]
            ledger_entry = ledger_map.get(task_id)
            if not ledger_entry:
                report_sections.append(f"## {task_description}\n\n*No detailed findings available for this section.*\n")
                continue
            
            # Get task-specific results first, then fall back to web_research_result if empty
            task_results = task_results_map.get(task_id, [])
            detailed_contents = [result["content"] for result in task_results]
            
            # Fallback: if no task-specific results, use all web_research_result as content
            if not detailed_contents:
                web_research_result = state.get("web_research_result", [])
                detailed_contents = web_research_result
                print(f"Warning: No task-specific results for {task_id}, using fallback web_research_result with {len(detailed_contents)} items")
            
            if not detailed_contents:
                # If still no content, create a section with just the summary
                section_content = ledger_entry['findings_summary']
                report_sections.append(f"## {task_description}\n\n{section_content}\n")
                continue
            
            batches = split_by_tokens(detailed_contents, max_tokens=100000)
            section_content = ""
            previous_content = ""
            
            for i, batch in enumerate(batches):
                is_last = (i == len(batches) - 1)
                batched_content = "\n\n".join(batch)
                
                section_prompt = f"""Synthesize the following research information into a well-written section for a research report. 

Section Topic: {task_description}
Key Summary: {ledger_entry['findings_summary']}

Research Information to Synthesize:
{batched_content}

INSTRUCTIONS:
1. Rewrite and synthesize the information into coherent, flowing prose
2. Do NOT copy-paste raw search results or include citation markers like [vertexaisearch.cloud.google.com/...]
3. Organize information logically with clear subheadings if needed
4. Write in formal academic style using complete sentences and paragraphs
5. Focus on insights and analysis, not just listing facts
6. Remove any meta-text, instructions, or commentary from source material"""

                if previous_content:
                    section_prompt += f"\n\nPrevious section content:\n{previous_content}\n\nContinue seamlessly from the above content, avoiding repetition."
                
                if is_last:
                    section_prompt += "\n\nThis is the final batch for this section. Conclude with a brief summary paragraph."
                else:
                    section_prompt += "\n\nThis is not the final batch. Continue the section but do not conclude."

                section_prompt += "\n\nIMPORTANT: Output only the section content. No meta-text, no instructions, no commentary."

                try:
                    batch_content = llm.invoke(section_prompt).content
                    
                    # Clean any potential meta-text or unwanted content
                    if batch_content.lower().startswith(("here", "this is", "based on", "according to", "好的", "根据")):
                        lines = batch_content.split('\n')
                        batch_content = '\n'.join([line for line in lines if not any(meta in line.lower() for meta in ["here is", "this is", "好的", "根据", "以下是", "based on the"])])
                    
                    # Remove citation markers and raw URLs
                    import re
                    batch_content = re.sub(r'\[vertexaisearch\.cloud\.google\.com/id/[^\]]+\]', '', batch_content)
                    batch_content = re.sub(r'\[[a-z0-9\-]+\]', '', batch_content)
                    batch_content = re.sub(r'https?://[^\s\]]+', '', batch_content)
                    
                    section_content += batch_content + "\n"
                    previous_content = section_content
                except Exception as e:
                    section_content += f"*Error generating batch content: {str(e)}*\n"
            
            report_sections.append(f"## {task_description}\n\n{section_content}\n")

        # Conclusion
        conclusion_prompt = f"""Write ONLY a comprehensive conclusion for this research report. Do not include any meta-text, instructions, or commentary.

Research Topic: {state.get('user_query', 'Not specified')}
Key Findings by Section:
{chr(10).join([f"- {task['description']}: {ledger_map.get(task['id'], {}).get('findings_summary', 'No findings')}" for task in plan])}

Write a conclusion that:
1. Summarizes the main findings
2. Discusses implications and significance
3. Identifies areas for future research
4. Uses formal, academic style

IMPORTANT: Output only the conclusion text. Do not include phrases like "here is the conclusion" or any meta-commentary."""

        try:
            conclusion = llm.invoke(conclusion_prompt).content
            # Clean any potential meta-text from the response
            if conclusion.lower().startswith(("here", "this is", "the following", "in conclusion", "好的", "根据")):
                lines = conclusion.split('\n')
                conclusion = '\n'.join([line for line in lines if not any(meta in line.lower() for meta in ["here is", "this is", "好的", "根据", "以下是"])])
            report_sections.append(f"## Conclusion\n\n{conclusion}\n")
        except Exception as e:
            report_sections.append(f"## Conclusion\n\n*Error generating conclusion: {str(e)}*\n")

        final_report_markdown = "\n\n---\n\n".join(report_sections)
        return {
            "messages": [AIMessage(content=final_report_markdown)],
            "final_report_markdown": final_report_markdown
        }
    except Exception as e:
        error_message = f"Error generating final report: {str(e)}"
        return {
            "messages": [AIMessage(content=error_message)],
            "final_report_markdown": error_message
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
    """Record the findings for the current task and prepare for the next task."""
    try:
        # Get current task info
        plan = state.get("plan", [])
        current_pointer = state.get("current_task_pointer", 0)
        
        if not plan or current_pointer >= len(plan):
            return {
                "messages": [AIMessage(content="Error: Invalid task pointer or empty plan")],
                "next_node_decision": "end"
            }
            
        current_task = plan[current_pointer]
        current_task_id = current_task.get("id")
        
        # Get detailed findings for current task
        detailed_findings = state.get("current_task_detailed_findings", [])
        task_specific_findings = [
            finding["content"] for finding in detailed_findings 
            if finding.get("task_id") == current_task_id
        ]
        
        # If no task-specific findings found, try to get recent web results as fallback
        if not task_specific_findings:
            print(f"Warning: No task-specific findings found for task {current_task_id}, using recent web results as fallback")
            web_results = state.get("web_research_result", [])
            # Take the most recent results (assume they belong to current task)
            task_specific_findings = web_results[-3:] if len(web_results) > 3 else web_results
        
        # Generate task summary
        task_summary = _summarize_task_findings(
            current_task["description"],
            task_specific_findings,
            config
        )
        
        # Create citations from detailed findings
        citations_for_snippets = []
        for finding in detailed_findings:
            if finding.get("task_id") == current_task_id and finding.get("source"):
                citations_for_snippets.append({
                    "snippet": finding["content"],
                    "source": str(finding["source"])
                })
        
        # Create ledger entry with detailed findings
        ledger_entry = {
            "task_id": current_task_id,
            "description": current_task["description"],
            "findings_summary": task_summary,
            "detailed_snippets": task_specific_findings,
            "citations_for_snippets": citations_for_snippets
        }
        
        # Update plan status
        plan[current_pointer]["status"] = "completed"
        
        # Clear current task findings to prepare for next task
        return {
            "ledger": [ledger_entry],
            "global_summary_memory": [task_summary],
            "plan": plan,
            "current_task_pointer": current_pointer + 1,
            "current_task_detailed_findings": [],  # Clear for next task
            "next_node_decision": "continue" if current_pointer + 1 < len(plan) else "end"
        }
    except Exception as e:
        error_message = f"Error in record_task_completion_node: {str(e)}"
        print(error_message)
        return {
            "messages": [AIMessage(content=error_message)],
            "next_node_decision": "end"
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
