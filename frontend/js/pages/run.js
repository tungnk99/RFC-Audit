/* Theo dõi một lần chạy: đồ thị agent trực tiếp, hội thoại Hub↔agent, dòng thời gian, tổng kết kết luận, bằng chứng, bản kê,
   và ngăn chi tiết "AI nhận gì · dùng gì · trả gì". Nguồn dữ liệu duy nhất là trace.db/evidence.db do lõi ghi. */
import { $, $$, api, copyBtn, empty, esc, fmt, html, icon, kv, labelOf, mount, on, openDrawer, raw, status, tabs, toast, verdict, modeName } from '../lib.js';
import { findingCard, summaryLine } from '../findings-view.js';
import { agentRate, flagMenu, reviewMeta, wireForm } from '../review.js';
import { app } from '../lib.js';
import { codeTab, newCodeState, scrollToLine } from '../code-view.js';
import { closeExplorer, openExplorer } from '../explorer.js';

const HUB = 'execution_loop';
const KIND_VN = {
  requirement_start: 'bắt đầu yêu cầu', round_start: 'vòng mới', sufficiency: 'đánh giá độ đủ', plan: 'quyết định kế hoạch', plan_context: 'bối cảnh kế hoạch',
  message: 'giao việc', role_run: 'agent xong', llm_run: 'lần gọi LLM', llm_failure: 'LLM lỗi', task_result: 'kết quả nhiệm vụ', critique_result: 'phản biện',
  stop: 'dừng', verdict: 'KẾT LUẬN', gate_reject: 'cổng từ chối', role_failure: 'agent hỏng', task_rejected: 'nhiệm vụ bị từ chối', stop_rejected: 'dừng bị từ chối',
  tool_call: 'gọi công cụ', tool_denied: 'công cụ bị chặn', output_retry: 'làm lại đầu ra', t3: 'kiểm thử T3', t3_case: 'ca kiểm thử', suspicious_scan: 'quét điểm đáng ngờ trong mã',
};
const NOISY = new Set(['tool_call', 't3_case', 't3', 'plan_context', 'round_start']);
const GW = 560, GH = 430;
const NODE_LABEL = { [HUB]: 'Hub', evidence: 'Kho bằng chứng', verdict: 'Verdict engine' };

