// quote0-widget.js — JSBox iOS 桌面小组件
// 显示和 Quote/0 墨水屏完全同步的 Codex + DeepSeek 用量数据
// 改下面 CONFIG 的三个值即可使用

// ═══════════════════════ CONFIG ═══════════════════════
const CODEX_TOKEN  = "";  // ~/.codex/auth.json → tokens.access_token
const CODEX_ACCT   = "";  // ~/.codex/auth.json → tokens.account_id（可选）
const DEEPSEEK_KEY = "";  // DeepSeek API key（sk-...）
// ══════════════════════════════════════════════════════

// ── 数据获取 ──────────────────────────────────────────

function getCodex() {
  try {
    const headers = {
      "Authorization": "Bearer " + CODEX_TOKEN,
      "Accept": "application/json"
    };
    if (CODEX_ACCT) headers["ChatGPT-Account-Id"] = CODEX_ACCT;

    const r = $http.get({
      url: "https://chatgpt.com/backend-api/wham/usage",
      header: headers,
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };

    const d = r.data;
    const rl = d.rate_limit || {};
    const p = rl.primary_window || {};
    const s = rl.secondary_window || {};
    return {
      ok: true,
      sUsed: p.used_percent || 0,
      sReset: p.reset_at || null,
      lUsed: s.used_percent || 0,
      lReset: s.reset_at || null
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
