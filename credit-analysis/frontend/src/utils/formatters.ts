export function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "—";
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 1_000) {
    formatted = Math.round(abs).toLocaleString("en-US");
  } else if (abs >= 1) {
    formatted = abs.toFixed(1);
  } else {
    formatted = abs.toFixed(2);
  }
  return value < 0 ? `(${formatted})` : formatted;
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  } catch {
    return dateStr;
  }
}

export function formatCoupon(
  coupon_rate: number | null,
  coupon_type: string | null,
  floating_benchmark: string | null,
  floating_spread: number | null
): string {
  if (!coupon_rate && !floating_spread) return "—";
  if (coupon_type === "floating" && floating_benchmark) {
    const spread = floating_spread ? `+${(floating_spread * 10000).toFixed(0)}bps` : "";
    return `${floating_benchmark}${spread}`;
  }
  return coupon_rate ? `${(coupon_rate * 100).toFixed(3).replace(/\.?0+$/, "")}%` : "—";
}
