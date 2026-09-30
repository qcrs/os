export type EvidenceSection = "communication" | "state" | "memory" | "capability";
export type RunMode = "quick" | "scenario" | "experiment";
export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";

export interface HeadlineMetric {
  id: string;
  label: string;
  baseline: number;
  statebus: number;
  unit: string;
  delta_pct: number;
}

export interface EvidenceSnapshot {
  schema_version: string;
  snapshot_id: string;
  snapshot_label: string;
  measured_at: string;
  published_at: string;
  git_sha: string;
  quality: Record<string, number>;
  headline_metrics: HeadlineMetric[];
  full_stack: Record<string, any>;
  structured_control: Record<string, number>;
  semantic_state: Record<string, number>;
  memory: Record<string, number>;
  capability: {
    passed: number;
    total: number;
    python_codeact: number;
    dsl: number;
    fallback: number;
    families: Array<{ id: string; label: string; cases: number }>;
  };
  engineering: Record<string, string | number>;
  task_scope: Array<{ id: string; label: string; count: number; detail: string }>;
  sources: string[];
}

export interface SourcePreview {
  kind: "table" | "text" | "metadata";
  rows?: string[][];
  lines?: string[];
}

export interface DatasetSource {
  name: string;
  path: string;
  format: string;
  size_bytes: number;
  sha256: string;
  preview: SourcePreview;
}

export interface DatasetTask {
  task_id?: string;
  family_id?: string;
  label?: string;
  case_count?: number;
  round?: number;
  request_text?: string;
  intent_op?: string;
  input_shape?: string;
  required_outputs?: string[];
  depends_on_rounds?: number[];
  reuse_class?: string;
}

export interface Dataset {
  dataset_id: string;
  label: string;
  domain: string;
  description: string;
  task_count: number;
  tasks: DatasetTask[];
  sources: DatasetSource[];
  manifest: string;
}

export interface Recipe {
  recipe_id: string;
  name: string;
  mode: RunMode;
  description: string;
  duration: string;
  dataset_ids: string[];
  task_ids: string[];
  accent: string;
}

export interface Catalog {
  datasets: Dataset[];
  recipes: Recipe[];
}

export interface RunEvent {
  sequence: number;
  timestamp: string;
  event_type: string;
  role: string;
  task_id: string;
  step_id: string;
  message: string;
  metrics: Record<string, number>;
  payload: Record<string, unknown>;
}

export interface RunView {
  run_id: string;
  recipe_id: string;
  recipe_name: string;
  mode: RunMode;
  status: RunStatus;
  created_at: string;
  started_at: string;
  completed_at: string;
  progress: number;
  current_stage: string;
  run_dir: string;
  error: string;
  result: Record<string, unknown>;
  latest_events: RunEvent[];
}

export interface TaskFlowObject {
  object_type: string;
  summary: string;
  refs: string[];
  hash?: string;
  data: unknown;
}

export interface TaskFlowValidationCheck {
  id: string;
  label: string;
  passed: boolean;
}

export interface TaskFlowStep {
  step_id: string;
  role: "planner" | "retriever" | "executor" | "summarizer" | string;
  status: string;
  capability_id: string;
  execution_kind: string;
  input: TaskFlowObject;
  transform: {
    summary: string;
    model: string;
    usage: Record<string, number>;
    decision_note?: string;
    structured_output?: unknown;
  };
  output: TaskFlowObject;
  validation: {
    status: string;
    validator_id: string;
    checks: TaskFlowValidationCheck[];
    error_codes: unknown[];
  };
}

export interface GeneratedProgram {
  kind: "python" | "dsl" | "none";
  capability_id?: string;
  model?: string;
  selection_reason?: string;
  source: string;
  input_refs?: string[];
  output_contract?: string;
  policy?: Record<string, unknown>;
  sandbox?: Record<string, unknown>;
  result?: Record<string, unknown>;
}

export interface TaskFlow {
  task_id: string;
  request_text: string;
  operation: string;
  task_family: string;
  status: string;
  quality_passed: boolean | null;
  elapsed_ms: number | null;
  execution_kind: string;
  execution_capability_id: string;
  model: string;
  usage: Record<string, number>;
  final_answer: string;
  steps: TaskFlowStep[];
  generated_program: GeneratedProgram;
  evidence: Record<string, unknown>;
  receipts: Record<string, unknown>;
  quality: Record<string, unknown>;
}

