import type { LucideIcon } from "lucide-react";
import { ArrowDownRight } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone?: "teal" | "blue" | "green" | "neutral";
}

export function MetricCard({ label, value, detail, icon: Icon, tone = "teal" }: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__topline">
        <span>{label}</span>
        <Icon size={18} aria-hidden="true" />
      </div>
      <div className="metric-card__value">{value}</div>
      <div className="metric-card__detail">
        {value.startsWith("-") && <ArrowDownRight size={14} aria-hidden="true" />}
        <span>{detail}</span>
      </div>
    </article>
  );
}

