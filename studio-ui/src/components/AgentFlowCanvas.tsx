import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  BrainCircuit,
  Braces,
  Check,
  Code2,
  FileCheck2,
  FileJson2,
  Search,
  Waypoints,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import "@xyflow/react/dist/style.css";
import type { TaskFlow, TaskFlowStep } from "../types";

export type FlowVisualState = "waiting" | "active" | "done" | "error";

interface AgentNodeData extends Record<string, unknown> {
  role: string;
  label: string;
  english: string;
  capability: string;
  state: FlowVisualState;
}

interface ObjectNodeData extends Record<string, unknown> {
  role: string;
  objectType: string;
  reference: string;
  state: FlowVisualState;
}

type AgentNode = Node<AgentNodeData, "agent">;
type ObjectNode = Node<ObjectNodeData, "object">;
type CanvasNode = AgentNode | ObjectNode;

const roleMeta = {
  planner: { label: "规划 Agent", english: "Planner", icon: BrainCircuit },
  retriever: { label: "检索 Agent", english: "Retriever", icon: Search },
  executor: { label: "执行 Agent", english: "Executor", icon: Code2 },
  summarizer: { label: "总结 Agent", english: "Summarizer", icon: FileCheck2 },
} as const;

const objectMeta = [
  { id: "task-spec", role: "planner", objectType: "CanonicalTaskSpec", x: 98 },
  { id: "approved-plan", role: "planner", objectType: "ApprovedPlan", x: 286 },
  { id: "evidence-pack", role: "retriever", objectType: "EvidencePack", x: 474 },
  { id: "artifact-ref", role: "executor", objectType: "ExecutionArtifactRef", x: 662 },
  { id: "claim-set", role: "summarizer", objectType: "ClaimSet", x: 850 },
] as const;

const agentPositions = {
  planner: { x: 116, y: 20 },
  retriever: { x: 324, y: 20 },
  executor: { x: 532, y: 20 },
  summarizer: { x: 740, y: 20 },
} as const;

function stateLabel(state: FlowVisualState) {
  return {
    waiting: "等待",
    active: "运行中",
    done: "已验证",
    error: "失败",
  }[state];
}

function AgentCanvasNode({ data }: NodeProps<AgentNode>) {
  const meta = roleMeta[data.role as keyof typeof roleMeta] ?? roleMeta.planner;
  const Icon = meta.icon;
  return (
    <button className={`flow-agent-node flow-state--${data.state}`} type="button">
      <Handle className="flow-handle flow-handle--target" id="in" position={Position.Bottom} type="target" />
      <Handle className="flow-handle flow-handle--source" id="out" position={Position.Bottom} type="source" />
      <div className="flow-agent-node__top">
        <span className="flow-agent-node__icon"><Icon size={18} /></span>
        <span className="flow-node-status">
          {data.state === "done" && <Check size={11} />}
          {data.state === "error" && <XCircle size={11} />}
          {stateLabel(data.state)}
        </span>
      </div>
      <strong>{data.label}</strong>
      <small>{data.english}</small>
      <code title={data.capability}>{data.capability || "等待 Capability"}</code>
    </button>
  );
}

function ObjectCanvasNode({ data }: NodeProps<ObjectNode>) {
  const Icon = data.objectType === "ExecutionArtifactRef"
    ? Braces
    : data.objectType === "ClaimSet"
      ? FileCheck2
      : data.objectType === "EvidencePack"
        ? Waypoints
        : FileJson2;
  return (
    <button className={`flow-object-node flow-state--${data.state}`} type="button">
      <Handle className="flow-object-handle flow-object-handle--target" id="in" position={Position.Top} type="target" />
      <Handle className="flow-object-handle flow-object-handle--source" id="out" position={Position.Top} type="source" />
      <span><Icon size={14} /></span>
      <div><strong>{data.objectType}</strong><small>{data.reference || stateLabel(data.state)}</small></div>
    </button>
  );
}

const nodeTypes = {
  agent: AgentCanvasNode,
  object: ObjectCanvasNode,
};

function referenceFor(step: TaskFlowStep | undefined) {
  return step?.output?.refs?.[0] || step?.output?.hash || "";
}

function shortReference(value: string) {
  if (!value) return "";
  return value.length <= 20 ? value : `${value.slice(0, 10)}...${value.slice(-6)}`;
}

function edgeState(targetState: FlowVisualState): FlowVisualState {
  if (targetState === "error") return "error";
  if (targetState === "active") return "active";
  if (targetState === "done") return "done";
  return "waiting";
}

function edgeStyle(state: FlowVisualState) {
  if (state === "done") return { stroke: "#25865f", strokeWidth: 2 };
  if (state === "active") return { stroke: "#087f75", strokeWidth: 2.4 };
  if (state === "error") return { stroke: "#b84242", strokeWidth: 2.4 };
  return { stroke: "#c7d0d5", strokeWidth: 1.5 };
}

