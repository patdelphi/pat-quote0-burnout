// quote0-widget.js — JSBox iOS 桌面小组件
// 显示和 Quote/0 墨水屏完全同步的 Codex + DeepSeek 用量数据
// 改下面 CONFIG 的三个值即可使用

// ═══════════════════════ CONFIG ═══════════════════════
const CODEX_TOKEN  = "";  // OAuth access token（仅小组件直连回退接口需要）
const CODEX_ACCT   = "";  // ~/.codex/auth.json → tokens.account_id（可选）
const DEEPSEEK_KEY = "";  // DeepSeek API key（sk-...）
const CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage";
const CODEX_LEGACY_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";
// ══════════════════════════════════════════════════════

// ── 数据获取 ──────────────────────────────────────────

function getCodex() {
  try {
    const headers = {
      "Authorization": "Bearer " + CODEX_TOKEN,
      "Accept": "application/json"
    };
    if (CODEX_ACCT) headers["ChatGPT-Account-Id"] = CODEX_ACCT;

    let d = null;
    let lastError = null;
    // iOS 小组件无法启动本机 app-server，因此使用新的 Codex HTTP 路径，
    // 并保留旧路径以兼容尚未切换的服务端。
    for (const url of [CODEX_USAGE_URL, CODEX_LEGACY_USAGE_URL]) {
      const r = $http.get({ url: url, header: headers, timeout: 8 });
      if (!r.error && r.data) {
        d = r.data;
        break;
      }
      lastError = r.error;
    }
    if (!d) return { ok: false, msg: lastError ? "请求失败" : "无数据" };

    const rl = d.rateLimits || d.rate_limit || {};
    const p = rl.primary || rl.primary_window || {};
    const s = rl.secondary || rl.secondary_window || {};
    const pUsed = p.usedPercent !== undefined ? p.usedPercent : p.used_percent;
    const sUsed = s.usedPercent !== undefined ? s.usedPercent : s.used_percent;
    const pReset = p.resetsAt !== undefined ? p.resetsAt : p.reset_at;
    const sReset = s.resetsAt !== undefined ? s.resetsAt : s.reset_at;
    const resetCredits = d.rateLimitResetCredits || d.rate_limit_reset_credits || {};
    const countValue = resetCredits.availableCount !== undefined
      ? resetCredits.availableCount : resetCredits.available_count;
    const resetCount = countValue !== undefined && countValue !== null && Number.isFinite(Number(countValue))
      ? Number(countValue) : null;
    const cardList = Array.isArray(resetCredits.credits) ? resetCredits.credits : [];
    const firstCard = cardList.find(function(card) {
      return card && (card.status === undefined || card.status === "available");
    });
    const resetExpires = firstCard
      ? (firstCard.expiresAt !== undefined ? firstCard.expiresAt : firstCard.expires_at)
      : null;
    return {
      ok: true,
      sUsed: Number(pUsed) || 0,
      sReset: pReset || null,
      lUsed: Number(sUsed) || 0,
      lReset: sReset || null,
      resetCount: resetCount,
      resetExpires: resetExpires || null
    };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

function getDeepSeek() {
  if (!DEEPSEEK_KEY) return { ok: false, msg: "无 key" };
  try {
    const r = $http.get({
      url: "https://api.deepseek.com/user/balance",
      header: { "Authorization": "Bearer " + DEEPSEEK_KEY, "Accept": "application/json" },
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };

    const infos = r.data.balance_infos || [];
    const usd = infos.find(x => x.currency === "USD") || infos[0];
    if (!usd) return { ok: false, msg: "无余额" };

    const curr = usd.currency || "USD";
    return {
      ok: true,
      balance: usd.total_balance || 0,
      symbol: curr === "CNY" ? "¥" : curr === "EUR" ? "€" : "$",
      avail: r.data.is_available !== false
    };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

// ── 工具函数 ──────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return "";
  const secs = Math.max(0, Math.floor(ts - Date.now() / 1000));
  if (secs <= 0) return "now";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return d + "d" + h + "h";
  if (h > 0) return m > 0 ? h + "h" + pad(m) + "m" : h + "h";
  return m + "m";
}

function pad(n) { return n < 10 ? "0" + n : String(n); }

function pctBar(used, w) {
  const rem = 100 - used;
  const fill = Math.round(rem / 100 * w);
  let s = "";
  for (let i = 0; i < fill; i++) s += "█";
  for (let i = fill; i < w; i++) s += "░";
  return s;
}

function cxStatus(u) {
  if (u >= 90) return "●";
  if (u >= 70) return "◐";
  return "○";
}

function dsStatus(b, a) {
  if (!a || b < 3) return "●";
  if (b < 10) return "◐";
  return "○";
}

// ── Widget 渲染 ───────────────────────────────────────

$widget.setTimeline(function(ctx) {
  const cx = getCodex();
  const ds = getDeepSeek();
  const family = ctx.family;  // 0=small, 1=medium, 2=large

  const now = new Date();
  const timeStr = pad(now.getHours()) + ":" + pad(now.getMinutes());

  // 根据 widget 大小调整参数
  const compact = family === 0;
  const fSize  = compact ? 9 : 10;
  const sSize  = compact ? 7 : 8;
  const lh     = compact ? 12 : 14;
  const barW   = compact ? 8 : 12;

  const rows = [];

  // 标题行：时间 + 状态
  const cxBadge = cx.ok ? cxStatus(cx.sUsed) : "✕";
  const dsBadge = ds.ok ? dsStatus(ds.balance, ds.avail) : "✕";
  rows.push({ text: "C " + cxBadge + "  D " + dsBadge + "     " + timeStr, size: sSize });

  if (cx.ok) {
    const sr = 100 - cx.sUsed;
    const lr = 100 - cx.lUsed;
    rows.push({ text: "5h " + pctBar(cx.sUsed, barW) + " " + sr.toFixed(0) + "% " + fmtTime(cx.sReset), size: fSize });
    rows.push({ text: "Wk " + pctBar(cx.lUsed, barW) + " " + lr.toFixed(0) + "% " + fmtTime(cx.lReset), size: fSize });
    if (cx.resetCount !== null) {
      let resetText = "Reset " + cx.resetCount;
      if (cx.resetExpires) resetText += " exp " + fmtTime(cx.resetExpires);
      rows.push({ text: resetText, size: sSize });
    }
  } else {
    rows.push({ text: "Codex: " + (cx.msg || "error"), size: fSize });
  }

  // 分隔
  rows.push({ text: "—".repeat(compact ? 14 : 20), size: sSize });

  if (ds.ok) {
    rows.push({ text: ds.symbol + ds.balance.toFixed(2), size: fSize + 4 });
  } else {
    rows.push({ text: "DeepSeek: " + (ds.msg || "error"), size: fSize });
  }

  const padX = 6;
  const padY = 4;

  const views = rows.map(function(row, i) {
    return {
      type: "label",
      props: {
        text: row.text,
        font: $font("Menlo", row.size),
        textColor: $color("#000"),
        align: $align.left,
        frame: $rect(padX, padY + i * lh, ctx.displaySize.width - padX * 2, lh)
      }
    };
  });

  return {
    type: "view",
    props: {
      bgcolor: $color("#fff"),
      frame: $rect(0, 0, ctx.displaySize.width, padY * 2 + rows.length * lh)
    },
    views: views
  };
});
