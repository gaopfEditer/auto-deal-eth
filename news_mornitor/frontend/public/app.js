(() => {
  const timelineScroll = document.getElementById("timelineScroll");
  const boardsGrid = document.getElementById("boardsGrid");
  const tickerTrack = document.getElementById("tickerTrack");
  const meta = document.getElementById("meta");
  const boardsHint = document.getElementById("boardsHint");
  const fetchStatusEl = document.getElementById("fetchStatus");
  const btnFetchStop = document.getElementById("btnFetchStop");
  const btnFetchStart = document.getElementById("btnFetchStart");
  const btnFetchNow = document.getElementById("btnFetchNow");
  const btnHistory = document.getElementById("btnHistory");
  const historyDrawer = document.getElementById("historyDrawer");
  const historyList = document.getElementById("historyList");
  const btnCloseHistory = document.getElementById("btnCloseHistory");
  const btnClearHistory = document.getElementById("btnClearHistory");
  const postModal = document.getElementById("postModal");
  const postModalBackdrop = document.getElementById("postModalBackdrop");
  const postModalTitle = document.getElementById("postModalTitle");
  const postModalMeta = document.getElementById("postModalMeta");
  const postModalBody = document.getElementById("postModalBody");
  const postModalNote = document.getElementById("postModalNote");
  const btnClosePost = document.getElementById("btnClosePost");
  const btnPostFav = document.getElementById("btnPostFav");
  const btnPostOpen = document.getElementById("btnPostOpen");

  const HISTORY_KEY = "cryptopulse_history_v1";
  const HISTORY_MAX = 200;
  let historyTab = "all";
  let activePost = null;

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
        timeZone: "Asia/Shanghai",
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

  /** 仅真帖 permalink 可外跳；广场首页 / mock 空链一律不算 */
  function isRealPermalink(url) {
    if (!url || url === "#" || !/^https?:\/\//i.test(url)) return false;
    try {
      const u = new URL(url);
      const path = u.pathname.toLowerCase().replace(/\/+$/, "") || "/";
      const hubs = [
        "/zh-cn/square",
        "/square",
        "/zh-cn/insights",
        "/insights",
        "/zh-hans/copy-trading/signal-trader",
        "/trade/spot/feed",
        "/zh-my/trade/spot/feed",
        "/r/cryptocurrency/hot",
        "/markets/cryptocurrencies/ideas",
        "/news",
      ];
      if (hubs.some((h) => path === h || path.endsWith(h))) return false;
      if (path === "/" || path === "") return false;
      return (
        /\/(post|posts|comments|chart|conversations|status|idea)s?\b/i.test(path) ||
        /\/ideas\/[a-z0-9_-]+/i.test(path) ||
        /reddit\.com\/r\/[^/]+\/comments\//i.test(url) ||
        /cryptopanic\.com\/news\/.+/i.test(url)
      );
    } catch {
      return false;
    }
  }

  function loadHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      const data = raw ? JSON.parse(raw) : { items: [] };
      return Array.isArray(data.items) ? data.items : [];
    } catch {
      return [];
    }
  }

  function saveHistory(items) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify({ items: items.slice(0, HISTORY_MAX) }));
  }

  function postSnapshot(p) {
    const title = p.title || (p.summary || p.content || "").slice(0, 80) || "(无标题)";
    const content = String(p.content || p.summary || title || "");
    return {
      id: String(p.id || `${p.platform}:${p.external_id}`),
      platform: p.platform || "",
      author: p.author || "",
      title,
      content,
      source_url: p.source_url || "",
      like_count: Number(p.like_count || 0),
      comment_count: Number(p.comment_count || 0),
      score: Number(p.score || 0),
      published_at: p.published_at || "",
    };
  }

  function upsertHistory(snap, { click = false, favorite = null } = {}) {
    const items = loadHistory();
    const now = new Date().toISOString();
    let row = items.find((x) => x.id === snap.id);
    if (!row) {
      row = { ...snap, clicked_at: null, favorited_at: null };
      items.unshift(row);
    } else {
      Object.assign(row, snap);
      const idx = items.indexOf(row);
      if (idx > 0) {
        items.splice(idx, 1);
        items.unshift(row);
      }
    }
    if (click) row.clicked_at = now;
    if (favorite === true) row.favorited_at = now;
    if (favorite === false) row.favorited_at = null;
    if (!row.clicked_at && !row.favorited_at) {
      const i = items.indexOf(row);
      if (i >= 0) items.splice(i, 1);
    }
    saveHistory(items);
    if (!historyDrawer.hidden) renderHistory();
    return row;
  }

  function isFavorited(id) {
    return loadHistory().some((x) => x.id === id && x.favorited_at);
  }

  function filteredHistory() {
    const items = loadHistory();
    if (historyTab === "fav") return items.filter((x) => x.favorited_at);
    if (historyTab === "click") return items.filter((x) => x.clicked_at);
    return items.filter((x) => x.clicked_at || x.favorited_at);
  }

  function openPostDetail(snap) {
    if (!snap || !snap.id) return;
    activePost = snap;
    upsertHistory(snap, { click: true });
    const title = snap.title || "(无标题)";
    const body = snap.content || title;
    postModalTitle.textContent = title;
    postModalMeta.textContent = `${snap.platform || "—"} · ${snap.author || "anon"} · 赞 ${snap.like_count || 0} · 评 ${snap.comment_count || 0} · ${fmtTime(snap.published_at)}`;
    postModalBody.textContent = body;
    const fav = isFavorited(snap.id);
    btnPostFav.textContent = fav ? "取消收藏" : "收藏";
    const real = isRealPermalink(snap.source_url);
    if (real) {
      btnPostOpen.hidden = false;
      btnPostOpen.href = snap.source_url;
      postModalNote.textContent = "已验证为帖子链接，可打开原文";
    } else {
      btnPostOpen.hidden = true;
      btnPostOpen.removeAttribute("href");
      postModalNote.textContent = "演示/无深链：此处正文即列表内容，不跳外站假页";
    }
    postModal.hidden = false;
  }

  function closePostDetail() {
    postModal.hidden = true;
    activePost = null;
  }

  function renderHistory() {
    const items = filteredHistory();
    if (!items.length) {
      historyList.innerHTML = '<p class="empty sm">暂无记录</p>';
      return;
    }
    historyList.innerHTML = items
      .map((h) => {
        const when = h.favorited_at || h.clicked_at;
        const tags = [
          h.favorited_at ? '<span class="hist-tag fav">收藏</span>' : "",
          h.clicked_at ? '<span class="hist-tag">点击</span>' : "",
        ]
          .filter(Boolean)
          .join("");
        const payload = escapeAttr(JSON.stringify(h));
        return `
<article class="hist-row" data-id="${escapeAttr(h.id)}">
  <div>
    <div class="hist-meta">${escapeHtml(h.platform)} · ${fmtTime(when)} · 赞 ${h.like_count} · 评 ${h.comment_count}</div>
    <button type="button" class="hist-title" data-post="${payload}">${escapeHtml(h.title)}</button>
    <div class="hist-tags">${tags}</div>
  </div>
  <div class="hist-ops">
    <button type="button" class="hist-fav" title="${h.favorited_at ? "取消收藏" : "收藏"}">${h.favorited_at ? "★" : "☆"}</button>
    <button type="button" class="hist-del" title="删除">✕</button>
  </div>
</article>`;
      })
      .join("");
  }

  function openHistory() {
    historyDrawer.hidden = false;
    renderHistory();
  }

  function closeHistory() {
    historyDrawer.hidden = true;
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
        '<p class="empty sm">暂无真实宏观事件<br/>需成功抓取金十日历后展示</p>';
      return;
    }
    // 按时间升序：过去在上，未来在下；默认滚到「现在」附近
    const sorted = [...items].sort((a, b) => {
      const ta = Date.parse(a.publish_at || "") || 0;
      const tb = Date.parse(b.publish_at || "") || 0;
      return ta - tb;
    });
    const nowMs = Date.now();
    let nearestIdx = 0;
    let nearestDist = Infinity;
    sorted.forEach((e, i) => {
      const t = Date.parse(e.publish_at || "") || 0;
      const d = Math.abs(t - nowMs);
      if (d < nearestDist) {
        nearestDist = d;
        nearestIdx = i;
      }
    });
    // 若有「已过→待定」分界，优先锚定到第一个待定（更贴近「当前」）
    const firstUpcoming = sorted.findIndex((e) => e.phase !== "past");
    const anchorIdx = firstUpcoming >= 0 ? firstUpcoming : nearestIdx;

    const parts = [];
    let nowInserted = false;
    sorted.forEach((e, i) => {
      const bc = biasClass(e.bias);
      const phase = e.phase === "past" ? "past" : "upcoming";
      const phaseLabel = phase === "past" ? "已过" : "待定";
      if (!nowInserted && firstUpcoming >= 0 && i === firstUpcoming) {
        parts.push(`<div class="tl-now" id="tlNowMarker" aria-label="当前时间">现在 · 北京时间</div>`);
        nowInserted = true;
      }
      const nums = [
        e.previous != null ? `<span>前值 <strong>${escapeHtml(e.previous)}</strong></span>` : "",
        e.consensus != null ? `<span>预期 <strong>${escapeHtml(e.consensus)}</strong></span>` : "",
        e.actual != null ? `<span>公布 <strong>${escapeHtml(e.actual)}</strong></span>` : "",
      ]
        .filter(Boolean)
        .join("");
      parts.push(`
<article class="tl-item ${bc} ${phase}" data-idx="${i}" data-phase="${phase}">
  <div class="tl-meta">
    <span class="tl-time" title="北京时间">${fmtTime(e.publish_at)}</span>
    <span class="tl-phase ${phase}">${phaseLabel}</span>
    <span class="tl-country">${escapeHtml(e.country || "")}</span>
    <span class="stars" title="${e.star}星">${stars(e.star)}</span>
    <span class="bias-tag ${bc}">${escapeHtml(e.bias_label || "中性")}</span>
  </div>
  <h3 class="tl-title">${escapeHtml(e.title)}</h3>
  ${e.bias_reason ? `<p class="tl-reason">${escapeHtml(e.bias_reason)}</p>` : ""}
  ${nums ? `<div class="tl-nums">${nums}</div>` : ""}
</article>`);
    });
    if (!nowInserted && firstUpcoming < 0) {
      // 全部已过：锚点放在末尾（最接近现在）
      parts.push(`<div class="tl-now" id="tlNowMarker" aria-label="当前时间">现在 · 北京时间</div>`);
    }
    timelineScroll.innerHTML = `<div class="tl-rail">${parts.join("")}</div>`;
    requestAnimationFrame(() => {
      const marker = document.getElementById("tlNowMarker");
      const fallback = timelineScroll.querySelector(`.tl-item[data-idx="${anchorIdx}"]`);
      const target = marker || fallback;
      if (!target) return;
      const parentRect = timelineScroll.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const absTop = targetRect.top - parentRect.top + timelineScroll.scrollTop;
      timelineScroll.scrollTop = Math.max(0, absTop - timelineScroll.clientHeight * 0.28);
    });
  }

  function renderBoards(boards) {
    if (!boards.length) {
      boardsGrid.innerHTML = '<p class="empty">暂无真实抓取结果<br/>请点「立即获取」或等待定时调度</p>';
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
                const likes = Number(p.like_count || 0);
                const comments = Number(p.comment_count || 0);
                const pid = String(p.id || `${p.platform}:${p.external_id}`);
                const favOn = isFavorited(pid);
                const payload = escapeAttr(JSON.stringify(postSnapshot(p)));
                return `
<div class="board-row" data-id="${escapeAttr(pid)}">
  <span class="rank ${i < 3 ? "top" : ""}">${String(i + 1).padStart(2, "0")}</span>
  <button type="button" class="row-main" data-post="${payload}" title="查看与列表一致的正文">
    <div class="row-author">${escapeHtml(p.author || "anon")}</div>
    <div class="row-title">${escapeHtml(title)}</div>
    ${ticks ? `<div class="row-ticks">${ticks}</div>` : ""}
    <div class="row-eng">赞 ${likes} · 评 ${comments}</div>
  </button>
  <div class="row-side">
    <button type="button" class="btn-fav ${favOn ? "on" : ""}" data-post="${payload}" title="${favOn ? "取消收藏" : "收藏"}">${favOn ? "★" : "☆"}</button>
    <span class="row-score" title="热度分">${Number(p.score || 0).toFixed(1)}</span>
  </div>
</div>`;
              })
              .join("")
          : '<p class="board-empty">该源暂无过门槛影响力帖</p>';
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

  function parsePostAttr(el) {
    try {
      return JSON.parse(el.getAttribute("data-post") || "{}");
    } catch {
      return null;
    }
  }

  boardsGrid.addEventListener("click", (ev) => {
    const favBtn = ev.target.closest(".btn-fav");
    if (favBtn) {
      ev.preventDefault();
      ev.stopPropagation();
      const snap = parsePostAttr(favBtn);
      if (!snap || !snap.id) return;
      const on = isFavorited(snap.id);
      upsertHistory(snap, { favorite: !on });
      favBtn.classList.toggle("on", !on);
      favBtn.textContent = !on ? "★" : "☆";
      favBtn.title = !on ? "取消收藏" : "收藏";
      return;
    }
    const main = ev.target.closest("button.row-main");
    if (main) {
      const snap = parsePostAttr(main);
      openPostDetail(snap);
    }
  });

  historyList.addEventListener("click", (ev) => {
    const row = ev.target.closest(".hist-row");
    if (!row) return;
    const id = row.getAttribute("data-id");
    const items = loadHistory();
    const item = items.find((x) => x.id === id);
    if (!item) return;
    if (ev.target.closest(".hist-del")) {
      saveHistory(items.filter((x) => x.id !== id));
      renderHistory();
      loadBoards();
      return;
    }
    if (ev.target.closest(".hist-fav")) {
      upsertHistory(item, { favorite: !item.favorited_at });
      loadBoards();
      return;
    }
    if (ev.target.closest(".hist-title")) {
      openPostDetail(item);
    }
  });

  historyDrawer.querySelectorAll(".hist-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      historyTab = btn.getAttribute("data-tab") || "all";
      historyDrawer.querySelectorAll(".hist-tab").forEach((b) => b.classList.toggle("active", b === btn));
      renderHistory();
    });
  });

  btnHistory.addEventListener("click", () => {
    if (historyDrawer.hidden) openHistory();
    else closeHistory();
  });
  btnCloseHistory.addEventListener("click", closeHistory);
  btnClearHistory.addEventListener("click", () => {
    if (historyTab === "all") saveHistory([]);
    else if (historyTab === "fav") {
      saveHistory(
        loadHistory()
          .map((x) => ({ ...x, favorited_at: null }))
          .filter((x) => x.clicked_at),
      );
    } else if (historyTab === "click") {
      saveHistory(
        loadHistory()
          .map((x) => ({ ...x, clicked_at: null }))
          .filter((x) => x.favorited_at),
      );
    }
    renderHistory();
    loadBoards();
  });

  btnClosePost.addEventListener("click", closePostDetail);
  postModalBackdrop.addEventListener("click", closePostDetail);
  btnPostFav.addEventListener("click", () => {
    if (!activePost) return;
    const on = isFavorited(activePost.id);
    upsertHistory(activePost, { favorite: !on });
    btnPostFav.textContent = !on ? "取消收藏" : "收藏";
    loadBoards();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !postModal.hidden) closePostDetail();
  });

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
      const pastN = (data.items || []).filter((x) => x.phase === "past").length;
      const futN = (data.items || []).length - pastN;
      meta.textContent = `宏观 ${data.items?.length || 0}（已过 ${pastN} / 待定 ${futN}）· ≥${data.min_star}★ · 北京时间 −${Math.round((data.behind_hours || 72) / 24)}d～+${Math.round((data.ahead_hours || 72) / 24)}d`;
    } catch (e) {
      timelineScroll.innerHTML = `<p class="err">宏观加载失败</p>`;
    }
  }

  async function loadBoards() {
    try {
      const res = await fetch("/api/v1/boards?limit=20&time_range=3d");
      const data = await res.json();
      if (!data.ok) {
        boardsGrid.innerHTML = `<p class="err">${escapeHtml(data.error || "加载失败")}</p>`;
        return;
      }
      renderBoards(data.boards || []);
      const total = (data.boards || []).reduce((n, b) => n + (b.items?.length || 0), 0);
      const likes = data.min_likes ?? 200;
      const comments = data.min_comments ?? 30;
      const histN = loadHistory().filter((x) => x.clicked_at || x.favorited_at).length;
      boardsHint.textContent = data.use_mock
        ? `调试 MOCK · 赞≥${likes} 或 评≥${comments} · ${total} 条`
        : data.influential_only
          ? `真实抓取 · 赞≥${likes} 或 评≥${comments} · ${data.time_range || "3d"} · ${total} 条 · 历史 ${histN}`
          : `真实抓取 · ${total} 条 · 历史 ${histN}`;
    } catch {
      boardsGrid.innerHTML = '<p class="err">榜单加载失败</p>';
    }
  }

  async function refreshAll() {
    await Promise.all([loadTickers(), loadTimeline(false), loadBoards(), loadFetchStatus()]);
  }

  function fmtRemain(sec) {
    const n = Math.max(0, Math.floor(Number(sec) || 0));
    if (n <= 0) return "即将";
    if (n < 60) return `${n}s`;
    const m = Math.floor(n / 60);
    const s = n % 60;
    return s ? `${m}m${s}s` : `${m}m`;
  }

  function applyFetchStatus(data) {
    if (!fetchStatusEl || !data) return;
    fetchStatusEl.classList.remove("is-on", "is-off", "is-run");
    if (data.running) {
      fetchStatusEl.textContent = "抓取中…";
      fetchStatusEl.classList.add("is-run");
    } else if (data.enabled) {
      const next = data.retry_after_sec > 0 ? ` · 下次 ${fmtRemain(data.retry_after_sec)}` : "";
      fetchStatusEl.textContent = `定时开${next}`;
      fetchStatusEl.classList.add("is-on");
    } else {
      fetchStatusEl.textContent = "定时停";
      fetchStatusEl.classList.add("is-off");
    }
    if (btnFetchStop) btnFetchStop.disabled = !!data.running || !data.enabled;
    if (btnFetchStart) btnFetchStart.disabled = !!data.running || !!data.enabled;
    if (btnFetchNow) btnFetchNow.disabled = !!data.running;
  }

  async function loadFetchStatus() {
    try {
      const res = await fetch("/api/v1/fetch/status");
      const data = await res.json();
      applyFetchStatus(data);
      return data;
    } catch {
      if (fetchStatusEl) fetchStatusEl.textContent = "状态未知";
      return null;
    }
  }

  btnFetchStop?.addEventListener("click", async () => {
    btnFetchStop.disabled = true;
    try {
      const res = await fetch("/api/v1/fetch/stop", { method: "POST" });
      applyFetchStatus(await res.json());
    } catch (e) {
      alert("停止失败: " + e);
    } finally {
      await loadFetchStatus();
    }
  });

  btnFetchStart?.addEventListener("click", async () => {
    btnFetchStart.disabled = true;
    try {
      const res = await fetch("/api/v1/fetch/start", { method: "POST" });
      applyFetchStatus(await res.json());
    } catch (e) {
      alert("开始失败: " + e);
    } finally {
      await loadFetchStatus();
    }
  });

  btnFetchNow?.addEventListener("click", async () => {
    btnFetchNow.disabled = true;
    if (fetchStatusEl) {
      fetchStatusEl.textContent = "抓取中…";
      fetchStatusEl.classList.add("is-run");
    }
    try {
      const res = await fetch("/api/v1/fetch/now?limit=40", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (data.skipped && data.reason === "already_running") {
        alert("已有抓取在进行中，请稍后再试");
      } else if (data.error) {
        alert("抓取失败: " + data.error);
      }
      if (data.status) applyFetchStatus(data.status);
      await Promise.all([loadTickers(), loadTimeline(true), loadBoards(), loadFetchStatus()]);
    } catch (e) {
      alert("抓取失败: " + e);
      await loadFetchStatus();
    }
  });

  loadTickers();
  loadTimeline();
  loadBoards();
  loadFetchStatus();
  // 仅刷新展示，绝不自动 ingest（抓取只由后端调度 / 本页按钮）
  setInterval(() => refreshAll(), 60_000);
  setInterval(() => loadFetchStatus(), 15_000);
})();