export function AgentFlowCanvas({
  flow,
  states,
  selectedRole,
  hasRun,
  onSelectRole,
}: {
  flow: TaskFlow | null;
  states: Record<string, FlowVisualState>;
  selectedRole: string;
  hasRun: boolean;
  onSelectRole: (role: string) => void;
}) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const flowInstanceRef = useRef<ReactFlowInstance<CanvasNode, Edge> | null>(null);
  const fitFrameRef = useRef<number | null>(null);
  const steps = useMemo(
    () => new Map((Array.isArray(flow?.steps) ? flow.steps : []).map((step) => [step.role, step])),
    [flow],
  );

  const fitCanvas = useCallback(() => {
    if (fitFrameRef.current !== null) window.cancelAnimationFrame(fitFrameRef.current);
    fitFrameRef.current = window.requestAnimationFrame(() => {
      fitFrameRef.current = null;
      void flowInstanceRef.current?.fitView({ padding: 0.09, minZoom: 0.3, maxZoom: 1.15 });
    });
  }, []);

  useEffect(() => {
    fitCanvas();
    const settledTimer = window.setTimeout(fitCanvas, 120);
    return () => window.clearTimeout(settledTimer);
  }, [fitCanvas, flow?.task_id, flow?.steps?.length, hasRun]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(fitCanvas);
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      if (fitFrameRef.current !== null) window.cancelAnimationFrame(fitFrameRef.current);
    };
  }, [fitCanvas]);

  const nodes = useMemo<CanvasNode[]>(() => {
    const agentNodes = Object.entries(roleMeta).map(([role, meta]) => {
      const step = steps.get(role);
      return {
        id: `agent-${role}`,
        type: "agent" as const,
        position: agentPositions[role as keyof typeof agentPositions],
        data: {
          role,
          label: meta.label,
          english: meta.english,
          capability: step?.capability_id ?? "",
          state: states[role] ?? "waiting",
        },
        selected: selectedRole === role,
        draggable: false,
        selectable: true,
      } satisfies AgentNode;
    });

    const producerSteps: Record<string, TaskFlowStep | undefined> = {
      "approved-plan": steps.get("planner"),
      "evidence-pack": steps.get("retriever"),
      "artifact-ref": steps.get("executor"),
      "claim-set": steps.get("summarizer"),
    };
    const objectNodes = objectMeta.map((meta, index) => {
      const producer = producerSteps[meta.id];
      const state = index === 0
        ? (hasRun ? "done" : "waiting")
        : (states[meta.role] ?? "waiting");
      return {
        id: meta.id,
        type: "object" as const,
        position: { x: meta.x, y: 214 },
        data: {
          role: meta.role,
          objectType: meta.objectType,
          reference: shortReference(referenceFor(producer)),
          state,
        },
        selected: false,
        draggable: false,
        selectable: true,
      } satisfies ObjectNode;
    });
    return [...agentNodes, ...objectNodes];
  }, [flow, hasRun, selectedRole, states, steps]);

  const edges = useMemo<Edge[]>(() => {
    const definitions = [
      ["task-spec", "agent-planner", "planner", "in"],
      ["agent-planner", "approved-plan", "planner", "out"],
      ["approved-plan", "agent-retriever", "retriever", "in"],
      ["agent-retriever", "evidence-pack", "retriever", "out"],
      ["evidence-pack", "agent-executor", "executor", "in"],
      ["agent-executor", "artifact-ref", "executor", "out"],
      ["artifact-ref", "agent-summarizer", "summarizer", "in"],
      ["agent-summarizer", "claim-set", "summarizer", "out"],
    ] as const;
    return definitions.map(([source, target, role, direction], index) => {
      const targetState = states[role] ?? "waiting";
      const state = direction === "in"
        ? edgeState(targetState)
        : targetState === "done" || targetState === "error" ? targetState : "waiting";
      return {
        id: `flow-edge-${index}`,
        source,
        target,
        sourceHandle: "out",
        targetHandle: "in",
        type: "smoothstep",
        animated: state === "active",
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeStyle(state).stroke, width: 14, height: 14 },
        style: edgeStyle(state),
        className: `flow-edge flow-edge--${state}`,
      } satisfies Edge;
    });
  }, [states]);

  return (
    <div className="agent-flow-canvas" ref={canvasRef}>
      <div className="statebus-object-rail"><span>StateBus</span><strong>类型化对象轨道</strong></div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(instance) => {
          flowInstanceRef.current = instance;
          fitCanvas();
        }}
        onNodeClick={(_event, node) => onSelectRole(String(node.data.role || "planner"))}
        fitView
        fitViewOptions={{ padding: 0.09, minZoom: 0.3, maxZoom: 1.15 }}
        minZoom={0.28}
        maxZoom={1.25}
        nodesConnectable={false}
        nodesDraggable={false}
        elementsSelectable
        panOnDrag={false}
        panOnScroll={false}
        zoomOnDoubleClick={false}
        zoomOnPinch
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#dbe2e5" gap={22} size={1} variant={BackgroundVariant.Dots} />
      </ReactFlow>
    </div>
  );
}
