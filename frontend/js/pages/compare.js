/* So sánh hai lần chạy: kết luận, chi phí, vòng điều tra, từng agent, và những gì khác nhau, nói bằng lời.
   Dựng từ cùng nguồn như trang theo dõi (sự kiện trace), nên không có số liệu riêng nào có thể lệch. */
import { api, esc, fmt, html, icon, labelOf, mount, on, pageHead, raw, verdict } from '../lib.js';
import { agentCards, agentName, buildModel, ruleInfo } from '../story.js';

async function load(id) {
  const detail = await api(`/api/runs/${encodeURIComponent(id)}`);
  const events = []; let after = 0;
  for (;;) {
    const r = await api(`/api/runs/${encodeURIComponent(id)}/events?after=${after}&limit=1000`);
    events.push(...r.events); if (r.events.length < 1000) break; after = r.events[r.events.length - 1].seq;
  }
  const model = buildModel(events);
  const steps = model.reqs.flatMap((r) => r.rounds.flatMap((x) => x.steps));
  const cards = agentCards(model);
  const v = detail.verdicts?.[0] || model.reqs.find((r) => r.verdict)?.verdict?.payload || null;
  const span = events.length > 1 ? (events[events.length - 1].ts_ns - events[0].ts_ns) / 1e9 : null;
  return {
    id, detail, model, cards, verdict: v,
    m: {
      tokens: cards.reduce((a, c) => a + c.tokens, 0),
      seconds: detail.started_at && detail.ended_at ? detail.ended_at - detail.started_at : span,
      rounds: Math.max(0, ...model.reqs.map((r) => Math.max(0, ...r.rounds.map((x) => x.n)))),
      tools: cards.reduce((a, c) => a + c.tools, 0),
      evidence: model.reqs.reduce((a, r) => a + r.rounds.flatMap((x) => x.steps).reduce((b, s) => b + (s.result?.payload.new_evidence || 0), 0), 0),
      failures: cards.reduce((a, c) => a + c.fail, 0),
      denied: cards.reduce((a, c) => a + c.denied, 0),
      retries: cards.reduce((a, c) => a + c.retries, 0),
      steps: steps.length,
    },
    tasks: model.reqs.flatMap((r) => r.rounds.filter((x) => x.n > 0).map((x) => ({ n: x.n, tasks: x.steps.filter((s) => s.to !== 'planner').map((s) => s.task || s.to) }))),
  };
}

const pct = (a, b) => (a ? Math.round(((b - a) / a) * 100) : null);
/* lower = tốt hơn (chi phí, lỗi); null = chỉ nêu khác biệt, không đánh giá tốt/xấu */
const ROWS = [
  ['tokens', 'Token tiêu thụ', 'lower', fmt.tok], ['seconds', 'Thời gian', 'lower', (x) => (x == null ? '–' : fmt.sec(x))], ['rounds', 'Số vòng điều tra', 'lower', String],
  ['steps', 'Số lần giao việc', 'lower', String], ['tools', 'Lần gọi công cụ', 'lower', String], ['evidence', 'Bằng chứng mới', null, String],
  ['failures', 'Lượt agent hỏng', 'lower', String], ['denied', 'Lệnh bị chặn', 'lower', String], ['retries', 'Lần bị cổng bắt làm lại', 'lower', String],
];

function sentences(A, B) {
  const out = [], la = A.verdict?.label, lb = B.verdict?.label;
  if (la && lb) {
    if (la === lb && A.verdict.rule === B.verdict.rule) out.push({ tone: 'ok', t: `Cùng kết luận ${labelOf(la)[0]} theo quy tắc ${A.verdict.rule}.` });
    else if (la === lb) out.push({ tone: 'info', t: `Cùng nhãn ${labelOf(la)[0]} nhưng khác quy tắc: ${A.verdict.rule} so với ${B.verdict.rule}${ruleInfo(B.verdict.rule) ? ` (${ruleInfo(B.verdict.rule)[0].toLowerCase()})` : ''}.` });
    else out.push({ tone: 'bad', t: `KẾT LUẬN KHÁC NHAU: ${labelOf(la)[0]} (${A.verdict.rule}) so với ${labelOf(lb)[0]} (${B.verdict.rule}). Đây là chỗ cần xem kỹ nhất.` });
  } else out.push({ tone: 'warn', t: 'Một trong hai lần chạy chưa có kết luận.' });
  const dt = pct(A.m.tokens, B.m.tokens);
  if (dt != null && Math.abs(dt) >= 10) out.push({ tone: dt < 0 ? 'ok' : 'warn', t: `Lần B ${dt < 0 ? 'rẻ hơn' : 'tốn hơn'} ${Math.abs(dt)}% token (${fmt.tok(A.m.tokens)} → ${fmt.tok(B.m.tokens)}).` });
  if (A.m.rounds !== B.m.rounds) out.push({ tone: 'info', t: `Số vòng điều tra khác nhau: ${A.m.rounds} so với ${B.m.rounds}.` });
  if (A.m.failures !== B.m.failures) out.push({ tone: B.m.failures > A.m.failures ? 'warn' : 'ok', t: `Số lượt agent hỏng: ${A.m.failures} → ${B.m.failures}.` });
  const top = (X) => X.cards[0];
  if (top(A) && top(B) && top(A).role !== top(B).role) out.push({ tone: 'info', t: `Agent tiêu nhiều token nhất khác nhau: ${agentName(top(A).role)} so với ${agentName(top(B).role)}.` });
  const ta = A.tasks.map((x) => x.tasks.join('+')).join(' › '), tb = B.tasks.map((x) => x.tasks.join('+')).join(' › ');
  out.push({ tone: ta === tb ? 'ok' : 'info', t: ta === tb ? 'Trình tự nhiệm vụ giống hệt nhau.' : 'Trình tự nhiệm vụ khác nhau (xem bảng bên dưới).' });
  return out;
}

