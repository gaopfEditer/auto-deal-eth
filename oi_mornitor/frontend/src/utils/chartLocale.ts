import { TickMarkType, type Time } from "lightweight-charts";

const LOCALE = "zh-CN";

function toDate(time: Time): Date | null {
  if (typeof time === "number") return new Date(time * 1000);
  if (typeof time === "string") return new Date(time);
  if (time && typeof time === "object" && "year" in time) {
    return new Date(Date.UTC(time.year, time.month - 1, time.day));
  }
  return null;
}

/** 币安 K 线为 UTC 时间戳，格式化为浏览器本地时区（修复轴上显示 UTC 中午的问题）。 */
export function formatChartTickMark(time: Time, tickMarkType: TickMarkType, locale = LOCALE): string {
  const d = toDate(time);
  if (!d) return "";

  switch (tickMarkType) {
    case TickMarkType.Year:
      return d.toLocaleDateString(locale, { year: "numeric" });
    case TickMarkType.Month:
      return d.toLocaleDateString(locale, { month: "short" });
    case TickMarkType.DayOfMonth:
      return d.toLocaleDateString(locale, { day: "numeric", month: "short" });
    case TickMarkType.TimeWithSeconds:
      return d.toLocaleString(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    case TickMarkType.Time:
    default:
      return d.toLocaleString(locale, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
  }
}

export function formatChartCrosshairTime(time: Time, locale = LOCALE): string {
  const d = toDate(time);
  if (!d) return "";
  return d.toLocaleString(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatCandleLocalTime(timeSec: number, locale = LOCALE): string {
  return new Date(timeSec * 1000).toLocaleString(locale, {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export const chartLocalization = {
  locale: LOCALE,
  dateFormat: "MM-dd",
  timeFormatter: formatChartCrosshairTime,
};

export const chartTimeScaleOptions = {
  timeVisible: true,
  secondsVisible: false,
  barSpacing: 7,
  minBarSpacing: 0.35,
  rightOffset: 6,
  fixLeftEdge: false,
  fixRightEdge: false,
  tickMarkFormatter: formatChartTickMark,
};
