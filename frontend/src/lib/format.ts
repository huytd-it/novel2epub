const nf = new Intl.NumberFormat("vi-VN");

export function num(value: number | null | undefined): string {
  return nf.format(value ?? 0);
}

export function percent(part: number, total: number): number {
  if (!total) return 0;
  return Math.round((part / total) * 100);
}

/** Khoảng thời gian tương đối, đủ thô để đọc lướt trong bảng job. */
export function ago(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "—";
  const diff = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (diff < 60) return `${Math.floor(diff)} giây trước`;
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}

export function duration(from: number | null | undefined, to: number | null | undefined): string {
  if (!from) return "—";
  const end = to ?? Date.now() / 1000;
  const secs = Math.max(0, Math.round(end - from));
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

export function bytes(value: number | null | undefined): string {
  const n = value ?? 0;
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}
