export function displaySymbol(symbol: string): string {
  return symbol.replace(/USDT$/i, "");
}

export function coinInitial(symbol: string): string {
  const base = displaySymbol(symbol);
  return base.slice(0, 1).toUpperCase();
}
