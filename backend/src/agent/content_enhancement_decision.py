"""
智能内容增强决策模块 - 决定何时使用Firecrawl进行深度内容抓取
"""

import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnableConfig
from firecrawl import FirecrawlApp

@dataclass
class EnhancementDecision:
    """内容增强决策结果"""
    needs_enhancement: bool
    priority_urls: List[Dict[str, Any]]
    reasoning: str
    confidence_score: float  # 0-1
    enhancement_type: str  # "none", "selective", "comprehensive"


class ContentEnhancementDecisionMaker:
    """智能内容增强决策器 - 类似reflection机制"""
    
    def __init__(self):
        self.firecrawl_app = None
        if os.getenv("FIRECRAWL_API_KEY"):
            self.firecrawl_app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
    
    def analyze_enhancement_need(
        self, 
        research_topic: str,
        current_findings: List[str],
        grounding_sources: List[Dict[str, Any]],
        config: RunnableConfig
    ) -> EnhancementDecision:
        """
        智能分析是否需要内容增强 - 使用LLM做判断
        
        类似reflection机制，让LLM分析当前研究质量并决定是否需要深度抓取
        """
        
        # 构建分析提示词
        analysis_prompt = self._build_analysis_prompt(
            research_topic, current_findings, grounding_sources
        )
        
        # 使用LLM进行智能判断
        from agent.configuration import Configuration
        configurable = Configuration.from_runnable_config(config)
        
        llm = ChatGoogleGenerativeAI(
            model=configurable.reflection_model,  # 使用和reflection相同的模型
            temperature=0.3,  # 低温度确保一致性
            max_retries=2,
            api_key=os.getenv("GEMINI_API_KEY"),
        )
        
        response = llm.invoke(analysis_prompt)
        decision_text = response.content if hasattr(response, 'content') else str(response)
        
        # 解析LLM的决策
        return self._parse_llm_decision(decision_text, grounding_sources)
    
    def _build_analysis_prompt(
        self, 
        research_topic: str, 
        current_findings: List[str], 
        grounding_sources: List[Dict[str, Any]]
    ) -> str:
        """构建分析提示词"""
        
        findings_summary = "\n---\n".join(current_findings[-3:])  # 最近3个结果
        
        sources_list = "\n".join([
            f"- {source.get('title', 'N/A')}: {source.get('url', 'N/A')}"
            for source in grounding_sources[:5]  # 前5个源
        ])
        
        return f"""你是一个研究质量评估专家。请分析当前的研究结果质量，并决定是否需要深度内容增强。

研究主题: {research_topic}

当前研究发现:
{findings_summary}

可用的信息源:
{sources_list}

请根据以下标准进行评估:

1. **内容深度不足的信号**:
   - 缺乏具体数据、统计信息、案例研究
   - 描述过于泛泛，缺乏技术细节
   - 没有提及重要的公司、项目或实施案例
   - 信息源质量不高（非权威网站）

2. **需要深度抓取的情况**:
   - 研究主题需要详细的技术说明
   - 当前结果缺乏关键数据支撑
   - 存在权威信息源但内容被截断
   - 需要获取完整的报告或研究内容

3. **评估当前信息源的价值**:
   - 官方网站/文档: 高价值
   - 学术论文/研究报告: 高价值  
   - 维基百科/百科类: 中等价值
   - 新闻报道: 根据详细程度判断
   - 博客/论坛: 低价值

请按以下格式回答:

**决策**: [ENHANCE/NO_ENHANCE]
**置信度**: [0.1-1.0]
**增强类型**: [selective/comprehensive/none]
**推荐URL数量**: [0-3]
**推理过程**: 
[详细说明你的判断理由，包括当前内容的不足之处和预期的改进效果]

**优先URLs** (如果需要增强):
[从信息源中选择最值得深度抓取的URL，按优先级排序]
"""

    def _parse_llm_decision(
        self, 
        decision_text: str, 
        grounding_sources: List[Dict[str, Any]]
    ) -> EnhancementDecision:
        """解析LLM的决策结果"""
        
        decision_text = decision_text.lower()
        
        # 解析基本决策
        needs_enhancement = "enhance" in decision_text and "no_enhance" not in decision_text
        
        # 解析置信度
        confidence_score = 0.5  # 默认值
        import re
        confidence_match = re.search(r'置信度.*?([0-9]\.[0-9])', decision_text)
        if confidence_match:
            try:
                confidence_score = float(confidence_match.group(1))
            except:
                pass
        
        # 解析增强类型
        enhancement_type = "none"
        if "selective" in decision_text:
            enhancement_type = "selective"
        elif "comprehensive" in decision_text:
            enhancement_type = "comprehensive"
        elif needs_enhancement:
            enhancement_type = "selective"  # 默认选择性增强
        
        # 选择优先URL（简化版本，可以后续改进为LLM选择）
        priority_urls = []
        if needs_enhancement and grounding_sources:
            # 简单的优先级算法
            scored_sources = []
            for source in grounding_sources:
                score = self._calculate_url_priority(source)
                scored_sources.append((source, score))
            
            # 按评分排序，选择前2-3个
            scored_sources.sort(key=lambda x: x[1], reverse=True)
            max_urls = 3 if enhancement_type == "comprehensive" else 2
            
            priority_urls = [
                {
                    "title": source.get("title", ""),
                    "url": source.get("url", ""),
                    "priority_score": score,
                    "reasoning": f"评分: {score:.2f}"
                }
                for source, score in scored_sources[:max_urls]
                if score > 0.3  # 只选择评分较高的
            ]
        
        return EnhancementDecision(
            needs_enhancement=needs_enhancement,
            priority_urls=priority_urls,
            reasoning=decision_text,
            confidence_score=confidence_score,
            enhancement_type=enhancement_type
        )
    
    def _calculate_url_priority(self, source: Dict[str, Any]) -> float:
        """计算URL的优先级评分"""
        score = 0.0
        
        url = source.get("url", "").lower()
        title = source.get("title", "").lower()
        
        # 官方网站和文档
        if any(domain in url for domain in [".gov", ".edu", ".org"]):
            score += 0.4
        
        # 知名平台
        if any(platform in url for platform in ["wikipedia", "arxiv", "ieee", "acm"]):
            score += 0.3
        
        # 技术内容指标
        if any(keyword in title for keyword in ["report", "study", "research", "analysis", "technical"]):
            score += 0.2
        
        # 公司官网
        if any(company in url for company in ["google", "microsoft", "amazon", "tesla", "nvidia"]):
            score += 0.2
        
        # 基础评分
        score += 0.1
        
        return min(score, 1.0)
    
    async def enhance_content_with_firecrawl(
        self, 
        priority_urls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """使用Firecrawl增强内容"""
        
        if not self.firecrawl_app:
            return []
        
        enhanced_results = []
        
        for url_info in priority_urls:
            url = url_info.get("url")
            if not url:
                continue
            
            try:
                print(f"🔥 Firecrawl增强: {url_info.get('title', 'Unknown')}")
                
                result = self.firecrawl_app.scrape_url(url)
                
                if result and result.success:
                    markdown_content = result.markdown or ''
                    
                    enhanced_results.append({
                        "url": url,
                        "title": url_info.get("title", ""),
                        "original_priority": url_info.get("priority_score", 0),
                        "enhanced_content": markdown_content,
                        "content_length": len(markdown_content),
                        "enhancement_quality": self._assess_enhancement_quality(markdown_content),
                        "source_type": "firecrawl_enhanced"
                    })
                    
                    print(f"  ✅ 增强成功: {len(markdown_content)} 字符")
                else:
                    print(f"  ❌ 增强失败: {result.error if hasattr(result, 'error') else '未知错误'}")
                    
            except Exception as e:
                print(f"  ❌ 增强异常: {str(e)}")
                continue
        
        return enhanced_results
    
    def _assess_enhancement_quality(self, content: str) -> str:
        """评估增强内容的质量"""
        if not content:
            return "poor"
        
        length = len(content)
        has_data = any(char.isdigit() for char in content)
        has_structure = any(marker in content for marker in ['#', '##', '###'])
        
        if length > 5000 and has_data and has_structure:
            return "excellent"
        elif length > 1000 and (has_data or has_structure):
            return "good"
        elif length > 300:
            return "fair"
        else:
            return "poor"


# 延迟初始化函数，避免循环导入
def get_content_enhancement_decision_maker():
    """获取内容增强决策器实例（延迟初始化）"""
    if not hasattr(get_content_enhancement_decision_maker, '_instance'):
        get_content_enhancement_decision_maker._instance = ContentEnhancementDecisionMaker()
    return get_content_enhancement_decision_maker._instance

# 为了向后兼容，保留原有的全局变量名
content_enhancement_decision_maker = None  # 将在首次使用时初始化 