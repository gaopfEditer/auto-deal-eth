/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 币安 U 本位 REST，默认 https://fapi.binance.com */
  readonly VITE_BINANCE_FAPI_BASE?: string;
  /** client=浏览器直连拉 K（默认）；backend=仍走服务端代拉 */
  readonly VITE_CHART_KLINES_SOURCE?: "client" | "backend";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
