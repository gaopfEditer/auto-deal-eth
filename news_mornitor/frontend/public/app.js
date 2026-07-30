(() => {
  const timelineScroll = document.getElementById("timelineScroll");
  const boardsGrid = document.getElementById("boardsGrid");
  const tickerTrack = document.getElementById("tickerTrack");
  const meta = document.getElementById("meta");
  const boardsHint = document.getElementById("boardsHint");
  const btnIngest = document.getElementById("btnIngest");

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function stars(n) {
    const s = Math.max(0, Math.min(5, Number(n) || 0));
    return "★".repeat(s) + "☆".repeat(5 - s);
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    } catch {
      return iso;
    }
  }

  function biasClass(bias) {
    if (bias === "bullish") return "bullish";
    if (bias === "bearish") return "bearish";
    return "neutral";
  }

  function renderTickers(items) {
    if (!items.length) {
      tickerTrack.innerHTML = '<span class="ticker-item muted">暂无热搜</span>';
      return;
    }
    const html = items
      .map(
        (t) =>
          `<button type="button" class="ticker-item" data-ticker="${escapeAttr(t.symbol)}">$${escapeHtml(
            t.symbol,
          )}<em>×${t.mention_count_24h}</em></button>`,
      )
      .join("");
    tickerTrack.innerHTML = html + html;
  }

  function renderTimeline(items) {
    if (!items.length) {
      timelineScroll.innerHTML =
        '<p class="empty sm">未来 24h 暂无 ≥3★ 宏观事件<br/>可点「刷新源」</p>';
      return;
    }
    const rows = items
      .map((e) => {
        const bc = biasClass(e.bias);
        const nums = [
          e.previous != null ? `<span>前值 <strong>${escapeHtml(e.previous)}</strong></span>` : "",
          e.consensus != null ? `<span>预期 <strong>${escapeHtml(e.consensus)}</strong></span>` : "",
          e.actual != null ? `<span>公布 <strong>${escapeHtml(e.actual)}</strong></span>` : "",
        ]
          .filter(Boolean)
          .join("");
        return `
<article class="tl-item ${bc}">
  <div class="tl-meta">
    <span class="tl-time">${fmtTime(e.publish_at)}</span>
    <span class="tl-country">${escapeHtml(e.country || "")}</span>
    <span class="stars" title="${e.star}星">${stars(e.star)}</span>
    <span class="bias-tag ${bc}">${escapeHtml(e.bias_label || "中性")}</span>
  </div>
  <h3 class="tl-title">${escapeHtml(e.title)}</h3>
  ${e.bias_reason ? `<p class="tl-reason">${escapeHtml(e.bias_reason)}</p>` : ""}
  ${nums ? `<div class="tl-nums">${nums}</div>` : ""}
</article>`;
      })
      .join("");
    timelineScroll.innerHTML = `<div class="tl-rail">${rows}</div>`;
  }

  function renderBoards(boards) {
    if (!boards.length) {
      boardsGrid.innerHTML = '<p class="empty">暂无榜单数据，请刷新源</p>';
      return;
    }
    boardsGrid.innerHTML = boards
      .map((b) => {
        const items = b.items || [];
        const list = items.length
          ? items
              .map((p, i) => {
                const title = p.title || (p.summary || p.content || "").slice(0, 80) || "(无标题)";
                const ticks = (p.mentioned_tickers || [])
                  .slice(0, 4)
                  .map((t) => `<span class="chip">$${escapeHtml(t)}</span>`)
                  .join("");
                return `
<a class="board-row" href="${escapeAttr(p.source_url || "#")}" target="_blank" rel="noopener">
  <span class="rank ${i < 3 ? "top" : ""}">${String(i + 1).padStart(2, "0")}</span>
  <div class="row-body">
    <div class="row-author">${escapeHtml(p.author || "anon")}</div>
    <div class="row-title">${escapeHtml(title)}</div>
    ${ticks ? `<div class="row-ticks">${ticks}</div>` : ""}
  </div>
  <span class="row-score">${Number(p.score || 0).toFixed(1)}</span>
</a>`;
              })
              .join("")
          : '<p class="board-empty">该源暂无热帖</p>';
        return `
<section class="board">
  <header class="board-head">
    <h3>${escapeHtml(b.label || b.platform)}</h3>
    <span class="board-count">${items.length} 条</span>
  </header>
  <div class="board-list">${list}</div>
</section>`;
      })
      .join("");
  }

  async function loadTickers() {
    try {
      const res = await fetch("/api/v1/tickers/trending?limit=10");
      const data = await res.json();
      renderTickers(data.items || []);
    } catch {
      tickerTrack.innerHTML = '<span class="ticker-item muted">热搜加载失败</span>';
    }
  }

  async function loadTimeline(refresh = false) {
    try {
      const q = refresh ? "?refresh=1" : "";
      const res = await fetch(`/api/v1/macro/timeline${q}`);
      const data = await res.json();
      if (!data.ok) {
        timelineScroll.innerHTML = `<p class="err">${escapeHtml(data.error || "加载失败")}</p>`;
        return;
      }
      renderTimeline(data.items || []);
      meta.textContent = `宏观 ${data.items?.length || 0} · ≥${data.min_star}★ · ${data.ahead_hours}h`;
    } catch (e) {
      timelineScroll.innerHTML = `<p class="err">宏观加载失败</p>`;
    }
  }

  async function loadBoards() {
    try {
      const res = await fetch("/api/v1/boards?limit=12&time_range=24h");
      const data = await res.json();
      if (!data.ok) {
        boardsGrid.innerHTML = `<p class="err">${escapeHtml(data.error || "加载失败")}</p>`;
        return;
      }
      renderBoards(data.boards || []);
      const total = (data.boards || []).reduce((n, b) => n + (b.items?.length || 0), 0);
      boardsHint.textContent = `24h 热度分 · 共 ${total} 条`;
    } catch {
      boardsGrid.innerHTML = '<p class="err">榜单加载失败</p>';
    }
  }

  btnIngest.addEventListener("click", async () => {
    btnIngest.disabled = true;
    btnIngest.textContent = "抓取中…";
    try {
      await fetch("/api/v1/ingest?limit=40", { method: "POST" });
      await Promise.all([loadTickers(), loadTimeline(true), loadBoards()]);
    } catch (e) {
      alert("抓取失败: " + e);
    } finally {
      btnIngest.disabled = false;
      btnIngest.textContent = "刷新源";
    }
  });

  loadTickers();
  loadTimeline();
  loadBoards();
})();