export interface TaskFlowIndex {
  run_id: string;
  available: boolean;
  tasks: Array<{
    task_id: string;
    status: string;
    operation: string;
    execution_kind: string;
    execution_capability_id: string;
    quality_passed: boolean | null;
  }>;
  selected_task_id: string;
  selected: TaskFlow | null;
}

export interface SystemHealth {
  ok: boolean;
  api: { ok: boolean };
  worker: { ok: boolean; concurrency: number };
  role_worker: { ok: boolean; detail: string; project_root_in_pythonpath: boolean };
  python: { ok: boolean; executable: string; version: string };
  model_config: { ok: boolean; path: string };
  embedding_model: {
    ok: boolean;
    path: string;
    device: string;
    runtime: { ok: boolean; device: string; detail: string; visible_device_count?: number };
  };
  model_service: { ok: boolean; status: number; url: string; detail?: string };
  policy: string;
}

export type ObservatoryView = "runtime" | "data" | "memory";

export interface ObservatoryEvent {
  id: string;
  kind: string;
  order: number;
  event_ts_ns: number | null;
  time_basis: "runtime_timestamp" | "causal_order" | string;
  actor: string;
  object_ids: string[];
  source_ref: { path: string; line?: number; json_pointer?: string };
  payload: Record<string, unknown>;
}

export interface ObservatoryObject {
  id: string;
  object_type: string;
  label: string;
  summary: string;
  fields: Record<string, unknown>;
}

export interface ObservatoryEdge {
  from: string;
  to: string;
  kind: string;
  label: string;
}

export interface ObservatoryTaskContract {
  method: string;
  periods: string[];
  required_history: string[];
  instructions: string;
  input_schemas: Record<string, Record<string, string>>;
  output_schema: Record<string, string>;
  source_ref: ObservatoryEvent["source_ref"];
}

export interface ObservatoryDelivery {
  rows: Array<Record<string, string | number | null>>;
  rows_source_ref: ObservatoryEvent["source_ref"];
  claim_set: {
    claim_set_id: string;
    status: string;
    claims: Array<{ claim_id: string; claim_text: string; status: string; supporting_evidence_item_ids: string[]; supporting_artifact_ref_ids: string[] }>;
  };
  report_source_ref: ObservatoryEvent["source_ref"];
  quality_passed: boolean | null;
  business_quality_passed: boolean | null;
  mechanism_gate_passed: boolean | null;
  quality_source_ref: ObservatoryEvent["source_ref"];
}

export interface ObservatoryTask {
  task_id: string;
  family: string;
  variant: string;
  run_id: string;
  status: string;
  round: number;
  metrics: Record<string, unknown>;
  task_contract?: ObservatoryTaskContract;
  delivery?: ObservatoryDelivery;
  events: ObservatoryEvent[];
  objects: ObservatoryObject[];
  edges: ObservatoryEdge[];
  raw_evidence: Array<{ source_ref: ObservatoryEvent["source_ref"]; event_type: string; fields: Record<string, unknown> }>;
  source_ref: ObservatoryEvent["source_ref"];
}

export interface ObservatoryCampaignTask {
  task_id: string;
  round: number;
  status: string;
  run_id: string;
  event_count: number;
  object_count: number;
  memory_consumption_count: number;
}

export interface ObservatoryCampaign {
  schema: string;
  collection: string;
  collection_date: string;
  generator_version: string;
  run_ids: Record<string, string>;
  families: string[];
  task_ids: string[];
  tasks: ObservatoryCampaignTask[];
  evidence: {
    quality_pass_rate: number;
    passed_count: number;
    record_count: number;
    provider: Record<string, number>;
    state: Record<string, unknown>;
    memory: Record<string, unknown>;
  };
  source_file_count: number;
  constraints: Record<string, unknown>;
}

// Both archived replays and future experiment adapters resolve to this same task shape.
export type ObservatorySourceMode = "replay" | "experiment";

export interface ObservatorySource {
  source_id: string;
  mode: ObservatorySourceMode;
  label: string;
  status: "available" | "running" | "complete" | "failed";
  task_ids: string[];
}

export interface ObservatoryEvidence {
  collection: string;
  results: Record<string, any>;
  tasks: Array<Record<string, string>>;
}