export default async function (ctx) {
  const [id, openSeq, openTab, openReq] = ctx.args;
  const [detail, cat] = await Promise.all([api(`/api/runs/${id}`), api('/api/catalog').catch(() => ({ agents: [] }))]);
  if (!ctx.alive()) return;
  ctx.setCrumbs([{ text: 'Lần chạy', href: '#/runs' }, { text: id }]);
  const roleInfo = Object.fromEntries(cat.agents.map((a) => [a.name, a]));

  const S = { id, run: detail, status: detail.status, events: [], nodes: {}, req: {}, llmByMsg: {}, lastSeq: 0, evCount: 0, tab: 'chat', sel: null, follow: true, tl: { kind: '', role: '', q: '', noisy: false }, ev: null, evDirty: true, es: null, replaying: false, speed: 1, speedPref: 4, graphKey: null, pos: null, code: newCodeState(), reviews: [], rvStates: {}, rvErr: {}, meta: null, canReview: false };

  /* ---------- trạng thái suy ra từ sự kiện ---------- */
  const nodeOf = (role) => (S.nodes[role] ||= { id: role, runs: 0, tokens: 0, tools: 0, working: 0, errors: 0, det: !(roleInfo[role] && !roleInfo[role].deterministic) });
  const reqOf = (rid) => (rid ? (S.req[rid] ||= { id: rid, tokens: 0, tool_calls: 0, round: 0, provisional: null, missing: null, verdict: null, t3: {}, evidence: 0 }) : null);
  const seedNodes = () => { nodeOf(HUB).det = false; nodeOf('evidence').det = true; nodeOf('verdict').det = true; cat.agents.filter((a) => a.wired && !a.deterministic).forEach((a) => nodeOf(a.name)); };
  const resetDerived = () => { Object.assign(S, { nodes: {}, req: {}, llmByMsg: {}, lastSeq: 0, evCount: 0, graphKey: null }); seedNodes(); };

  function apply(e, animate) {
    const p = e.payload || {}, r = reqOf(e.requirement_id);
    S.lastSeq = Math.max(S.lastSeq, e.seq);
    switch (e.kind) {
      case 'requirement_start': Object.assign(r, { rtype: p.rtype, modal: p.modal, budget: p.budget, startTs: e.ts_ns }); break;
      case 'round_start': if (r) r.round = p.round; break;
      case 'message': { nodeOf(e.role).working++; if (r && p.round) r.round = Math.max(r.round, p.round); if (animate) pulse(HUB, e.role, 'var(--series-7)'); break; }
      case 'tool_call': { nodeOf(e.role).tools++; if (animate) flash(e.role); break; }
      case 'llm_run': case 'llm_failure': S.llmByMsg[p.msg_id] = e.seq; break;
      case 'role_run': { const n = nodeOf(p.role); n.working = Math.max(0, n.working - 1); n.runs++; n.tokens += p.tokens || 0; if (!p.ok) n.errors++; if (r) { r.tokens += p.tokens || 0; r.tool_calls += p.tool_calls || 0; } if (animate) pulse(p.role, HUB, p.ok ? 'var(--good)' : 'var(--critical)'); break; }
      case 'task_result': if (r) r.evidence += p.new_evidence || 0; S.evCount += p.new_evidence || 0; S.evDirty = true; if (animate && p.new_evidence) pulse(HUB, 'evidence', 'var(--series-3)'); break;
      case 'sufficiency': if (r) { r.provisional = p.provisional; r.missing = (p.missing || []).length; } if (animate) pulse(HUB, 'verdict', 'var(--warning)'); break;
      case 't3': if (r) r.t3[p.outcome] = (r.t3[p.outcome] || 0) + 1; break;
      case 'stop': if (r) r.stop = p; break;
      case 'verdict': if (r) r.verdict = p; S.findingsDirty = true; S.code.files = null; S.code.data = null; if (animate) pulse('verdict', HUB, p.label === 'COMPLIANT' ? 'var(--good)' : 'var(--critical)'); break;
    }
  }

  /* ---------- đồ thị ---------- */
  function layout() {
    const roles = Object.keys(S.nodes).filter((r) => ![HUB, 'evidence', 'verdict'].includes(r));
    const llm = roles.filter((r) => !S.nodes[r].det).sort(), det = roles.filter((r) => S.nodes[r].det).sort();
    const pos = { [HUB]: [GW / 2, 215], evidence: [95, 375], verdict: [GW - 95, 375] };
    const place = (list, rx, ry) => list.forEach((r, i) => { const a = Math.PI + (Math.PI * (i + 0.5)) / list.length; pos[r] = [GW / 2 + rx * Math.cos(a), 215 + ry * Math.sin(a)]; });
    place(llm, 215, 150); place(det, 130, 85); return pos;
  }
  function graphSvg() {
    const pos = (S.pos = layout()); const ids = Object.keys(pos);
    return raw(`<svg class="graph" viewBox="0 0 ${GW} ${GH}" role="img" aria-label="Mạng agent">${ids.filter((i) => i !== HUB).map((i) => `<line class="edge" x1="${pos[HUB][0]}" y1="${pos[HUB][1]}" x2="${pos[i][0]}" y2="${pos[i][1]}"/>`).join('')}<g>${ids.map((nid) => {
      const [x, y] = pos[nid]; const cls = nid === HUB ? 'hub' : nid === 'evidence' ? 'sink' : nid === 'verdict' ? 'verdict' : '';
      const shape = nid === HUB ? `<rect class="body" x="${x - 40}" y="${y - 29}" width="80" height="58" rx="14"/>` : cls ? `<rect class="body" x="${x - 52}" y="${y - 25}" width="104" height="50" rx="10"/>` : `<rect class="body" x="${x - 58}" y="${y - 26}" width="116" height="52" rx="26"/>`;
      return `<g class="node ${cls}" data-node="${esc(nid)}" tabindex="0" role="button" aria-label="${esc(NODE_LABEL[nid] || nid)}">${shape}<text x="${x}" y="${y - 2}">${esc(NODE_LABEL[nid] || nid)}</text><text class="sub" x="${x}" y="${y + 12}" data-sub="${esc(nid)}"></text></g>`;
    }).join('')}</g><g id="pulses"></g></svg>`);
  }
  function updateGraph() {
    const box = $('#graph-box', ctx.el); if (!box) return;
    const key = Object.keys(S.nodes).join('|');
    if (S.graphKey !== key) { S.graphKey = key; mount(box, graphSvg()); }
    $$('[data-node]', box).forEach((g) => {
      const nid = g.dataset.node, n = S.nodes[nid]; if (!n) return;
      g.classList.toggle('working', n.working > 0); g.classList.toggle('error', n.errors > 0 && n.working === 0); g.classList.toggle('sel', S.sel === nid); g.classList.toggle('det', !!n.det && !['evidence', 'verdict'].includes(nid));
      const sub = $('[data-sub]', g); sub.textContent = nid === 'evidence' ? S.evCount + ' mục' : nid === 'verdict' ? '' : nid === HUB ? 'điều phối' : n.working > 0 ? 'đang chạy…' : `${n.runs}× · ${fmt.tok(n.tokens)}`;
    });
  }
  function pulse(from, to, color) {
    const layer = $('#pulses', ctx.el); if (!layer || !S.pos?.[from] || !S.pos?.[to]) return;
    const [x1, y1] = S.pos[from], [x2, y2] = S.pos[to];
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); c.setAttribute('r', 6); c.setAttribute('fill', color); layer.appendChild(c);
    const t0 = performance.now(), dur = 650 / (S.speed || 1);
    const step = (t) => { const k = Math.min(1, (t - t0) / dur); c.setAttribute('cx', x1 + (x2 - x1) * k); c.setAttribute('cy', y1 + (y2 - y1) * k); if (k < 1) requestAnimationFrame(step); else c.remove(); };
    requestAnimationFrame(step);
  }
  const flash = (role) => { const el = $(`[data-node="${CSS.escape(role)}"] .body`, ctx.el); el?.animate([{ strokeWidth: 7 }, { strokeWidth: 2 }], 350); };

  /* ---------- hội thoại ---------- */
  function buildFeed(events) {
    const feed = [], byMsg = {}, open = {};
    const shown = (e) => !S.sel || e.role === S.sel || e.kind === 'verdict' || e.kind === 'stop';
    for (const e of events) {
      const p = e.payload || {};
      switch (e.kind) {
        case 'message': { if (!shown(e)) break; const x = { type: 'dispatch', e, to: e.role, tools: [], done: null, llm: null, result: null }; byMsg[p.msg_id] = x; (open[e.role] ||= []).push(x); feed.push(x); break; }
        case 'tool_call': { const q = open[e.role]; if (q?.length) q[q.length - 1].tools.push(e); break; }
        case 'llm_run': case 'llm_failure': if (byMsg[p.msg_id]) byMsg[p.msg_id].llm = e; break;
        case 'role_run': if (byMsg[p.msg_id]) { byMsg[p.msg_id].done = e; const q = open[p.role] || []; const i = q.indexOf(byMsg[p.msg_id]); if (i >= 0) q.splice(i, 1); } break;
        case 'task_result': if (byMsg[p.msg_id]) byMsg[p.msg_id].result = e; break;
        case 'round_start': case 'plan_context': case 't3': case 't3_case': break;
        case 'tool_denied': { const q = open[e.role]; if (q?.length) q[q.length - 1].tools.push(e); else if (shown(e)) feed.push({ type: 'note', e }); break; }
        default: if (shown(e)) feed.push({ type: 'note', e });
      }
    }
    return feed;
  }
  const taskOf = (e) => e.payload.body && (e.payload.body.task_type || e.payload.body.task?.task_type) || '';
  const briefBody = (b) => { const c = { ...(b || {}) }; delete c.task_type; const s = JSON.stringify(c); return s === '{}' ? '' : s.length > 200 ? s.slice(0, 200) + '…' : s; };
  /* Tham số giao việc: vài chip tóm tắt, JSON đầy đủ gập lại (không phơi cả khối thô giữa hội thoại). */
  const paramsView = (b) => {
    const c = { ...(b || {}) }; delete c.task_type; if (!Object.keys(c).length) return '';
    const pr = c.params || {}, chips = [];
    if (pr.aspects?.length) chips.push(html`<span class="chip">khía cạnh: ${pr.aspects.join(', ')}</span>`);
    if (pr.missing_variants?.length) chips.push(html`<span class="chip">${pr.missing_variants.length} biến thể cần chạy</span>`);
    if (c.evidence_count != null) chips.push(html`<span class="chip">${c.evidence_count} bằng chứng hiện có</span>`);
    return html`<div class="row" style="gap:4px;margin:4px 0">${chips}<details class="params"><summary>${icon('chevron', 11)}tham số</summary><pre class="code">${JSON.stringify(c, null, 1)}</pre></details></div>`;
  };
  const toolChips = (tools) => { const m = {}; tools.filter((t) => t.kind === 'tool_call').forEach((t) => { m[t.payload.tool] = (m[t.payload.tool] || 0) + 1; }); return Object.entries(m).map(([t, n]) => html`<span class="chip accent mono">${t}${n > 1 ? ' ×' + n : ''}</span>`); };

  function feedItem(it) {
    const e = it.e, p = e.payload || {}, rid = e.requirement_id ? html`<span class="chip">${e.requirement_id}</span>` : '';
    const link = html`<a href="#" class="small" data-seq="${e.seq}">chi tiết</a>`;
    if (it.type === 'dispatch') {
      const d = it.done, dp = d?.payload, denied = it.tools.filter((t) => t.kind === 'tool_denied').length;
      const reply = d ? html`<div class="reply ${dp.ok ? '' : 'fail'}"><div class="row">${dp.ok ? icon('check', 15) : icon('x', 15)}<b>${it.to}</b> trả ${dp.ok ? html`<span class="chip">${dp.schema || 'xong'}</span>` : html`<span class="chip bad">HỎNG ${dp.failure}</span>`}
          <span class="muted small">${fmt.ms(dp.duration_ms)} · ${fmt.tok(dp.tokens)} token · ${dp.tool_calls} công cụ${dp.output_retries ? ` · làm lại ${dp.output_retries}` : ''}</span></div>
          <div>${toolChips(it.tools)}${denied ? html`<span class="chip bad">${denied} lần bị chặn</span>` : ''}</div>
          ${it.llm ? html`<div style="margin-top:8px"><button class="btn sm" data-seq="${it.llm.seq}">${icon('eye', 14)}Xem AI nhận gì · dùng gì · trả gì</button></div>` : html`<div class="muted small">Không có bản ghi gọi LLM (agent tất định)</div>`}
          ${it.result ? html`<div class="small" style="margin-top:6px">${icon('chevron', 12)} Hub nhận: ${it.result.summary}</div>` : ''}
          ${e.requirement_id && S.findings?.some((f) => f.requirement_id === e.requirement_id) ? html`<div style="margin-top:8px">${agentRate(S.id, e.requirement_id, it.to, p.msg_id, canReview())}</div>` : ''}</div>`
        : html`<div class="reply"><span class="spin"></span>${it.to} đang làm việc… ${toolChips(it.tools)}</div>`;
      return html`<div class="msg dispatch"><div><span class="who" style="color:var(--series-7)">Hub</span><span class="arrow">→</span><span class="who">${it.to}</span> <span class="chip accent">${taskOf(e) || 'giao việc'}</span> ${rid} <span class="meta">vòng ${p.round ?? '–'} · ${link}</span></div>
        ${paramsView(p.body)}${reply}</div>`;
    }
    switch (e.kind) {
      case 'plan': return html`<div class="msg sys"><b>Planner quyết định</b> ${rid} <span class="chip">${p.action}</span> ${(p.tasks || []).map((t) => html`<span class="chip accent">${t.task_type} → ${t.target_role}</span>`)}<div class="meta">lý do: ${p.rationale_code} · ${link}</div></div>`;
      case 'sufficiency': { const pr = p.provisional; return html`<div class="msg sys"><b>Verdict engine đánh giá độ đủ</b> ${rid} ${pr ? verdict(pr.label, pr.rule) : html`<span class="chip">chưa có nhãn tạm</span>`} <span class="meta">thiếu ${(p.missing || []).length} · mâu thuẫn ${(p.conflicts || []).length} · ${link}</span></div>`; }
      case 'critique_result': return html`<div class="msg ${p.clean ? 'sys' : 'warn'}"><b>Phản biện (Verifier)</b> ${rid} ${p.clean ? html`<span class="badge ok">${icon('check', 12)}sạch</span>` : (p.issues || []).map((i) => html`<span class="badge warn">${i.kind}</span>`)} ${link}</div>`;
      case 'stop': return html`<div class="msg sys"><b>Hub dừng</b> ${rid} <span class="chip">${p.reason}</span> <span class="meta">${p.used ? `${p.used.rounds} vòng · ${fmt.tok(p.used.tokens)} token · ${p.used.tool_calls} công cụ · ${p.used.seconds}s` : ''}</span></div>`;
      case 'verdict': { const bad = p.label === 'VIOLATION'; return html`<div class="msg final ${bad ? 'bad' : ''}"><b>KẾT LUẬN</b> ${rid} ${verdict(p.label, p.rule)} <span class="meta">bảo đảm ${p.assurance} · ${(p.evidence_ids || []).length} bằng chứng · ${link}</span></div>`; }
      case 'requirement_start': return html`<div class="msg sys"><b>Bắt đầu điều tra</b> ${rid} <span class="chip">${p.modal} · loại ${p.rtype}</span> <span class="meta">ngân sách ${p.budget.rounds} vòng · ${fmt.tok(p.budget.tokens)} token · ${p.budget.tool_calls} công cụ</span></div>`;
      default: return html`<div class="msg ${['gate_reject', 'role_failure', 'task_rejected', 'stop_rejected', 'llm_failure'].includes(e.kind) ? 'bad' : 'warn'}"><b>${KIND_VN[e.kind] || e.kind}</b> ${e.role || ''} ${rid} <span class="meta">${e.summary || JSON.stringify(Object.fromEntries(Object.entries(p).filter(([k]) => k !== `round`)))} · ${link}</span></div>`;
    }
  }

  /* ---------- các tab ---------- */
  const kindTone = (k) => (k === 'verdict' ? 'final' : /fail|reject|denied/.test(k) ? 'bad' : k === 'message' || k === 'plan' ? 'dispatch' : k === 'tool_call' ? 'tool' : k === 'sufficiency' || k === 'critique_result' || k === 'stop' ? 'sys' : '');
  /* Mô tả một dòng bằng tiếng người cho từng loại sự kiện (thay cho chuỗi dict của máy chủ). */
  const plainSummary = (e) => {
    const p = e.payload || {}, L = (a) => (a || []).length;
    switch (e.kind) {
      case 'requirement_start': return `loại ${p.rtype} · ${p.modal} · ngân sách ${p.budget?.rounds} vòng, ${fmt.tok(p.budget?.tokens)} token, ${p.budget?.tool_calls} công cụ`;
      case 'sufficiency': return `${p.provisional ? `nhãn tạm ${labelOf(p.provisional.label)[0]} (${p.provisional.rule})` : 'chưa có nhãn tạm'} · còn thiếu ${L(p.missing)} · mâu thuẫn ${L(p.conflicts)}`;
      case 'plan': return `${p.action === 'stop' ? 'dừng' : 'giao'}: ${(p.tasks || []).map((t) => `${t.task_type} → ${t.target_role}`).join(', ') || '–'} (${p.rationale_code})`;
      case 'message': return `giao ${taskOf(e) || 'việc'} cho ${p.to_role}`;
      case 'role_run': return `${p.role} ${p.ok ? 'xong' : 'HỎNG ' + p.failure} · ${fmt.ms(p.duration_ms)} · ${fmt.tok(p.tokens)} token · ${p.tool_calls} công cụ${p.schema ? ' · ra ' + p.schema : ''}`;
      case 'llm_run': return `${p.model} · ${fmt.ms(p.duration_ms)} · vào ${fmt.tok(p.input_tokens)} ra ${fmt.tok(p.output_tokens)}${L(p.skills_loaded) ? ' · skill đã nạp: ' + p.skills_loaded.join(', ') : ''}`;
      case 'task_result': return `${p.task_type} → ${p.new_evidence} bằng chứng mới`;
      case 'critique_result': return p.clean ? 'phản biện sạch, không nêu vấn đề' : `nêu ${L(p.issues)} vấn đề: ${(p.issues || []).map((i) => i.kind).join(', ')}`;
      case 'stop': return `${p.reason} · ${p.used?.rounds ?? '–'} vòng · ${fmt.tok(p.used?.tokens)} token · ${p.used?.tool_calls ?? '–'} công cụ`;
      case 'verdict': return `${labelOf(p.label)[0]} theo quy tắc ${p.rule} · bảo đảm ${p.assurance} · ${L(p.evidence_ids)} bằng chứng`;
      case 'tool_call': return `${p.tool} ${JSON.stringify(p.args || {}).slice(0, 90)}`;
      case 'tool_denied': return `${p.tool}: ${p.code}`;
      case 't3': return `${p.variant}: ${p.outcome}`;
      case 'suspicious_scan': return `đã quét ${p.symbols} ký hiệu, ${p.findings} điểm đáng ngờ, ${p.new} bằng chứng mới`;
      default: return String(e.summary || '').replace(/^giao - /, 'giao việc ');
    }
  };
  /* Tóm tắt một bản ghi bằng chứng cho sổ cái: đọc được ngay, không phải JSON cắt cụt. */
  const evSummary = (x) => {
    const b = x.brief || {};
    if (x.kind === 'scenario_result') { const o = b.observed; return html`<span class="ev-sum"><b>${b.variant || '–'}</b> → ${b.outcome || '–'}${o ? html` · <span class="mono">${o.alert && o.alert !== 'none' ? 'cảnh báo ' + o.alert : 'không cảnh báo'}${o.closed ? ', đóng kết nối' : ''}</span>` : ''}</span>`; }
    if (x.kind === 'coverage_link') return html`<span class="ev-sum">${b.linked ? 'liên kết độ phủ' : 'chưa liên kết'} · dòng <span class="mono">${(b.lines_hit || []).join(', ') || '–'}</span></span>`;
    if (x.kind === 'location') return html`<span class="ev-sum"><span class="mono">${b.file}:${b.line_start}–${b.line_end}</span>${b.symbol ? html` · <b>${b.symbol}</b>` : ''}${b.finding ? ` · ${b.finding}` : ''}</span>`;
    return html`<span class="ev-sum mono">${Object.entries(b).slice(0, 4).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}</span>`;
  };
  const tabChat = () => { const feed = buildFeed(S.events); return html`<div class="row small muted" style="margin-bottom:10px">${S.sel ? html`<span class="chip accent">lọc: ${S.sel} <a href="#" data-clear>✕</a></span>` : 'Bấm một nút trên đồ thị để lọc theo agent.'}</div><div class="feed" id="feed">${feed.length ? feed.map(feedItem) : empty('Chưa có hoạt động', 'Lần chạy chưa phát sinh sự kiện nào.')}</div>`; };
  const tabTimeline = () => {
    const f = S.tl, kinds = [...new Set(S.events.map((e) => e.kind))].sort(), roles = [...new Set(S.events.map((e) => e.role).filter(Boolean))].sort();
    const rows = S.events.filter((e) => (f.noisy || !NOISY.has(e.kind)) && (!f.kind || e.kind === f.kind) && (!f.role || e.role === f.role) && (!f.q || `${e.kind} ${e.role || ''} ${e.summary}`.toLowerCase().includes(f.q.toLowerCase())));
    const t0 = S.events[0]?.ts_ns || 0;
    return html`<div class="tl-bar"><select id="tl-kind" aria-label="Loại sự kiện"><option value="">Mọi loại</option>${kinds.map((k) => html`<option value="${k}" ${f.kind === k ? 'selected' : ''}>${KIND_VN[k] || k}</option>`)}</select>
      <select id="tl-role" aria-label="Agent"><option value="">Mọi agent</option>${roles.map((k) => html`<option value="${k}" ${f.role === k ? 'selected' : ''}>${k === HUB ? 'Hub' : k}</option>`)}</select>
      <input type="search" id="tl-q" class="grow" placeholder="Tìm trong dòng thời gian…" value="${f.q}" aria-label="Tìm sự kiện"><label><input type="checkbox" id="tl-noisy" ${f.noisy ? 'checked' : ''}>Gồm công cụ & ca kiểm thử</label>
      <span class="muted small nowrap">${rows.length}/${S.events.length} · <a href="/api/runs/${S.id}/export?full=true" download>tải trace đầy đủ</a></span></div>
      <div class="table-wrap feed"><table class="tbl tl"><thead><tr><th style="width:56px">#</th><th style="width:70px">Lúc</th><th style="width:130px">Ai</th><th style="width:170px">Việc gì</th><th>Chi tiết</th></tr></thead><tbody>${rows.slice(-1500).map((e) => html`<tr class="click" data-seq="${e.seq}"><td class="t">${e.seq}</td><td class="t">+${((e.ts_ns - t0) / 1e9).toFixed(1)}s</td><td>${e.role ? html`<span class="chip ${e.role === HUB ? '' : 'accent'}">${e.role === HUB ? 'Hub' : e.role}</span>` : html`<span class="muted">hệ thống</span>`}</td>
        <td class="k"><span class="kd ${kindTone(e.kind)}"></span>${KIND_VN[e.kind] || e.kind}<div class="raw">${e.kind}</div></td><td><div class="clamp sum" title="${plainSummary(e)}">${plainSummary(e) || html`<span class="muted">–</span>`}</div></td></tr>`)}</tbody></table></div>`;
  };
  /* Một tab Bằng chứng, hai cách xem: gắn vào dòng mã (bằng chứng có vị trí) hoặc sổ cái đầy đủ (mọi bản ghi, kể cả kết quả kiểm thử). */
  async function tabEvidence() {
    if (S.evView == null) { if (!S.findings) await loadFindings(); S.evView = S.findings?.some((f) => f.location) ? 'code' : 'list'; }
    const toggle = html`<div class="row" style="margin-bottom:12px"><div class="seg mini" role="group" aria-label="Cách xem bằng chứng"><button data-evview="code" class="${S.evView === 'code' ? 'on' : ''}">Trên mã nguồn</button><button data-evview="list" class="${S.evView === 'list' ? 'on' : ''}">Sổ cái đầy đủ${S.evCount ? ` (${S.evCount})` : ''}</button></div>
      <span class="muted small">${S.evView === 'code' ? 'Bằng chứng có vị trí, gắn vào đúng dòng mã.' : 'Mọi bản ghi trong kho, kể cả kết quả kiểm thử không gắn dòng mã.'}</span></div>`;
    return html`${toggle}${S.evView === 'code' ? await codeTab(S) : await evidenceList()}`;
  }
  async function evidenceList() {
    if (S.evDirty || !S.ev) { S.evDirty = false; S.ev = (await api(`/api/runs/${S.id}/evidence`)).evidence; }
    const POL = { SUPPORTS: 'ok', REFUTES: 'bad' };
    return html`<div class="muted small" style="margin-bottom:8px">${S.ev.length} bằng chứng. Kho chỉ ghi thêm, nối bằng chuỗi hash; chỉ thành phần tất định được ghi, agent chỉ đề xuất.</div>
      <div class="table-wrap feed"><table class="tbl compact"><thead><tr><th>#</th><th>Tầng</th><th>Loại</th><th>Cực</th><th>Do</th><th>Nội dung</th></tr></thead><tbody>${S.ev.map((x) => html`<tr class="click" data-ev="${x.evidence_id}"><td>${x.seq}</td><td><span class="chip accent">${x.tier}</span></td><td>${x.kind}</td><td><span class="badge ${POL[x.polarity] || ''}">${x.polarity}</span></td><td class="small">${x.produced_by}</td><td>${evSummary(x)}</td></tr>`)}</tbody></table></div>`;
  }
  async function loadReviews() { try { const r = await api(`/api/runs/${S.id}/reviews`); S.reviews = r.reviews; S.rvStates = r.states; } catch { S.reviews = []; S.rvStates = {}; } }
  const canReview = () => !live() && !app.readOnly;
  async function loadFindings() { try { S.findings = (await api(`/api/runs/${S.id}/findings`)).findings; } catch { S.findings = []; } }
  async function tabSummary() {
    if (!S.findings || S.findingsDirty) { S.findingsDirty = false; await loadFindings(); }
    const reqs = Object.values(S.req);
    if (!reqs.length) return empty('Chưa có yêu cầu nào bắt đầu');
    const byId = Object.fromEntries(S.findings.map((f) => [f.requirement_id, f]));
    return html`${reqs.map((r) => byId[r.id] ? findingCard(byId[r.id], { run: S.id, reviews: S.reviews || [], meta: S.meta, canReview: canReview(), error: S.rvErr[r.id] }) : html`<section class="req-card"><div class="row"><h3 class="mono" style="font-size:15px">${r.id}</h3><span class="chip">${r.modal || ''} · loại ${r.rtype || ''}</span><span class="badge info pulse">${icon('activity', 12)}đang điều tra</span></div>
        ${kv([['Nhãn tạm', r.provisional ? verdict(r.provisional.label, r.provisional.rule) : 'chưa có'], ['Còn thiếu', r.missing ?? '–'], ['Tiến độ', `${r.round} vòng · ${fmt.tok(r.tokens)} token · ${r.evidence} bằng chứng`]])}
        <div class="muted small">Phân tích vi phạm sẽ hiện ngay khi Verdict engine kết luận.</div></section>`)}
      <div class="banner info" style="margin-top:6px">${icon('info', 16)}<div>Nhãn do Verdict engine gán bằng bộ quy tắc cố định, có phiên bản là hash nội dung. Agent chỉ đề xuất; một đề xuất chỉ thành bằng chứng sau khi qua cổng kiểm chứng không dùng LLM.</div></div>`;
  }
  const tabManifest = () => {
    const m = S.run.manifest, sp = S.run.spec;
    return html`<div class="section"><h4>Cấu hình</h4>${kv([['Giao thức', sp.adapter], ['Chế độ', modeName(sp.mode)], ['Yêu cầu', (sp.requirements || []).join(', ') || 'tất cả'], ['Mã nguồn', sp.code_root || (sp.mode === 'demo' ? 'mô phỏng' : '–')], ['Chỉ mục / sandbox / SUT', [sp.code_index, sp.executor, sp.sut_launcher].filter(Boolean).join(' · ') || '–'], ['Ngân sách', Object.keys(sp.budget || {}).length ? JSON.stringify(sp.budget) : 'mặc định'], ['Tạo lúc', fmt.time(S.run.created_at)], ['Thời lượng', fmt.dur(S.run.started_at, S.run.ended_at)]])}</div>
      ${S.run.leak_scan ? html`<div class="banner ${S.run.leak_scan.clean ? 'ok' : 'bad'}">${icon(S.run.leak_scan.clean ? 'check' : 'alert', 16)}<div>Quét rò rỉ khoá API / tệp ngoài phạm vi: ${S.run.leak_scan.clean ? 'sạch' : `${S.run.leak_scan.count} dấu vết, xem leak_scan.json`}</div></div>` : ''}
      <div class="section"><h4>Bản kê: hash mọi đầu vào ảnh hưởng kết luận</h4>${m ? html`<div class="table-wrap"><table class="tbl compact"><tbody>${Object.entries(m.digests || {}).map(([k, v]) => html`<tr><td>${k}</td><td class="mono small muted">${v}</td><td>${copyBtn(v)}</td></tr>`)}</tbody></table></div>` : html`<div class="muted">chưa có</div>`}</div>
      <div class="section"><h4>Toàn vẹn Evidence store</h4><button class="btn" id="verify">${icon('shield', 15)}Kiểm tra chuỗi hash</button> <span id="verify-out" class="small"></span></div>`;
  };

  /* ---------- khung trang ---------- */
  const live = () => (S.status === 'queued' || S.status === 'running') && !S.replaying;
  const totalBudget = () => Object.values(S.req).reduce((a, r) => a + (r.budget?.tokens || 0), 0);
  const tokensUsed = () => Object.values(S.req).reduce((a, r) => a + r.tokens, 0);
  const elapsed = () => { const start = S.run.started_at; if (!start) { const ev = S.events; return ev.length > 1 ? (ev[ev.length - 1].ts_ns - ev[0].ts_ns) / 1e9 : null; } const end = live() || !S.run.ended_at ? Date.now() / 1000 : S.run.ended_at; return end - start; };

  function frame() {
    mount(ctx.el, html`
      <header class="page-head" id="head"></header><div id="err"></div><div id="quick"></div>
      <div class="run-top" id="top"></div>
      <div class="run-layout"><div>
        <section class="card graph-card"><div class="card-head"><div><h3>Mạng agent</h3><p class="sub">Nét đứt = thành phần tất định. Bấm một nút để lọc hội thoại.</p></div></div><div id="graph-box"></div>
          <div class="legend-line"><span><i style="background:var(--series-7)"></i>Hub giao việc</span><span><i style="background:var(--good)"></i>agent trả kết quả</span><span><i style="background:var(--series-3)"></i>ghi bằng chứng</span><span><i style="background:var(--warning)"></i>đánh giá độ đủ</span></div></section>
        <section class="card"><div class="card-head"><h3>Yêu cầu</h3></div><div id="reqs"></div></section></div>
      <section class="card"><div id="tabs"></div><div id="tab-body"></div></section></div>`);
  }
  function drawHead() {
    const r = S.run, isLive = live();
    mount($('#head', ctx.el), html`<div><h1 class="mono" style="font-size:20px">${r.run_id} ${copyBtn(r.run_id)}</h1><p class="sub row" style="gap:8px">${status(S.status)}<span>${r.spec.adapter || '–'} · ${modeName(r.spec.mode)}</span>${Object.values(S.req).filter((x) => x.verdict).map((x) => html`<span>${verdict(x.verdict.label, x.verdict.rule)}</span>`)}</p></div>
      <div class="actions">${isLive ? html`<button class="btn danger" id="cancel-run">${icon('stop', 14)}Huỷ</button>` : S.replaying ? html`<button class="btn" id="replay">${icon('stop', 14)}Dừng phát lại</button>` : html`<button class="btn" id="replay">${icon('play', 14)}Phát lại</button><select id="speed" aria-label="Tốc độ">${[1, 4, 16].map((s) => html`<option value="${s}" ${s === S.speedPref ? 'selected' : ''}>${s}×</option>`)}</select>`}
        ${r.spec.mode === 'demo' || r.spec.mode === 'real' ? html`<button class="btn" id="rerun">${icon('refresh', 14)}Chạy lại</button>` : ''}<a class="btn" href="/api/runs/${S.id}/export" download>${icon('download', 14)}Xuất JSON</a></div>`);
    mount($('#err', ctx.el), r.error ? html`<div class="banner bad">${icon('alert', 18)}<div><b>Lần chạy ${S.status === 'failed' ? 'bị lỗi' : S.status}.</b><div class="mono small">${r.error}</div></div></div>` : '');
  }
  function drawTop() {
    const tb = totalBudget(), tu = tokensUsed(), el = elapsed(), rounds = Object.values(S.req).reduce((a, r) => a + r.round, 0), tools = Object.values(S.nodes).reduce((a, n) => a + n.tools, 0);
    const stat = (l, v, extra = '') => html`<div class="stat"><div class="l">${l}</div><div class="v">${v}</div>${extra}</div>`;
    mount($('#top', ctx.el), html`${stat('Trạng thái', status(S.status))}${stat('Thời gian', el == null ? '–' : fmt.sec(el))}${stat('Vòng điều tra', rounds || '–')}
      ${stat('Token', fmt.tok(tu), tb ? html`<div class="bar"><i style="width:${Math.min(100, (tu / tb) * 100)}%"></i></div><div class="muted small">trên ngân sách ${fmt.tok(tb)}</div>` : '')}${stat('Bằng chứng · công cụ', html`${S.evCount} · ${tools}`)}`);
  }
  function drawReqs() {
    mount($('#reqs', ctx.el), Object.values(S.req).length ? html`${Object.values(S.req).map((r) => { const b = r.budget || {}; return html`<div class="req-card"><div class="row"><b class="mono">${r.id}</b><span class="chip">${r.modal || ''} · ${r.rtype || ''}</span>${r.verdict ? verdict(r.verdict.label, r.verdict.rule) : r.provisional ? html`<span class="muted small">tạm:</span>${verdict(r.provisional.label, r.provisional.rule)}` : html`<span class="badge info pulse">${icon('activity', 12)}đang điều tra</span>`}</div>
      <div class="muted small" style="margin:6px 0 4px">vòng ${r.round}${b.rounds ? '/' + b.rounds : ''} · ${r.evidence} bằng chứng${r.missing != null && !r.verdict ? ` · còn thiếu ${r.missing}` : ''} · ${fmt.tok(r.tokens)} token</div>
      <div class="bar"><i style="width:${b.tokens ? Math.min(100, (r.tokens / b.tokens) * 100) : 0}%"></i></div>
      ${Object.keys(r.t3).length ? html`<div style="margin-top:6px">${Object.entries(r.t3).map(([k, n]) => html`<span class="badge ${k === 'PASS' ? 'ok' : k === 'FAIL' ? 'bad' : 'warn'}">${k} ${n}</span>`)}</div>` : ''}</div>`; })}` : html`<div class="muted small">Chưa có yêu cầu nào bắt đầu.</div>`);
  }
  let raf = false;
  const render = () => { if (raf) return; raf = true; requestAnimationFrame(() => { raf = false; if (ctx.alive()) draw(); }); };
  async function draw() {
    if (!$('#graph-box', ctx.el)) return;
    S.canReview = canReview();
    if (Object.values(S.req).some((r) => r.verdict) && (!S.findings || S.findingsDirty)) { S.findingsDirty = false; await loadFindings(); }
    updateGraph(); drawHead(); drawTop(); drawReqs();
    mount($('#quick', ctx.el), S.findings?.length ? html`<div class="quicks">${S.findings.map((f) => summaryLine(f, S.rvStates?.[f.requirement_id] || 'pending'))}</div>` : '');
    mount($('#tabs', ctx.el), tabs([['chat', 'Hội thoại'], ['summary', 'Kết luận'], ['timeline', 'Dòng thời gian'], ['evidence', 'Bằng chứng', S.evCount || null], ['manifest', 'Bản kê & cấu hình']], S.tab));
    const body = $('#tab-body', ctx.el), sc = $('.feed', body), atBottom = !sc || sc.scrollHeight - sc.scrollTop - sc.clientHeight < 40, top = sc ? sc.scrollTop : 0;
    const out = S.tab === 'chat' ? tabChat() : S.tab === 'timeline' ? tabTimeline() : S.tab === 'evidence' ? await tabEvidence() : S.tab === 'summary' ? await tabSummary() : tabManifest();
    if (!ctx.alive()) return; mount(body, out);
    const sc2 = $('.feed', body); if (sc2) { sc2.scrollTop = atBottom && S.follow ? sc2.scrollHeight : top; sc2.onscroll = () => { S.follow = sc2.scrollHeight - sc2.scrollTop - sc2.clientHeight < 40; }; }
  }

  /* ---------- ngăn chi tiết ---------- */
  const pretty = (t) => { try { return JSON.stringify(JSON.parse(t), null, 1); } catch { return t; } };
  function transcriptView(ev) {
    const t = ev.transcript, p = ev.payload; const sys = t.steps.filter((s) => s.type === 'system' || s.type === 'instructions'), inputs = t.steps.filter((s) => s.type === 'input');
    const rets = Object.fromEntries(t.steps.filter((s) => s.type === 'tool_return').map((s) => [s.call_id, s])); const flow = [];
    t.steps.forEach((s) => { if (s.type === 'tool_call' && String(s.tool).startsWith('final_result')) return; if (s.type === 'tool_call') flow.push({ call: s, ret: rets[s.call_id] }); else if (['assistant', 'retry', 'thinking'].includes(s.type)) flow.push({ s }); });
    const cut = (s) => (s.truncated ? html`<div class="muted small">(đã cắt bớt, toàn văn trong trace.db)</div>` : '');
    return html`<div class="section row">${p.model ? html`<span class="chip">mô hình ${p.model}</span>` : ''}<span class="chip">${fmt.ms(p.duration_ms)}</span>${p.input_tokens != null ? html`<span class="chip">vào ${fmt.tok(p.input_tokens)} · ra ${fmt.tok(p.output_tokens)} token</span>` : ''}${p.requests ? html`<span class="chip">${p.requests} lượt gọi</span>` : ''}${ev.kind === 'llm_failure' ? html`<span class="badge bad">${p.error}: ${p.detail}</span>` : ''}</div>
      <div class="section"><h4>Skill</h4>${(p.skills_offered || []).length ? html`<div>Được đưa: ${p.skills_offered.map((s) => html`<span class="chip">${s}</span>`)}</div><div>Đã nạp: ${(p.skills_loaded || []).map((s) => html`<span class="badge ok">${s}</span>`)}${(p.skills_loaded || []).length ? '' : html`<span class="muted">không nạp skill nào</span>`}</div>` : html`<span class="muted">agent này không có skill</span>`}</div>
      <div class="section"><h4>① AI nhận được gì (đầu vào nhiệm vụ)</h4>${inputs.map((s) => html`<pre class="code">${pretty(s.text)}</pre>${cut(s)}`)}
        <details style="margin-top:10px"><summary class="muted" style="cursor:pointer">Lời nhắc hệ thống / vai trò (${sys.length} khối)</summary>${sys.map((s) => html`<pre class="code" style="margin-top:8px">${s.text}</pre>${cut(s)}`)}</details></div>
      <div class="section"><h4>② Quá trình: công cụ đã dùng (${Object.entries(t.tools_used).map(([k, v]) => `${k} ×${v}`).join(', ') || 'không'})</h4>
        ${flow.map((f) => f.call ? html`<details class="step call"><summary>${icon('tool', 14)}<b>${f.call.tool}</b><span class="muted small mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${JSON.stringify(f.call.args).slice(0, 100)}</span></summary><div class="body"><div class="muted small">tham số</div><pre class="code">${JSON.stringify(f.call.args, null, 1)}</pre>${f.ret ? html`<div class="muted small" style="margin-top:8px">kết quả trả về</div><pre class="code">${f.ret.text}</pre>${cut(f.ret)}` : ''}</div></details>`
          : html`<details class="step ${f.s.type === 'retry' ? 'retry' : ''}" ${f.s.type === 'retry' ? 'open' : ''}><summary>${f.s.type === 'retry' ? 'Cổng từ chối, AI phải làm lại' : f.s.type === 'thinking' ? 'Suy nghĩ' : 'AI nói'}</summary><div class="body"><pre class="code">${f.s.text}</pre></div></details>`)}${flow.length ? '' : html`<span class="muted">không dùng công cụ</span>`}</div>
      <div class="section"><h4>③ AI trả gì (đầu ra cuối, trước khi qua cổng kiểm chứng)</h4><pre class="code">${typeof t.output === 'string' ? t.output : JSON.stringify(t.output, null, 1)}</pre><div class="hint muted small" style="margin-top:6px">Đầu ra này chỉ là đề xuất. Chỉ khi qua cổng tất định (Schema gate, Test driver…) nó mới thành bằng chứng.</div></div>`;
  }
  async function openEvent(seq) {
    const ev = await api(`/api/runs/${S.id}/events/${seq}`); const title = `#${seq} · ${KIND_VN[ev.kind] || ev.kind}${ev.role ? ' · ' + ev.role : ''}`;
    if (ev.transcript) return openDrawer(title, transcriptView(ev), true);
    const llm = ev.kind === 'message' ? S.llmByMsg[ev.payload.msg_id] : null;
    openDrawer(title, html`<div class="section muted">${ev.summary}</div>${llm ? html`<div class="section"><button class="btn" data-open="${llm}">${icon('eye', 14)}Xem lần gọi LLM tương ứng</button></div>` : ''}<pre class="code">${JSON.stringify(ev.payload, null, 1)}</pre>`);
  }

  /* ---------- nạp, luồng trực tiếp, phát lại ---------- */
  async function loadEvents() { for (;;) { const r = await api(`/api/runs/${S.id}/events?after=${S.lastSeq}&limit=1000`); r.events.forEach((e) => { S.events.push(e); apply(e, false); }); if (r.events.length < 1000) return r; } }
  function connect() {
    const es = (S.es = new EventSource(`/api/runs/${S.id}/stream?after=${S.lastSeq}`));
    es.addEventListener('trace', (m) => { const e = JSON.parse(m.data); if (e.seq <= S.lastSeq || S.replaying) return; S.events.push(e); apply(e, true); render(); });
    es.addEventListener('status', async (m) => { S.status = JSON.parse(m.data).status; S.run = { ...S.run, ...(await api(`/api/runs/${S.id}`)) }; render(); });
    es.addEventListener('end', async (m) => { es.close(); S.status = JSON.parse(m.data).status; S.run = await api(`/api/runs/${S.id}`); S.evDirty = true; render(); });
  }
  function replay(speed) {
    if (S.replaying) { S.replaying = false; return; }
    const all = S.events.slice(), real = S.status; S.replaying = true; S.speed = speed; S.events = []; resetDerived(); all.forEach((e) => e.role && nodeOf(e.role)); S.status = 'running'; S.tab = 'chat';
    let i = 0;
    const next = () => {
      if (!S.replaying || i >= all.length) { S.replaying = false; S.speed = 1; S.status = real; S.events = all; resetDerived(); all.forEach((e) => apply(e, false)); render(); return; }
      const e = all[i++]; S.events.push(e); apply(e, true); render();
      setTimeout(next, i < all.length ? Math.max(30, Math.min(900, (all[i].ts_ns - e.ts_ns) / 1e6 / speed)) : 0);
    };
    next();
  }

  /* ---------- sự kiện ---------- */
  on(ctx.el, 'click', '[data-tab]', (b, e) => { e.preventDefault(); S.tab = b.dataset.tab; render(); });
  on(ctx.el, 'click', '[data-seq]', (el, e) => { e.preventDefault(); openEvent(Number(el.dataset.seq)); });
  on(ctx.el, 'click', '[data-ev]', async (el, e) => {
    if (e.target.closest('[data-flagm]')) return;  // bấm cờ không mở bằng chứng
    e.preventDefault(); const x = await api(`/api/runs/${S.id}/evidence/${encodeURIComponent(el.dataset.ev)}`);
    openDrawer(`Bằng chứng · ${x.kind}`, html`<div class="section row"><span class="chip accent">${x.tier}</span><span class="chip">${x.polarity}</span><span class="chip">IFC ${x.ifc}</span><span class="muted small">do ${x.produced_by}</span><span class="grow"></span>${flagMenu(S.id, x.record.requirement_id, x.evidence_id, canReview())}</div><pre class="code">${JSON.stringify(x.record, null, 1)}</pre>`);
  });
  wireForm(ctx.el, () => ({ run: S.id, setError: (rid, err) => { S.rvErr[rid] = err; }, onSubmitted: async () => { await loadReviews(); window.dispatchEvent(new Event('rfcv:review-submitted')); render(); } }), render);
  const onRv = () => render(); window.addEventListener('rfcv:rv', onRv);
  on(ctx.el, 'click', '[data-node]', (g) => { S.sel = S.sel === g.dataset.node ? null : g.dataset.node; S.tab = 'chat'; render(); });
  on(ctx.el, 'keydown', '[data-node]', (g, e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); g.dispatchEvent(new MouseEvent('click', { bubbles: true })); } });
  on(ctx.el, 'click', '[data-code]', (b, e) => { e.preventDefault(); const [path, line] = b.dataset.code.split('|'); openExplorer(S.id, { path, line: Number(line) }); });
  on(ctx.el, 'click', '[data-explorer]', () => openExplorer(S.id, { path: S.code.cur }));
  on(ctx.el, 'click', '[data-evview]', (b) => { S.evView = b.dataset.evview; render(); });
  on(ctx.el, 'click', '[data-goto]', (b, e) => { e.preventDefault(); scrollToLine(Number(b.dataset.goto), true); });
  on(ctx.el, 'change', '#code-tier', (el) => { S.code.tier = el.value; render(); }); on(ctx.el, 'change', '#code-req', (el) => { S.code.req = el.value; render(); });
  on(ctx.el, 'change', '#code-q', (el) => { S.code.q = el.value; S.code.qIdx = 0; S.code.focus = null; render(); setTimeout(() => { const m = $('.cl.found', ctx.el); if (m) scrollToLine(m, true); }, 80); });
  on(ctx.el, 'click', '[data-qnext]', () => { const ms = $$('.cl.found', ctx.el); if (!ms.length) return; S.code.qIdx = (S.code.qIdx + 1) % ms.length; scrollToLine(ms[S.code.qIdx], true); });
  on(ctx.el, 'click', '[data-cf]', (b) => { S.code.show[b.dataset.cf] = !S.code.show[b.dataset.cf]; render(); });
  on(ctx.el, 'change', '#code-file', (el) => { S.code.cur = el.value; S.code.data = null; render(); });
  on(ctx.el, 'click', '[data-next-bad]', () => { const f = $('.codeframe', ctx.el), marks = $$('.cl.mismatch', f), top = f.getBoundingClientRect().top; const next = marks.find((m) => m.getBoundingClientRect().top > top + 40) || marks[0]; scrollToLine(next, true); });
  on(ctx.el, 'click', '[data-clear]', (_, e) => { e.preventDefault(); S.sel = null; render(); });
  on(ctx.el, 'click', '#cancel-run', async (b) => { b.disabled = true; await api(`/api/runs/${S.id}/cancel`, { body: {} }).catch((x) => { b.disabled = false; toast(x.message, 'bad'); }); });
  on(ctx.el, 'click', '#replay', () => { const s = $('#speed', ctx.el); if (s) S.speedPref = Number(s.value); replay(S.speedPref); });
  on(ctx.el, 'click', '#rerun', async () => { try { const r = await api(`/api/runs/${S.id}/rerun`, { body: {} }); toast('Đã xếp hàng lần chạy lại', 'ok'); location.hash = `#/runs/${r.runs[0].run_id}`; } catch (e) { toast(e.message, 'bad'); } });
  on(ctx.el, 'change', '#tl-kind', (el) => { S.tl.kind = el.value; render(); }); on(ctx.el, 'change', '#tl-role', (el) => { S.tl.role = el.value; render(); });
  on(ctx.el, 'change', '#tl-noisy', (el) => { S.tl.noisy = el.checked; render(); }); on(ctx.el, 'change', '#tl-q', (el) => { S.tl.q = el.value; render(); });
  on(ctx.el, 'click', '#verify', async () => { const o = $('#verify-out', ctx.el); try { const r = await api(`/api/runs/${S.id}/verify`); mount(o, r.ok ? html`<span class="badge ok">${icon('check', 12)}nguyên vẹn · ${r.count} bản ghi</span>` : html`<span class="badge bad">HỎNG ${JSON.stringify(r)}</span>`); } catch (e) { o.textContent = e.message; } });
  const drawerClick = (e) => { const b = e.target.closest('[data-open]'); if (b) openEvent(Number(b.dataset.open)); };
  $('#drawer-body').addEventListener('click', drawerClick);

  /* ---------- khởi động ---------- */
  frame(); seedNodes();
  const first = await loadEvents(); if (!ctx.alive()) return;
  [S.meta] = await Promise.all([reviewMeta(), loadReviews()]);
  S.status = first.status; S.follow = live(); if (S.events.some((e) => e.kind === 'verdict') && !live()) S.tab = 'summary';
  if (openTab) { S.tab = openTab === 'code' || openTab === 'explorer' ? 'evidence' : openTab; if (openTab === 'code' || openTab === 'explorer') S.evView = 'code'; }
  if (openTab === 'review') S.tab = 'summary';
  await draw();
  if (openTab === 'review' && openReq) setTimeout(() => { const el = document.getElementById('rv-' + openReq); el?.scrollIntoView({ block: 'start' }); el?.classList.add('flash-box'); }, 120);
  if (openSeq) openEvent(Number(openSeq));
  if (live()) connect();
  const tick = setInterval(() => { if (live() || S.replaying) { const el = elapsed(); if (el != null) drawTop(); } }, 1000);
  if (openTab === 'explorer') openExplorer(S.id);
  ctx.onLeave(() => { window.removeEventListener('rfcv:rv', onRv); closeExplorer(); clearInterval(tick); S.es?.close(); S.replaying = false; $('#drawer-body').removeEventListener('click', drawerClick); });
}
