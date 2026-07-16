/** 紧凑金额：热钱看板统一 M（百万美金），≥1B 用 B */
function fmtCompactCore(
  n: number,
  digits = 2,
  signed = false,
): string {
  const abs = Math.abs(n);
  const prefix = n < 0 ? "-" : signed && n > 0 ? "+" : "";

  if (abs >= 1e9) {
    return `${prefix}${(abs / 1e9).toFixed(digits)}B`;
  }
  return `${prefix}${(abs / 1e6).toFixed(digits)}M`;
}

/** 榜单量级：M / K / B */
export function fmtMk(n: number | null | undefined, signed = true, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  if (v === 0) return "0";
  const abs = Math.abs(v);
  const prefix = v < 0 ? "-" : signed && v > 0 ? "+" : "";
  if (abs >= 1e9) return `${prefix}${(abs / 1e9).toFixed(digits)}B`;
  if (abs >= 1e6) return `${prefix}${(abs / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${prefix}${(abs / 1e3).toFixed(digits)}K`;
  return `${prefix}${Math.round(abs)}`;
}

/** 金额 / OI / 成交额（无正号） */
export function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return fmtCompactCore(Number(n), digits, false);
}

/** 变动量（带 +/- 号） */
export function fmtDelta(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  if (v === 0) return "0";
  return fmtCompactCore(v, digits, true);
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/** pattern-chart-meta 价格有效数字位数 */
export const META_PRICE_SIGFIGS = 5;

/** 与头部 meta 价格一致的展示 */
export function fmtMetaPrice(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toPrecision(META_PRICE_SIGFIGS);
}

/**
 * 从 toPrecision(META_PRICE_SIGFIGS) 结果推断小数位数，供 K 线价格轴对齐 meta。
 */
export function priceDecimalsFromMetaPrice(n: number | null | undefined): number {
  if (n == null || !Number.isFinite(n)) return 2;
  const s = Math.abs(Number(n)).toPrecision(META_PRICE_SIGFIGS);
  if (/e/i.test(s)) {
    const [base, expStr] = s.split(/e/i);
    const exp = Number(expStr);
    const fracLen = (base.split(".")[1] ?? "").length;
    return Math.min(10, Math.max(0, fracLen - exp));
  }
  const i = s.indexOf(".");
  return i < 0 ? 0 : s.length - i - 1;
}

export function chartPriceFormat(n: number | null | undefined): {
  type: "price";
  precision: number;
  minMove: number;
} {
  const precision = priceDecimalsFromMetaPrice(n);
  const minMove = precision <= 0 ? 1 : Number((10 ** -precision).toFixed(precision));
  return { type: "price", precision, minMove };
}

export function fmtTs(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

export function deltaClass(v: number): string {
  if (v > 0) return "pos";
  if (v < 0) return "neg";
  return "";
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pump: "🔥 涌入",
    dump: "🩸 撤离",
    warming: "⏳ 预热",
    normal: "正常",
    suppressed: "🔇 抑制",
  };
  return map[status] ?? "正常";
}
