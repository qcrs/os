export function formatNumber(value: number, maximumFractionDigits = 0): string {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits }).format(value);
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${formatNumber(value)} B`;
  if (value < 1024 * 1024) return `${formatNumber(value / 1024, 1)} KB`;
  return `${formatNumber(value / 1024 / 1024, 1)} MB`;
}

export function formatTimestamp(value: string): string {
  if (!value) return "--";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function shortHash(value: string, length = 10): string {
  if (!value) return "--";
  return value.length <= length ? value : `${value.slice(0, length)}...`;
}

