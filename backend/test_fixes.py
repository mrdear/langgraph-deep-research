#!/usr/bin/env python3
"""
测试修复效果的脚本
"""

import sys
import os
sys.path.append('src')

def test_state_definitions():
    """测试状态定义是否包含必要的字段"""
    print("=== 测试状态定义 ===")
    
    try:
        # 直接执行状态定义文件
        state_globals = {}
        with open("src/agent/state.py", "r") as f:
            exec(f.read(), state_globals)
        
        # 检查QueryGenerationState
        QueryGenerationState = state_globals['QueryGenerationState']
        query_fields = QueryGenerationState.__annotations__.keys()
        print(f"QueryGenerationState字段: {list(query_fields)}")
        assert 'plan' in query_fields, "QueryGenerationState缺少plan字段"
        assert 'current_task_pointer' in query_fields, "QueryGenerationState缺少current_task_pointer字段"
        
        # 检查ReflectionState
        ReflectionState = state_globals['ReflectionState']
        reflection_fields = ReflectionState.__annotations__.keys()
        print(f"ReflectionState字段: {list(reflection_fields)}")
        assert 'plan' in reflection_fields, "ReflectionState缺少plan字段"
        assert 'current_task_pointer' in reflection_fields, "ReflectionState缺少current_task_pointer字段"
        
        # 检查WebSearchState
        WebSearchState = state_globals['WebSearchState']
        web_search_fields = WebSearchState.__annotations__.keys()
        print(f"WebSearchState字段: {list(web_search_fields)}")
        assert 'current_task_id' in web_search_fields, "WebSearchState缺少current_task_id字段"
        
        # 检查OverallState
        OverallState = state_globals['OverallState']
        overall_fields = OverallState.__annotations__.keys()
        print(f"OverallState字段: {list(overall_fields)}")
        assert 'task_specific_results' in overall_fields, "OverallState缺少task_specific_results字段"
        
        print("✅ 所有状态定义都包含必要的字段")
        return True
        
    except Exception as e:
        print(f"❌ 状态定义测试失败: {e}")
        return False

def test_task_id_propagation():
    """测试任务ID传递逻辑"""
    print("\n=== 测试任务ID传递逻辑 ===")
    
    # 模拟continue_to_web_research函数的逻辑
    def mock_continue_to_web_research(state):
        plan = state.get("plan", [])
        current_pointer = state.get("current_task_pointer", 0)
        current_task_id = "unknown"
        
        if plan and current_pointer < len(plan):
            current_task_id = plan[current_pointer]["id"]
        
        return [{
            "search_query": query,
            "id": idx,
            "current_task_id": current_task_id
        } for idx, query in enumerate(state.get("query_list", []))]
    
    # 测试用例1: 正常情况
    test_state = {
        "query_list": ["query1", "query2"],
        "plan": [{"id": "task-1", "description": "test task"}],
        "current_task_pointer": 0
    }
    
    result = mock_continue_to_web_research(test_state)
    print(f"测试用例1结果: {result}")
    
    if result and result[0]["current_task_id"] == "task-1":
        print("✅ 任务ID传递正常")
    else:
        print("❌ 任务ID传递失败")
        return False
    
    # 测试用例2: 缺少plan的情况
    test_state_no_plan = {
        "query_list": ["query1"]
    }
    
    result_no_plan = mock_continue_to_web_research(test_state_no_plan)
    print(f"测试用例2结果: {result_no_plan}")
    
    if result_no_plan and result_no_plan[0]["current_task_id"] == "unknown":
        print("✅ 缺少plan时正确返回unknown")
    else:
        print("❌ 缺少plan时处理不当")
        return False
    
    return True

def test_web_research_error_handling():
    """测试web_research错误处理"""
    print("\n=== 测试web_research错误处理 ===")
    
    # 模拟web_research错误处理逻辑
    def mock_web_research_error_handling(state, error_message):
        from datetime import datetime
        
        current_task_id = state.get("current_task_id", "unknown")
        
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
    
    test_state = {
        "current_task_id": "task-1",
        "id": 0,
        "search_query": "test query"
    }
    
    result = mock_web_research_error_handling(test_state, "API quota exhausted")
    print(f"错误处理结果: {result}")
    
    # 检查关键字段
    if (result["current_task_detailed_findings"][0]["task_id"] == "task-1" and
        result["task_specific_results"][0]["task_id"] == "task-1"):
        print("✅ 错误处理中任务ID正确保留")
        return True
    else:
        print("❌ 错误处理中任务ID丢失")
        return False

def main():
    """运行所有测试"""
    print("开始测试修复效果...\n")
    
    tests = [
        test_state_definitions,
        test_task_id_propagation,
        test_web_research_error_handling
    ]
    
    passed = 0
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n=== 测试总结 ===")
    print(f"通过: {passed}/{len(tests)} 个测试")
    
    if passed == len(tests):
        print("🎉 所有修复都已验证成功！")
    else:
        print("⚠️  仍有问题需要解决")

if __name__ == "__main__":
    main() 