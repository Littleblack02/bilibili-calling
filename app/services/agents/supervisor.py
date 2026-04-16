"""
Supervisor Agent - 主控Agent
负责意图分析、任务分发和结果汇总
"""
import asyncio
import json
from typing import Dict, Any, List
from app.services.agents.base import BaseAgent
from app.services.tools.base import ToolResult
from app.services.memory.manager import MemoryManager
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SupervisorAgent(BaseAgent):
    """Supervisor Agent：意图分析 + 任务分发 + 结果汇总"""

    name = "Supervisor"
    description = "主控Agent，负责分析用户意图并调度其他Agent"

    # 系统提示词
    SYSTEM_PROMPT = """你是一个智能助手的主控模块。

你的职责是根据用户问题，决定调用哪些子Agent来完成任务。

可用的子Agent及其职责：
- RAG: 用户收藏夹内视频的知识检索和内容理解
- Bilibili: B站搜索、评论、UP主信息、热榜、联网搜索
- Account: 收藏夹整理、定时同步等账号操作
- Recommendation: 个性化推荐和兴趣分析
- Web: 联网搜索和最新信息获取

分析用户问题后，按以下JSON格式输出：
{
  "intent": "用户意图的简要描述",
  "required_agents": ["RAG", "Bilibili"],  // 需要调用的Agent列表
  "execution_plan": [
    {"agent": "RAG", "task_type": "rag_search", "task": "搜索相关内容", "params": {"query": "AI"}},
    {"agent": "Bilibili", "task_type": "search_bilibili", "task": "获取最新视频", "params": {"keyword": "AI"}}
  ],
  "parallel": true  // 是否并行执行（true=无依赖可并行，false=有依赖需串行）
}

如果问题很简单，可以直接回答而不调用其他Agent：
{
  "intent": "直接回答",
  "required_agents": [],
  "execution_plan": [],
  "direct_answer": "这是直接回答的内容",
  "parallel": false
}

只返回JSON，不要其他内容。"""

    def __init__(self, memory: MemoryManager, session_id: str, agent_manager=None):
        super().__init__(memory, session_id)
        self.agent_manager = agent_manager

    async def process(self, task: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """处理用户请求"""
        import time
        start_time = time.time()

        try:
            user_message = task.get("content", "")

            # ===== 新增：多轮对话历史注入 =====
            # 1. 从记忆系统中召回与当前问题相关的历史对话
            recent_memories = await self.memory.recall(
                query=user_message,
                limit=5,
                memory_type="conversation"
            )
            # 如果召回不足5条，补充最近的历史（不限类型）
            if len(recent_memories) < 5:
                recent_all = await self.memory.get_recent(limit=10)
                seen_ids = {m.id for m in recent_memories}
                for m in recent_all:
                    if m.id not in seen_ids and len(recent_memories) < 5:
                        recent_memories.append(m)
                        seen_ids.add(m.id)

            # 2. 构建对话历史上下文
            conversation_context = self._build_conversation_context(recent_memories)
            self.logger.info(
                f"[MultiTurn] 召回历史 {len(recent_memories)} 条，上下文长度={len(conversation_context)}"
            )
            # ==================================

            # 3. 意图分析（带上历史上下文）
            plan = await self._analyze_intent(user_message, conversation_context=conversation_context)

            self.logger.info(f"Intent analysis result: {plan}")

            # 4. 如果有直接回答，直接返回（不调用Agent，但仍存入记忆）
            if "direct_answer" in plan:
                # 存入记忆
                await self.memory.remember(
                    content=f"用户: {user_message}\n助手: {plan['direct_answer']}",
                    memory_type="conversation",
                    importance=2,
                    metadata={"agents_called": []}
                )
                return ToolResult(
                    success=True,
                    data={"answer": plan["direct_answer"], "agents_called": []},
                    source="supervisor",
                    execution_time_ms=int((time.time() - start_time) * 1000)
                )

            # 5. 分发任务给子Agent
            agent_results = await self._dispatch_tasks(plan)

            # 6. 汇总结果（带上历史上下文，让LLM生成连贯的回答）
            final_answer = await self._summarize_results(
                agent_results, plan, user_message,
                conversation_context=conversation_context
            )

            # 7. 存入记忆
            await self.memory.remember(
                content=f"用户: {user_message}\n助手: {final_answer}",
                memory_type="conversation",
                importance=2,
                metadata={"agents_called": plan.get("required_agents", [])}
            )

            return ToolResult(
                success=True,
                data={
                    "answer": final_answer,
                    "agents_called": plan.get("required_agents", []),
                    "agent_results": {k: v.data for k, v in agent_results.items()},
                    "history_count": len(recent_memories)
                },
                source="supervisor",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            self.logger.error(f"Supervisor process error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="supervisor",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

    def _build_conversation_context(self, memories: List) -> str:
        """
        构建多轮对话历史上下文，用于注入到 LLM prompt 中。

        Args:
            memories: 召回的记忆列表（按相关性/时间排序）

        Returns:
            格式化的人类可读对话历史字符串
        """
        if not memories:
            return "（本次对话暂无历史记录）"

        lines = ["【对话历史】"]
        for i, mem in enumerate(memories, 1):
            content = mem.content.strip()
            mem_type = mem.memory_type or "conversation"
            # 提取 user/assistant 角色（格式：用户: xxx\n助手: xxx）
            if "\n" in content:
                parts = content.split("\n", 1)
                role_line = parts[0].strip()
                rest = parts[1].strip() if len(parts) > 1 else ""
                # 截断过长的回复
                if len(rest) > 200:
                    rest = rest[:200] + "..."
                lines.append(f"  [{i}轮] {role_line}")
                if rest:
                    lines.append(f"       助手: {rest}")
            else:
                # 无法解析格式，直接截断显示
                display = content[:150] + ("..." if len(content) > 150 else "")
                lines.append(f"  [{i}轮] {display}")

        lines.append("【当前问题】")
        return "\n".join(lines)

    async def _analyze_intent(
        self,
        user_message: str,
        conversation_context: str = ""
    ) -> Dict[str, Any]:
        """分析用户意图（使用LLM，可选传入对话历史上下文）"""
        try:
            # 尝试使用LLM进行意图分析
            return await self._llm_analyze_intent(user_message, conversation_context)
        except Exception as e:
            logger.warning(f"LLM意图分析失败，使用规则匹配: {e}")
            # Fallback到规则匹配
            return await self._rule_based_analyze_intent(user_message)

    async def _llm_analyze_intent(
        self,
        user_message: str,
        conversation_context: str = ""
    ) -> Dict[str, Any]:
        """使用LLM进行意图分析（带多轮对话上下文）"""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        # 构建意图分析提示词（注入对话历史）
        system_prompt = """你是一个智能助手的多Agent调度专家。

你的职责是分析用户的自然语言问题，判断需要调用哪些专业Agent来完成任务。

可用的Agent及其能力：
- RAG: 在用户收藏夹内搜索视频、理解视频内容、查询收藏夹列表
- Bilibili: 搜索B站视频、获取评论、查询UP主信息、热榜排行
- Web: 联网搜索最新信息、新闻搜索
- Account: 收藏夹整理、定时同步、收藏夹管理
- Recommendation: 个性化推荐、兴趣分析、用户画像

【重要】多轮对话理解：
- 注意用户的当前问题可能是对前文的追问、补充或延续
- 如果问题含"它"、"这个"、"继续"等指代词，需要结合对话历史理解
- 如果用户在前面的问题中指定了话题，当前问题应沿用该话题

决策规则：
1. 如果问题涉及用户自己的收藏内容 → RAG + Account
2. 如果问题需要最新信息/新闻 → Web
3. 如果问题需要搜索视频/UP主/热榜 → Bilibili
4. 如果问题涉及推荐或兴趣 → Recommendation
5. 如果问题涉及收藏夹管理/整理/同步 → Account
6. 复杂问题可能需要多个Agent协作

输出要求：
- 只返回JSON格式的分析结果
- plan必须包含具体可执行的params
- 判断是否需要并行执行
- 如果问题很简单（问候、闲聊），不需要调用Agent

JSON格式：
{
  "intent": "用户意图的简要描述（5-15字）",
  "required_agents": ["Agent1", "Agent2"],
  "execution_plan": [
    {
      "agent": "Agent名称",
      "task_type": "具体任务类型",
      "task": "任务描述",
      "params": {"具体参数": "参数值"}
    }
  ],
  "parallel": true或false,
  "direct_answer": "如果不需要调用Agent，给出的直接回答"
}"""

        # 根据是否有历史上下文，选择不同的 human prompt
        if conversation_context:
            human_prompt = f"""{conversation_context}

请结合以上对话历史，分析当前问题。

当前问题：{user_message}

请分析用户意图并决定调用哪些Agent。"""
        else:
            human_prompt = f"用户问题：{user_message}\n\n请分析用户意图并决定调用哪些Agent。"

        intent_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_prompt)
        ])

        # 获取LLM实例
        llm = self._get_llm()

        # 构建处理链
        chain = intent_prompt | llm | StrOutputParser()

        # 执行意图分析（如果无历史上下文则传空字符串）
        result = await chain.ainvoke({
            "user_message": user_message,
            "conversation_context": conversation_context or ""
        })

        # 解析JSON结果
        try:
            # 清理可能的markdown代码块
            result = result.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            result = result.strip()

            analysis = json.loads(result)

            # 验证必要字段
            if not analysis.get("required_agents") and not analysis.get("direct_answer"):
                raise ValueError("Missing required fields")

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"LLM返回的不是有效JSON: {result}, error: {e}")
            raise ValueError(f"Invalid LLM response: {e}")

    async def _rule_based_analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """基于规则的意图分析（Fallback）"""
        user_lower = user_message.lower()

        # 规则匹配
        rules = {
            "收藏": ["RAG"],
            "收藏夹": ["RAG", "Account"],
            "搜索": ["Bilibili"],
            "最新": ["Bilibili", "Web"],
            "新闻": ["Web"],
            "推荐": ["Recommendation"],
            "整理": ["Account"],
            "同步": ["Account"],
            "热榜": ["Bilibili"],
            "评论": ["Bilibili"],
            "UP主": ["Bilibili"],
            "有什么": ["Recommendation"],
            "学习": ["RAG", "Recommendation"],
            "教程": ["RAG"],
            "视频": ["Bilibili", "RAG"]
        }

        required_agents = []
        for keyword, agents in rules.items():
            if keyword in user_message:
                required_agents.extend(agents)

        # 去重
        required_agents = list(set(required_agents))

        # 如果没有匹配到，直接回答
        if not required_agents:
            return {
                "intent": "简单对话",
                "required_agents": [],
                "execution_plan": [],
                "direct_answer": self._generate_simple_response(user_message),
                "parallel": False
            }

        # 生成执行计划
        execution_plan = self._generate_execution_plan(user_message, required_agents)

        return {
            "intent": f"需要{', '.join(required_agents)}Agent协作",
            "required_agents": required_agents,
            "execution_plan": execution_plan,
            "parallel": True
        }

    def _generate_execution_plan(self, user_message: str, agents: List[str]) -> List[Dict[str, Any]]:
        """根据Agent列表生成执行计划"""
        execution_plan = []

        for agent in agents:
            if agent == "RAG":
                execution_plan.append({
                    "agent": "RAG",
                    "task_type": "rag_search",
                    "task": "搜索收藏夹内容",
                    "params": {"query": user_message}
                })
            elif agent == "Bilibili":
                execution_plan.append({
                    "agent": "Bilibili",
                    "task_type": "search_bilibili",
                    "task": "搜索B站内容",
                    "params": {"keyword": user_message}
                })
            elif agent == "Web":
                execution_plan.append({
                    "agent": "Web",
                    "task_type": "web_search",
                    "task": "联网搜索",
                    "params": {"query": user_message}
                })
            elif agent == "Account":
                execution_plan.append({
                    "agent": "Account",
                    "task_type": "get_favorites",
                    "task": "获取收藏夹信息",
                    "params": {}
                })
            elif agent == "Recommendation":
                execution_plan.append({
                    "agent": "Recommendation",
                    "task_type": "get_recommendations",
                    "task": "获取个性化推荐",
                    "params": {"session_id": self.session_id, "num": 5}
                })

        return execution_plan

    async def _dispatch_tasks(self, plan: Dict[str, Any]) -> Dict[str, ToolResult]:
        """直接调用服务层执行任务（不依赖子Agent）"""
        results = {}
        execution_plan = plan.get("execution_plan", [])
        parallel = plan.get("parallel", True)

        # 将 task 转换为可直接执行的任务
        tasks_to_run = []
        for step in execution_plan:
            task_type = step.get("task_type", "")
            params = step.get("params", {})
            agent_name = step.get("agent", "unknown")

            tasks_to_run.append({
                "name": agent_name,
                "task_type": task_type,
                "params": params,
                "task_obj": self._create_service_task(agent_name, task_type, params)
            })

        if not tasks_to_run:
            return results

        if parallel:
            # 并行执行所有服务任务
            async def safe_run(task_info):
                try:
                    result = await task_info["task_obj"]
                    return task_info["name"], result
                except Exception as e:
                    self.logger.error(f"Task {task_info['name']} failed: {e}")
                    return task_info["name"], ToolResult(
                        success=False,
                        error=str(e),
                        source=f"{task_info['name'].lower()}_service"
                    )

            run_results = await asyncio.gather(
                *[safe_run(t) for t in tasks_to_run],
                return_exceptions=True
            )
            for item in run_results:
                if isinstance(item, Exception):
                    continue
                name, result = item
                results[name] = result
        else:
            # 串行执行
            for task_info in tasks_to_run:
                try:
                    result = await task_info["task_obj"]
                    results[task_info["name"]] = result
                except Exception as e:
                    self.logger.error(f"Task {task_info['name']} failed: {e}")
                    results[task_info["name"]] = ToolResult(
                        success=False,
                        error=str(e),
                        source=f"{task_info['name'].lower()}_service"
                    )

        return results

    def _create_service_task(
        self,
        agent_name: str,
        task_type: str,
        params: Dict[str, Any]
    ):
        """
        根据 agent_name 和 task_type 创建可直接 await 的协程任务。

        这个方法让 SupervisorAgent 可以在没有子 Agent 的情况下，
        直接调用服务层完成实际工作。
        """
        if agent_name == "RAG":
            return self._run_rag_service(task_type, params)
        elif agent_name == "Bilibili":
            return self._run_bilibili_service(task_type, params)
        elif agent_name == "Web":
            return self._run_web_service(task_type, params)
        elif agent_name == "Account":
            return self._run_account_service(task_type, params)
        elif agent_name == "Recommendation":
            return self._run_recommendation_service(task_type, params)
        else:
            # 未知类型，返回空结果
            async def unknown():
                return ToolResult(
                    success=False,
                    error=f"Unknown agent: {agent_name}",
                    source="supervisor"
                )
            return unknown()

    async def _run_rag_service(self, task_type: str, params: Dict) -> ToolResult:
        """直接调用 RAG 服务"""
        from app.services.rag import RAGService
        rag = RAGService()
        query = params.get("query", "")
        top_k = params.get("top_k", 5)

        try:
            if task_type == "rag_search":
                docs = rag.search(query, k=top_k)
                results = []
                for doc in docs:
                    meta = doc.metadata or {}
                    results.append({
                        "bvid": meta.get("bvid", ""),
                        "title": meta.get("title", ""),
                        "content": doc.page_content[:200],
                        "url": meta.get("url", "")
                    })
                return ToolResult(success=True, data=results, source="rag_search")
            return ToolResult(success=False, error=f"Unknown rag task: {task_type}", source="rag")
        except Exception as e:
            return ToolResult(success=False, error=str(e), source="rag")

    async def _run_bilibili_service(self, task_type: str, params: Dict) -> ToolResult:
        """直接调用 Bilibili 服务"""
        from app.services.bilibili import BilibiliService
        keyword = params.get("keyword", "")

        try:
            bili = BilibiliService()
            async with bili:
                if task_type == "search_bilibili":
                    result = await bili.search_bilibili(keyword=keyword, search_type="video", page=1)
                    if result.get("success"):
                        items = result.get("items", [])
                        formatted = [{
                            "bvid": i.get("bvid", ""),
                            "title": i.get("title", ""),
                            "author": i.get("author", ""),
                            "play": i.get("play", 0)
                        } for i in items[:10]]
                        return ToolResult(success=True, data=formatted, source="bilibili_search")
                    return ToolResult(success=False, error=result.get("error", "搜索失败"), source="bilibili")
            return ToolResult(success=False, error="Bilibili service unavailable", source="bilibili")
        except Exception as e:
            return ToolResult(success=False, error=str(e), source="bilibili")

    async def _run_web_service(self, task_type: str, params: Dict) -> ToolResult:
        """直接调用 Web 搜索服务"""
        from app.services.web_search import WebSearchService
        query = params.get("query", "")

        try:
            service = WebSearchService()
            result = await service.search(query, num_results=5)
            return ToolResult(success=True, data=result, source="web_search")
        except Exception as e:
            return ToolResult(success=False, error=str(e), source="web_search")

    async def _run_account_service(self, task_type: str, params: Dict) -> ToolResult:
        """直接调用 Account 服务（收藏夹管理）"""
        from app.database import async_session_factory
        from app.models import FavoriteFolder, FavoriteVideo
        from sqlalchemy import select

        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(FavoriteFolder).where(FavoriteFolder.session_id == self.session_id)
                )
                folders = result.scalars().all()
                data = [{
                    "id": f.id,
                    "title": f.title,
                    "media_count": f.media_count,
                    "last_sync_at": f.last_sync_at.isoformat() if f.last_sync_at else None
                } for f in folders]
                return ToolResult(success=True, data=data, source="account")
        except Exception as e:
            return ToolResult(success=False, error=str(e), source="account")

    async def _run_recommendation_service(self, task_type: str, params: Dict) -> ToolResult:
        """直接调用推荐服务"""
        from app.services.recommendation.recommendation_service import get_recommendation_service
        num = params.get("num", 5)

        try:
            rec_service = get_recommendation_service()
            results = await rec_service.generate_recommendations(
                session_id=self.session_id,
                limit=num
            )
            return ToolResult(success=True, data=results, source="recommendation")
        except Exception as e:
            return ToolResult(success=False, error=str(e), source="recommendation")

    async def _summarize_results(
        self,
        agent_results: Dict[str, ToolResult],
        plan: Dict[str, Any],
        user_message: str,
        conversation_context: str = ""
    ) -> str:
        """汇总Agent结果（使用LLM，可选注入对话历史上下文）"""
        if not agent_results:
            return "抱歉，没有找到相关结果。"

        try:
            # 尝试使用LLM进行智能汇总（带上历史上下文）
            return await self._llm_summarize(
                agent_results, plan, user_message,
                conversation_context=conversation_context
            )
        except Exception as e:
            logger.warning(f"LLM汇总失败，使用fallback方案: {e}")
            # Fallback到字符串拼接方案
            return await self._fallback_summarize(agent_results, plan, user_message)

    async def _llm_summarize(
        self,
        agent_results: Dict[str, ToolResult],
        plan: Dict[str, Any],
        user_message: str,
        conversation_context: str = ""
    ) -> str:
        """使用LLM进行智能汇总（带多轮对话上下文）"""
        from app.config import settings
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        # 1. 准备Agent结果摘要
        results_summary = self._format_agent_results_for_llm(agent_results)

        # 2. 构建汇总提示词（根据是否有历史上下文选择不同模板）
        if conversation_context:
            system_prompt = """你是一个智能助手的结果汇总专家。

你的职责是将多个专业Agent的执行结果整合成一个清晰、有条理的回答。

【重要】请注意对话历史，用户当前问题可能是对前文的追问、补充或延续。
你应该：
1. 综合所有Agent的结果，去除重复信息
2. 按重要性排序结果
3. 用简洁的语言总结核心信息
4. 如果某个Agent失败了，简单说明原因
5. 保持回答的连贯性和可读性
6. 适当使用emoji和格式让回答更友好
7. 如果当前问题是追问，回答应延续前文而非重复介绍

输出格式：
- 开头：简要回答用户问题（若是追问则直接回应）
- 中间：分点列出各Agent的关键发现
- 结尾：总结或建议（如果适用）"""

            human_prompt = f"""{conversation_context}

【当前问题】：{user_message}

【调用的Agent】：{', '.join(agent_results.keys())}

【各Agent执行结果】：
{results_summary}

请整合以上结果，结合对话历史，给出一个完整、连贯的回答。"""
        else:
            system_prompt = """你是一个智能助手的结果汇总专家。

你的职责是将多个专业Agent的执行结果整合成一个清晰、有条理的回答。

规则：
1. 综合所有Agent的结果，去除重复信息
2. 按重要性排序结果
3. 用简洁的语言总结核心信息
4. 如果某个Agent失败了，简单说明原因
5. 保持回答的连贯性和可读性
6. 适当使用emoji和格式让回答更友好

输出格式：
- 开头：简要回答用户问题
- 中间：分点列出各Agent的关键发现
- 结尾：总结或建议（如果适用）"""

            human_prompt = f"""用户问题：{user_message}

调用的Agent：{', '.join(agent_results.keys())}

各Agent执行结果：
{results_summary}

请整合以上结果，给出一个完整、连贯的回答。"""

        summary_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_prompt)
        ])

        # 3. 初始化LLM（优先使用本地Ollama，降级到配置的API）
        llm = self._get_llm()

        # 4. 构建处理链
        chain = summary_prompt | llm | StrOutputParser()

        # 5. 执行汇总（conversation_context 通过 human_prompt 变量注入）
        agents_called = ', '.join(agent_results.keys())
        final_answer = await chain.ainvoke({
            "user_message": user_message,
            "agents_called": agents_called,
            "agent_results": results_summary,
            "conversation_context": conversation_context or ""
        })

        return final_answer.strip()

    def _get_llm(self):
        """获取LLM实例（使用百炼模型）"""
        from app.config import settings
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            temperature=0.7
        )

    def _format_agent_results_for_llm(self, agent_results: Dict[str, ToolResult]) -> str:
        """格式化Agent结果供LLM使用"""
        summary_parts = []

        for agent_name, result in agent_results.items():
            part = f"\n【{agent_name} Agent】\n"

            if result.success:
                if isinstance(result.data, list):
                    if result.data:
                        part += f"找到 {len(result.data)} 条结果：\n"
                        for i, item in enumerate(result.data[:5], 1):  # 最多5条
                            if isinstance(item, dict):
                                title = item.get("title", item.get("content", item.get("name", str(item))))
                                part += f"{i}. {title}\n"

                                # 添加关键信息
                                if item.get("description"):
                                    desc = str(item["description"])[:100]
                                    part += f"   描述: {desc}...\n"
                                if item.get("author"):
                                    part += f"   作者: {item['author']}\n"
                        if len(result.data) > 5:
                            part += f"... 还有 {len(result.data) - 5} 条结果\n"
                    else:
                        part += "未找到相关结果。\n"
                elif isinstance(result.data, dict):
                    part += "执行结果：\n"
                    for key, value in list(result.data.items())[:5]:
                        value_str = str(value)[:100]
                        part += f"- {key}: {value_str}\n"
                else:
                    part += f"执行结果: {str(result.data)[:200]}\n"
            else:
                part += f"执行失败: {result.error or '未知错误'}\n"

            summary_parts.append(part)

        return "\n".join(summary_parts)

    async def _fallback_summarize(
        self,
        agent_results: Dict[str, ToolResult],
        plan: Dict[str, Any],
        user_message: str
    ) -> str:
        """Fallback汇总方案（字符串拼接）"""
        summary_parts = []

        for agent_name, result in agent_results.items():
            if result.success and result.data:
                summary_parts.append(f"### {agent_name} Agent结果\n")

                # 根据不同agent类型格式化结果
                if isinstance(result.data, list):
                    if result.data:
                        summary_parts.append(f"找到 {len(result.data)} 条结果：\n")
                        for item in result.data[:3]:  # 只显示前3条
                            if isinstance(item, dict):
                                title = item.get("title", item.get("content", str(item)))
                                summary_parts.append(f"- {title}\n")
                    else:
                        summary_parts.append("未找到相关结果。\n")
                elif isinstance(result.data, dict):
                    for key, value in list(result.data.items())[:5]:
                        summary_parts.append(f"- {key}: {value}\n")
                else:
                    summary_parts.append(f"{result.data}\n")

                summary_parts.append("\n")

        final_summary = "".join(summary_parts)

        # 添加引导语
        if len(agent_results) > 1:
            final_summary = f"根据你的问题「{user_message}」，我调用了{', '.join(agent_results.keys())} Agent，以下是汇总结果：\n\n" + final_summary

        return final_summary.strip()

    def _generate_simple_response(self, message: str) -> str:
        """生成简单回答"""
        responses = {
            "你好": "你好！我是你的智能助手，可以帮你搜索B站视频、管理收藏夹、获取个性化推荐等。有什么可以帮你的吗？",
            "hi": "Hi! 有什么可以帮你的吗？",
            "谢谢": "不客气！如果还有其他问题，随时告诉我。",
            "再见": "再见！祝你生活愉快~",
            "是谁": "我是Bilibili RAG多Agent协作系统，由Supervisor主控，下设RAG、Bilibili、Account、Recommendation、Web等专业Agent。",
            "功能": "我可以帮你：\n1. 搜索和管理B站收藏夹\n2. 搜索B站最新视频和资讯\n3. 个性化推荐\n4. 整理收藏夹\n5. 获取最新资讯"
        }

        for key, response in responses.items():
            if key in message.lower():
                return response

        return "我收到你的消息了。你可以问我关于B站视频搜索、收藏夹管理、个性化推荐等问题。"
