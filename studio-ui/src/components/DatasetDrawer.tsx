import { Braces, ChevronRight, Database, FileText, Hash, Table2, X } from "lucide-react";
import type { Dataset } from "../types";
import { formatBytes, shortHash } from "../format";

interface DatasetDrawerProps {
  datasets: Dataset[];
  selectedId: string;
  open: boolean;
  onSelect: (datasetId: string) => void;
  onClose: () => void;
}

export function DatasetDrawer({ datasets, selectedId, open, onSelect, onClose }: DatasetDrawerProps) {
  const selected = datasets.find((dataset) => dataset.dataset_id === selectedId) ?? datasets[0];
  if (!open || !selected) return null;

  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label="任务与数据目录">
      <button className="drawer-layer__scrim" onClick={onClose} aria-label="关闭任务与数据目录" />
      <aside className="dataset-drawer">
        <header className="dataset-drawer__header">
          <div>
            <span className="eyebrow">TASK & DATA / 任务目录</span>
            <h2>任务与数据目录</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="关闭">
            <X size={19} />
          </button>
        </header>

        <div className="dataset-drawer__body">
          <nav className="dataset-list" aria-label="数据集">
            {datasets.map((dataset) => (
              <button
                key={dataset.dataset_id}
                className={dataset.dataset_id === selected.dataset_id ? "dataset-list__item is-active" : "dataset-list__item"}
                onClick={() => onSelect(dataset.dataset_id)}
              >
                <Database size={17} />
                <span>
                  <strong>{dataset.label}</strong>
                  <small>{dataset.task_count} 个任务</small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </nav>

          <section className="dataset-detail">
            <div className="dataset-detail__title">
              <div>
                <span className="status-chip status-chip--neutral">{selected.domain}</span>
                <h3>{selected.label}</h3>
                <p>{selected.description}</p>
              </div>
              <div className="dataset-stat">
                <strong>{selected.task_count}</strong>
                <span>注册任务</span>
              </div>
            </div>

            <div className="metadata-line">
              <Braces size={15} />
              <span>{selected.manifest}</span>
            </div>

            {selected.sources.length > 0 && (
              <div className="drawer-section">
                <div className="section-heading section-heading--compact">
                  <div>
                    <span className="eyebrow">数据来源</span>
                    <h3>输入文件</h3>
                  </div>
                </div>
                <div className="source-list">
                  {selected.sources.map((source) => (
                    <article className="source-row" key={source.path}>
                      <div className="source-row__meta">
                        {source.format === "csv" ? <Table2 size={17} /> : <FileText size={17} />}
                        <div>
                          <strong>{source.name}</strong>
                          <span>{source.path}</span>
                        </div>
                        <small>{formatBytes(source.size_bytes)}</small>
                      </div>
                      <div className="checksum"><Hash size={13} /> {shortHash(source.sha256, 18)}</div>
                      {source.preview.kind === "table" && source.preview.rows && (
                        <div className="preview-table-wrap">
                          <table className="preview-table">
                            <tbody>
                              {source.preview.rows.map((row, rowIndex) => (
                                <tr key={`${source.path}-${rowIndex}`}>
                                  {row.map((cell, cellIndex) => rowIndex === 0 ? (
                                    <th key={cellIndex}>{cell}</th>
                                  ) : (
                                    <td key={cellIndex}>{cell || "--"}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {source.preview.kind === "text" && source.preview.lines && (
                        <div className="text-preview">
                          {source.preview.lines.map((line, index) => <p key={index}>{line}</p>)}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            )}

            <div className="drawer-section">
              <div className="section-heading section-heading--compact">
                <div>
                  <span className="eyebrow">任务合同</span>
                  <h3>任务链</h3>
                </div>
              </div>
              <div className="task-contract-list">
                {selected.tasks.map((task, index) => (
                  <article className="task-contract" key={task.task_id ?? task.family_id ?? index}>
                    <div className="task-contract__index">{task.round ?? index + 1}</div>
                    <div className="task-contract__body">
                      <div className="task-contract__topline">
                        <strong>{task.task_id ?? task.label}</strong>
                        <span>{task.intent_op ?? `${task.case_count} 个用例`}</span>
                      </div>
                      {task.request_text && <p>{task.request_text}</p>}
                      <div className="task-contract__tags">
                        {task.reuse_class && <span>复用等级: {task.reuse_class}</span>}
                        {task.depends_on_rounds && task.depends_on_rounds.length > 0 && (
                          <span>依赖 R{task.depends_on_rounds.join(", R")}</span>
                        )}
                        {task.required_outputs?.slice(0, 3).map((output) => <span key={output}>{output}</span>)}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
