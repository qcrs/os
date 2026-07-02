"""
Agent运行时 - 管理和编排多个Agent的执行
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from .agent import Agent, AgentFactory
from .message import Message


class AgentRuntime:
    """
    多Agent运行时，负责Agent的生命周期管理和任务调度
    """

    def __init__(self, max_agents: int = 10, agent_timeout: float = 30.0):
        """
        初始化运行时

        Args:
            max_agents: 最大Agent数量
            agent_timeout: Agent操作超时时间（秒）
        """
        self.max_agents = max_agents
        self.agent_timeout = agent_timeout
        self.agents: Dict[str, Agent] = {}
        self.tasks: List[asyncio.Task] = []
        self.logger = logging.getLogger("AgentRuntime")
        self.started_at = None
        self.stopped = False
        self.scheduler = TaskScheduler(self)
        self.scheduler_task: Optional[asyncio.Task] = None

    def register_agent(self, agent: Agent) -> str:
        """
        注册一个Agent到运行时

        Args:
            agent: Agent实例

        Returns:
            Agent的ID
        """
        if len(self.agents) >= self.max_agents:
            raise RuntimeError(f"Max agents ({self.max_agents}) reached")

        self.agents[agent.agent_id] = agent
        self.logger.info(f"Registered agent: {agent.agent_id}")
        return agent.agent_id

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """获取指定ID的Agent"""
        return self.agents.get(agent_id)

    def list_agents(self) -> List[Agent]:
        """列出所有Agent"""
        return list(self.agents.values())

    def connect_agents(self, agent_a_id: str, agent_b_id: str, transport_factory=None):
        """
        连接两个Agent，使它们可以相互通信

        Args:
            agent_a_id: 第一个Agent的ID
            agent_b_id: 第二个Agent的ID
            transport_factory: 可选的 transport 构造函数
        """
        agent_a = self.get_agent(agent_a_id)
        agent_b = self.get_agent(agent_b_id)

        if not agent_a or not agent_b:
            raise ValueError("One or both agents not found")

        transport_ab = transport_factory(agent_a, agent_b) if transport_factory else None
        transport_ba = transport_factory(agent_b, agent_a) if transport_factory else None

        agent_a.connect_to_agent(agent_b, transport=transport_ab)
        agent_b.connect_to_agent(agent_a, transport=transport_ba)

        self.logger.info(f"Connected agents: {agent_a_id} <-> {agent_b_id}")

    async def start_agent(self, agent_id: str):
        """
        启动指定Agent

        Args:
            agent_id: Agent的ID
        """
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        task = asyncio.create_task(agent.run())
        self.tasks.append(task)
        self.logger.info(f"Started agent: {agent_id}")

    async def start_all_agents(self):
        """启动所有Agent"""
        for agent_id in self.agents.keys():
            await self.start_agent(agent_id)

    async def start_scheduler(self):
        """启动任务调度器"""
        if self.scheduler_task is None or self.scheduler_task.done():
            self.scheduler_task = asyncio.create_task(self.scheduler.execute_scheduled_tasks())
            self.logger.info("Started task scheduler")

    async def submit_task(self, task_def: Dict) -> str:
        """提交待办任务到调度器"""
        return await self.scheduler.submit_task(task_def)

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取待办任务状态"""
        return self.scheduler.get_task_status(task_id)

    def list_executed_tasks(self) -> List[Dict]:
        """列出执行完成的待办任务"""
        return self.scheduler.list_executed_tasks()

    async def run(self):
        """
        启动运行时，启动所有已注册的Agent

        这是运行时的主循环，通常在应用启动时调用
        """
        self.started_at = datetime.now()
        self.stopped = False
        self.logger.info(f"Runtime started with {len(self.agents)} agents")

        try:
            await self.start_all_agents()
            await self.start_scheduler()

            # 保持运行时活跃
            while not self.stopped:
                await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"Error in runtime: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """优雅关闭运行时"""
        self.logger.info("Shutting down runtime...")

        # 停止调度器
        self.scheduler.stop()
        if self.scheduler_task is not None:
            self.scheduler_task.cancel()
            await asyncio.gather(self.scheduler_task, return_exceptions=True)

        # 停止所有Agent
        for agent in self.agents.values():
            agent.stop()

        # 等待所有任务完成
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.stopped = True
        self.logger.info("Runtime shutdown complete")

    def stop(self):
        """停止运行时"""
        self.stopped = True

    def get_stats(self) -> Dict[str, Any]:
        """获取运行时统计信息"""
        agents_stats = [agent.get_stats() for agent in self.agents.values()]
        uptime = 0
        if self.started_at:
            uptime = (datetime.now() - self.started_at).total_seconds()

        return {
            "agents_count": len(self.agents),
            "agents_stats": agents_stats,
            "uptime_seconds": uptime,
            "tasks_count": len(self.tasks),
            "status": "running" if not self.stopped else "stopped",
        }


class TaskScheduler:
    """
    任务调度器，负责Agent任务的分配和调度
    """

    def __init__(self, runtime: AgentRuntime):
        """
        初始化任务调度器

        Args:
            runtime: AgentRuntime实例
        """
        self.runtime = runtime
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.executed_tasks: List[Dict] = []
        self.logger = logging.getLogger("TaskScheduler")
        self._stop_event = asyncio.Event()

    async def submit_task(self, task_def: Dict) -> str:
        """
        提交任务

        Args:
            task_def: 任务定义字典，包含 agent_id 和具体任务参数

        Returns:
            任务ID
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = {
            "task_id": task_id,
            "definition": task_def,
            "status": "queued",
            "created_at": datetime.now(),
        }

        await self.task_queue.put(task)
        self.logger.info(f"Submitted task: {task_id}")
        return task_id

    async def execute_scheduled_tasks(self):
        """
        执行队列中的任务

        这个方法应该在运行时中持续运行
        """
        while not self._stop_event.is_set():
            try:
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                await self._execute_task(task)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.error(f"Error executing task: {e}")

    def stop(self):
        """停止任务调度器"""
        self._stop_event.set()

    async def _execute_task(self, task: Dict):
        """执行单个任务"""
        task_id = task["task_id"]
        task_def = task["definition"]

        agent_id = task_def.get("agent_id")
        agent = self.runtime.get_agent(agent_id)

        if not agent:
            self.logger.error(f"Agent {agent_id} not found for task {task_id}")
            task["status"] = "failed"
            return

        try:
            task["status"] = "running"
            task["started_at"] = datetime.now()

            # 执行任务
            result = await agent.execute_task(task_def)

            task["status"] = "completed"
            task["result"] = result
            self.executed_tasks.append(task)

            self.logger.info(f"Task completed: {task_id}")
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            self.executed_tasks.append(task)
            self.logger.error(f"Task failed: {task_id} - {e}")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        for task in self.executed_tasks:
            if task["task_id"] == task_id:
                return task
        return None

    def list_executed_tasks(self) -> List[Dict]:
        """列出所有已执行的任务"""
        return self.executed_tasks