export default async function (ctx) {
  const [ida, idb] = ctx.args.map(decodeURIComponent);
  ctx.setCrumbs([{ text: 'Lần chạy', href: '#/runs' }, { text: 'So sánh' }]);
  mount(ctx.el, html`<div class="skeleton-stack"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let A, B;
  try { [A, B] = await Promise.all([load(ida), load(idb)]); } catch (e) { mount(ctx.el, html`<div class="banner bad">${icon('alert', 18)}<div><b>Không tải được lần chạy để so sánh.</b><div>${e.message}</div></div></div>`); return; }
  if (!ctx.alive()) return;
  const head = (X, tag) => html`<div class="cmp-run"><div class="small muted">Lần ${tag}</div><a class="mono cmp-id" href="#/runs/${X.id}">${X.id}</a>
    <div class="small muted">${X.detail.spec.adapter || '–'} · ${X.detail.spec.mode === 'demo' ? 'Demo mô phỏng' : X.detail.spec.mode} · ${fmt.time(X.detail.started_at || X.detail.created_at)}</div>
    <div style="margin-top:6px">${X.verdict ? verdict(X.verdict.label, X.verdict.rule) : html`<span class="muted">chưa có kết luận</span>`}</div></div>`;
  const metric = ([k, label, dir, f]) => {
    const a = A.m[k], b = B.m[k], d = a != null && b != null ? b - a : null, p = pct(a, b);
    const tone = dir && d ? (d < 0 ? 'good' : 'bad') : d ? 'info' : '';
    return html`<tr><td class="muted">${label}</td><td class="num">${f(a)}</td><td class="num">${f(b)}</td><td class="num ${tone}">${d ? html`${d > 0 ? '+' : '−'}${k === 'tokens' ? fmt.tok(Math.abs(d)) : k === 'seconds' ? fmt.sec(Math.abs(d)) : Math.abs(d)}${p != null && k !== 'rounds' ? html` <span class="muted small">(${p > 0 ? '+' : ''}${p}%)</span>` : ''}` : html`<span class="muted">=</span>`}</td></tr>`;
  };
  const roles = [...new Set([...A.cards, ...B.cards].map((c) => c.role))];
  const tok = (X, r) => X.cards.find((c) => c.role === r)?.tokens || 0;
  const max = Math.max(1, ...roles.flatMap((r) => [tok(A, r), tok(B, r)]));
  const bar = (v, cls) => html`<div class="cmp-bar ${cls}"><div class="cmp-track"><i style="width:${(v / max) * 100}%"></i></div><span>${fmt.tok(v)}</span></div>`;
  const maxRounds = Math.max(A.tasks.length, B.tasks.length);
  mount(ctx.el, html`
    ${pageHead('So sánh hai lần chạy', 'Cùng một mục đích: biết lần chạy nào tốt hơn, khác ở đâu, vì sao. Dùng để so trước và sau khi sửa lời nhắc, kỹ năng hay mô hình.', html`<a class="btn" id="swap" href="#/compare/${idb}/${ida}">${icon('refresh', 14)}Đổi chiều A ↔ B</a><a class="btn" href="#/runs">${icon('list', 14)}Chọn lần chạy khác</a>`)}
    <div class="cmp-heads">${head(A, 'A')}<div class="cmp-vs">so với</div>${head(B, 'B')}</div>
    <div class="section"><h4>Khác biệt chính</h4><ul class="cmp-notes">${sentences(A, B).map((s) => html`<li class="${s.tone}">${icon(s.tone === 'ok' ? 'check' : s.tone === 'bad' ? 'x' : s.tone === 'warn' ? 'alert' : 'info', 14)}<span>${s.t}</span></li>`)}</ul></div>
    <div class="grid g-2-1" style="align-items:start">
      <div class="section"><h4>Số liệu</h4><div class="table-wrap"><table class="tbl compact"><thead><tr><th></th><th class="num">Lần A</th><th class="num">Lần B</th><th class="num">B so với A</th></tr></thead><tbody>${ROWS.map(metric)}</tbody></table></div></div>
      <div class="section"><h4>Token theo agent</h4><div class="cmp-agents">${roles.map((r) => html`<div class="cmp-ag"><div class="small">${agentName(r)}</div>${bar(tok(A, r), 'a')}${bar(tok(B, r), 'b')}</div>`)}</div><div class="legend-line"><span><i style="background:var(--series-1)"></i>Lần A</span><span><i style="background:var(--series-5)"></i>Lần B</span></div></div>
    </div>
    <div class="section"><h4>Trình tự nhiệm vụ theo vòng</h4><div class="table-wrap"><table class="tbl compact"><thead><tr><th>Vòng</th><th>Lần A</th><th>Lần B</th></tr></thead><tbody>
      ${Array.from({ length: maxRounds }, (_, i) => { const a = A.tasks[i]?.tasks.join(' + ') || '–', b = B.tasks[i]?.tasks.join(' + ') || '–'; return html`<tr class="${a !== b ? 'row-bad' : ''}"><td>${i + 1}</td><td class="mono">${a}</td><td class="mono">${b}</td></tr>`; })}</tbody></table></div></div>`);
}
