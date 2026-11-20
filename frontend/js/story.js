/* Hành trình của một lần chạy, kể bằng lời thường: ai được giao việc gì, vì sao, đã dùng công cụ nào, kết quả ra sao, và kết luận
   được suy ra thế nào. Cộng thêm: lời dẫn "đang làm gì" cho lần chạy trực tiếp, biểu đồ làn (swimlane) theo thời gian, và tab "Bài học"
   rút kinh nghiệm từ hành vi của agent. Mọi thứ chỉ suy ra từ sự kiện trace; không đoán, không gọi thêm API. */
import { esc, fmt, html, icon, labelOf, raw, ruleTitles, verdict } from './lib.js';

export const HUB = 'execution_loop';

/* ---------- từ điển giải thích ---------- */
export const AGENT_VN = {
  planner: ['Planner', 'AI lập kế hoạch: nhìn bằng chứng hiện có rồi quyết định giao việc gì tiếp'],
  tester: ['Tester', 'chạy các kịch bản kiểm thử (biến thể) lên SUT thật và ghi kết quả'],
  code_reader: ['Code Reader', 'AI đọc mã nguồn để tìm chỗ hiện thực yêu cầu'],
  code_indexer: ['Code Indexer', 'dựng chỉ mục mã (ký hiệu, lời gọi) để các agent tra cứu'],
  locator: ['Locator', 'khoanh vùng mã liên quan từ kết quả kiểm thử'],
  verifier: ['Verifier', 'AI phản biện: soi bằng chứng đã có và tìm lỗ hổng'],
  rfc_analyst: ['RFC Analyst', 'AI đọc RFC và biên soạn yêu cầu'],
  [HUB]: ['Hub', 'bộ điều phối tất định: giao việc, giữ ngân sách, quyết định dừng'],
  verdict: ['Verdict engine', 'bộ quy tắc cố định gán nhãn từ bằng chứng (không dùng LLM)'],
};
export const agentName = (r) => (AGENT_VN[r] ? AGENT_VN[r][0] : r || 'hệ thống');

export const TASK_VN = {
  RFC_TO_RBS: 'Dịch câu RFC sang RBS (mù với bản người viết)',
  SELECT_TESTS: 'Chọn và chạy các ca kiểm thử trên SUT thật',
  LOCATE: 'Tìm trong mã nơi yêu cầu được hiện thực',
  TRACE_PATHS: 'Lần theo các đường thực thi tới điểm đó',
  RECHECK: 'Xem lại đúng khía cạnh đang mâu thuẫn',
  MAP_COMPONENTS: 'Lập bản đồ các thành phần mã liên quan',
  STATIC_QUERY: 'Truy vấn phân tích tĩnh trên chỉ mục mã',
  CRITIQUE: 'Phản biện bằng chứng trước khi chốt nhãn',
};
export const ASPECT_VN = { CONDITION: 'điều kiện kích hoạt', THRESHOLD: 'ngưỡng so sánh', REACTION: 'phản ứng (cảnh báo/đóng)', ORDER_STATE: 'thứ tự/trạng thái', EFFECT: 'tác động nội bộ' };
export const RATIONALE_VN = {
  INITIAL_TYPE_A: 'Vòng đầu, yêu cầu loại A: kiểm thử chạy thật trước, vì hành vi quan sát được từ ngoài',
  INITIAL_TYPE_B: 'Vòng đầu, yêu cầu loại B: kiểm thử chạy thật trước, vì hành vi quan sát được từ ngoài',
  INITIAL_TYPE_C: 'Vòng đầu, yêu cầu loại C: kiểm thử chạy thật trước (thứ tự/trạng thái)',
  INITIAL_TYPE_D: 'Vòng đầu, yêu cầu loại D: hành vi nội bộ nên dùng bằng chứng tĩnh, không chạy kiểm thử',
  FILL_MISSING_VARIANT: 'Còn thiếu bằng chứng, lấp chỗ trống',
  RESOLVE_CONFLICT: 'Hai nguồn bằng chứng mâu thuẫn nhau, cần giải quyết',
  CRITIQUE_BEFORE_COMPLIANT: 'Sắp chốt TUÂN THỦ nên phải qua phản biện trước',
  FOLLOW_CRITIQUE: 'Làm theo vấn đề mà bước phản biện nêu ra',
  DECISIVE_VIOLATION: 'Đã có bằng chứng quyết định là VI PHẠM',
  DECISIVE_COMPLIANT: 'Đã có bằng chứng quyết định là TUÂN THỦ',
  INFEASIBLE: 'Phần còn thiếu không thể làm được trong môi trường này',
  DEVIATE_PLAYBOOK: 'Planner cố ý làm khác sổ tay (vì làm theo sổ tay đã thất bại)',
};
export const RULE_VN = {
  V0: ['Kết quả kiểm thử không ổn định', 'chạy lại cùng ca mà ra kết quả khác nhau, nên không dám kết luận'],
  V1: ['Thiếu nhân chứng dương', 'chưa chứng minh được bản tham chiếu đúng biết phân biệt, nên ca FAIL có thể do môi trường'],
  V2: ['Kiểm thử FAIL hợp lệ', 'chạy thật trên SUT, hành vi quan sát được trái với yêu cầu; đây là bằng chứng mạnh nhất'],
  V3: ['Máy trạng thái học được vi phạm', 'mô hình hành vi học từ SUT cho thấy chuỗi thông điệp sai thứ tự'],
  V4: ['Nhánh nghi vấn trên đường xử lý', 'phân tích tĩnh thấy chỗ đáng ngờ trên đường xử lý, cần người xem'],
  V5: ['Tuân thủ, có liên kết độ phủ', 'kiểm thử PASS và độ phủ chứng minh dòng mã đã định vị thực sự được chạy qua; mức bảo đảm cao nhất'],
  V6: ['Tuân thủ theo hành vi', 'mọi ca kiểm thử PASS nhưng chưa chứng minh được mã đã định vị bị chạy qua'],
  V7: ['Cần xem xét: bằng chứng chưa khớp', 'kiểm thử PASS nhưng mã (T1/T2) bác bỏ, hoặc độ phủ không đi qua đoạn mã đã định vị'],
  V8: ['Loại D: phân tích tĩnh', 'yêu cầu nội bộ, kết luận từ có/không có đường vi phạm trong mã'],
  V9: ['Mặc định: không đủ để kết luận', 'không quy tắc nào khớp, nên hệ thống không dám chốt'],
};
Object.entries(RULE_VN).forEach(([k, [t, d]]) => { ruleTitles[k] = `${k}: ${t}. ${d}`; });
export const ruleInfo = (r) => RULE_VN[String(r || '').split('-')[0]] || null;
export const RTYPE_VN = { A: 'quan sát được từ ngoài (điều kiện)', B: 'quan sát được từ ngoài (điều kiện + phản ứng)', C: 'thứ tự/trạng thái thông điệp', D: 'hành vi nội bộ, không quan sát từ ngoài' };
export const STOP_VN = { SUFFICIENT: 'Đã đủ bằng chứng để chốt nhãn', BUDGET: 'Hết ngân sách', INFEASIBLE: 'Phần còn thiếu không thể làm được', MAX_ROUNDS: 'Hết số vòng cho phép' };
export const ISSUE_VN = { MISSING_EVIDENCE: 'thiếu bằng chứng', MISSING_PATH: 'chưa lần hết đường thực thi', WRONG_LOCATION: 'định vị mã sai chỗ', CONTRADICTION: 'bằng chứng tự mâu thuẫn', MISSING_VARIANT: 'thiếu biến thể kiểm thử' };
export const FAIL_VN = {
  UsageLimitExceeded: 'vượt hạn mức token của một nhiệm vụ (AI đọc quá nhiều rồi bị cắt giữa chừng)',
  COMMAND_REJECTED: 'lệnh bị sandbox từ chối',
  FLAG_NOT_ALLOWED: 'dùng cờ lệnh không nằm trong danh sách cho phép',
  ModelHTTPError: 'nhà cung cấp mô hình trả lỗi HTTP',
  UnexpectedModelBehavior: 'mô hình trả đầu ra không hợp lệ nhiều lần',
  TimeoutError: 'quá thời gian',
};
const failText = (c) => FAIL_VN[c] || c || 'lỗi không rõ';
const task = (e) => e.payload.body?.task_type || e.payload.body?.task?.task_type || '';
const short = (s, n = 110) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n) + '…' : s; };
const variantVn = (v) => {
  const [k, rest] = String(v).split(':'); const m = { at_limit: 'sát ngưỡng', boundary: 'vượt ngưỡng 1', max: 'giá trị lớn nhất', random: 'ngẫu nhiên', valid_random: 'ngẫu nhiên hợp lệ' };
  return m[k] ? `${m[k]}${rest ? ' · ' + rest : ''}` : String(v);
};

/* ---------- dựng mô hình từ sự kiện ---------- */
/* Mỗi yêu cầu → các vòng → các bước. Bước = một lần Hub giao việc cho một agent, kèm mọi thứ xảy ra cho tới khi agent trả kết quả. */
export function buildModel(events) {
  const reqs = {}, order = [], byMsg = {}, open = {};
  const R = (id) => { if (!id) return null; if (!reqs[id]) { reqs[id] = { id, rounds: [], cur: null, start: null, stop: null, verdict: null, ts0: 0, ts1: 0, rfc: { start: null, proposal: null, skipped: null } }; order.push(id); } return reqs[id]; };
  const roundOf = (r, n) => { n = n ?? (r.cur || 1); let x = r.rounds.find((q) => q.n === n); if (!x) { x = { n, steps: [], plan: null, ctx: null, suff: null, critique: null, ts0: 0 }; r.rounds.push(x); r.rounds.sort((a, b) => a.n - b.n); } return x; };
  const find = (e, p) => (p.msg_id && byMsg[p.msg_id]) || (open[e.role] || []).slice(-1)[0] || null;
  for (const e of events) {
    const p = e.payload || {}, r = R(e.requirement_id); if (r) { r.ts0 ||= e.ts_ns; r.ts1 = e.ts_ns; }
    switch (e.kind) {
      case 'requirement_start': if (r) r.start = e; break;
      case 'rfc_analysis_start': if (r) r.rfc.start = e; break;
      case 'rfc_proposal': if (r) r.rfc.proposal = e; break;
      case 'rfc_analysis_skipped': if (r) r.rfc.skipped = e; break;
      case 'round_start': if (r) { r.cur = p.round; roundOf(r, p.round).ts0 = e.ts_ns; } break;
      case 'message': {
        if (!r) break; const rd = roundOf(r, p.round);
        const s = { msg: e, to: e.role, task: task(e), params: p.body?.params || p.body?.task?.params || {}, round: rd.n, tools: [], denied: [], retries: [], rejects: [], live: [], t3: {}, t3v: [], llm: null, done: null, result: null, failure: null, req: r.id };
        byMsg[p.msg_id] = s; (open[e.role] ||= []).push(s); rd.steps.push(s); break;
      }
      case 'tool_call': { const s = find(e, p); if (s) s.tools.push(e); break; }
      case 'agent_step': { const s = find(e, p); if (s) s.live.push(e); break; }
      case 'tool_denied': { const s = find(e, p); if (s) s.denied.push(e); break; }
      case 'output_retry': case 'gate_reject': { const s = find(e, p); if (s) (e.kind === 'gate_reject' ? s.rejects : s.retries).push(e); break; }
      case 'llm_run': case 'llm_failure': { const s = byMsg[p.msg_id]; if (s) { s.llm = e; if (e.kind === 'llm_failure') s.failure = p; } break; }
      case 'role_run': { const s = byMsg[p.msg_id]; if (s) { s.done = e; const q = open[p.role] || []; const i = q.indexOf(s); if (i >= 0) q.splice(i, 1); } break; }
      case 'task_result': { const s = byMsg[p.msg_id]; if (s) s.result = e; break; }
      case 't3': { const q = (open.tester || []).slice(-1)[0] || Object.values(byMsg).filter((s) => s.to === 'tester').pop(); if (q) { q.t3[p.outcome] = (q.t3[p.outcome] || 0) + 1; q.t3v.push(p); } break; }
      case 'plan': if (r) { const rd = roundOf(r, p.round); rd.plan = e; } break;
      case 'plan_context': if (r) roundOf(r, p.round).ctx = e; break;
      case 'sufficiency': if (r) roundOf(r).suff = e; break;
      case 'critique_result': if (r) roundOf(r, p.round).critique = e; break;
      case 'stop': if (r) r.stop = e; break;
      case 'verdict': if (r) r.verdict = e; break;
    }
  }
  return { reqs: order.map((i) => reqs[i]), byMsg, events };
}

const stepTokens = (s) => s.done?.payload.tokens || 0;
const stepOpen = (s) => !s.done && !s.result && !s.failure;  // agent tất định (tester) không có role_run: task_result mới là dấu xong

/* ---------- lời dẫn "đang làm gì" ---------- */
export function narrate(model, isLive) {
  const all = model.reqs.flatMap((r) => r.rounds.flatMap((x) => x.steps.map((s) => ({ s, r }))));
  const active = all.filter(({ s }) => stepOpen(s));
  const last = model.events[model.events.length - 1];
  if (!model.events.length) return { tone: 'info', head: isLive ? 'Đang khởi động…' : 'Lần chạy chưa có sự kiện', sub: 'Máy chủ đang dựng môi trường và nạp yêu cầu.' };
  if (active.length) {
    const { s, r } = active[active.length - 1];
    const tl = s.tools[s.tools.length - 1], who = agentName(s.to);
    const what = s.to === 'planner' ? 'đang cân nhắc nên làm gì tiếp' : `đang thực hiện ${s.task || 'nhiệm vụ'}${TASK_VN[s.task] ? ' — ' + TASK_VN[s.task].toLowerCase() : ''}`;
    const extra = tl ? `Công cụ gần nhất: ${tl.payload.tool} ${short(JSON.stringify(tl.payload.args || {}), 70)}` : s.to === 'planner' ? 'Planner đọc bằng chứng hiện có rồi chọn bước tiếp theo.' : 'Chưa gọi công cụ nào.';
    return { tone: 'info', pulse: true, head: `${who} ${what}`, sub: `${r.id} · vòng ${s.round} · ${s.tools.length} lần gọi công cụ · ${extra}` };
  }
  const v = model.reqs.filter((r) => r.verdict);
  if (v.length && v.length === model.reqs.length) {
    const [t, tone] = labelOf(v[0].verdict.payload.label); const rl = ruleInfo(v[0].verdict.payload.rule);
    return { tone, head: v.length === 1 ? `Kết luận: ${t}` : `Đã kết luận ${v.length} yêu cầu`, sub: v.length === 1 ? `${v[0].id} theo quy tắc ${v[0].verdict.payload.rule}${rl ? ' — ' + rl[1] : ''}.` : v.map((x) => `${x.id}: ${labelOf(x.verdict.payload.label)[0]}`).join(' · ') };
  }
  if (last.kind === 'sufficiency') return { tone: 'info', pulse: isLive, head: 'Verdict engine đang đánh giá bằng chứng đã đủ chưa', sub: 'Bộ quy tắc tất định xem còn thiếu gì và có mâu thuẫn không.' };
  return { tone: 'info', pulse: isLive, head: isLive ? 'Hub đang điều phối bước tiếp theo' : 'Lần chạy đã dừng', sub: 'Hub giữ ngân sách, nhận kết quả và hỏi Planner khi cần.' };
}

/* ---------- tab Hành trình ---------- */
const lineTool = (t) => { const p = t.payload; const out = String(p.output || '').replace(/^\[[A-Z]+\]\s*tool=\S+\s*/, ''); return html`<details class="jr-tool"><summary><span class="chip accent mono">${p.tool}</span><span class="mono small muted jr-args">${short(JSON.stringify(p.args || {}), 90)}</span></summary><div class="body"><div class="muted small">tham số</div><pre class="code">${JSON.stringify(p.args || {}, null, 1)}</pre><div class="muted small" style="margin-top:8px">kết quả${p.label ? ' · nhãn tin cậy ' + p.label : ''}${p.output_truncated ? ' · đã cắt bớt' : ''}</div><pre class="code">${short(out, 1800)}</pre></div></details>`; };

function t3Bars(s) {
  const n = Object.values(s.t3).reduce((a, b) => a + b, 0); if (!n) return '';
  const col = { PASS: 'var(--good)', FAIL: 'var(--critical)' };
  return html`<div class="jr-t3"><div class="segbar" role="img" aria-label="Kết quả ca kiểm thử">${Object.entries(s.t3).map(([k, v]) => html`<div class="seg-part" style="flex:${v};background:${col[k] || 'var(--warning)'}" title="${k}: ${v}"></div>`)}</div>
    <div class="small muted" style="margin-top:4px">${Object.entries(s.t3).map(([k, v]) => `${v} ${k}`).join(' · ')} trên ${n} biến thể kiểm thử${s.t3v.some((x) => x.outcome === 'FAIL') ? '. FAIL: ' + s.t3v.filter((x) => x.outcome === 'FAIL').slice(0, 3).map((x) => variantVn(x.variant)).join(', ') : ''}</div></div>`;
}

function stepView(s) {
  const d = s.done?.payload, who = agentName(s.to), isPlanner = s.to === 'planner', openNow = stepOpen(s);
  const failed = s.failure || (d && !d.ok);
  const ev = s.llm ? s.llm.seq : s.msg.seq;
  const title = isPlanner ? html`<b>Planner</b> cân nhắc bước tiếp theo` : html`Hub giao cho <b>${who}</b>: ${s.task ? html`<span class="chip accent">${s.task}</span>` : ''}`;
  const why = isPlanner ? '' : TASK_VN[s.task] ? html`<div class="jr-why">${TASK_VN[s.task]}.</div>` : '';
  const pr = s.params || {}, chips = [];
  if (pr.aspects?.length) chips.push(html`<span class="chip">khía cạnh: ${pr.aspects.map((a) => ASPECT_VN[a] || a).join(', ')}</span>`);
  if (pr.aspect) chips.push(html`<span class="chip">khía cạnh: ${ASPECT_VN[pr.aspect] || pr.aspect}</span>`);
  if (pr.missing_variants?.length) chips.push(html`<span class="chip">${pr.missing_variants.length} biến thể cần chạy</span>`);
  if (pr.start_hints === 'locator') chips.push(html`<span class="chip">bắt đầu từ gợi ý của Locator</span>`);
  const toolMap = {}; s.tools.forEach((t) => { toolMap[t.payload.tool] = (toolMap[t.payload.tool] || 0) + 1; });
  const yieldN = s.result?.payload.new_evidence;
  const outcome = openNow ? html`<div class="jr-out run"><span class="spin"></span>${who} đang làm việc…</div>`
    : failed ? html`<div class="jr-out bad">${icon('x', 15)}<div><b>${who} không hoàn thành.</b> ${failText(s.failure?.error || d?.failure)}.${s.failure?.detail ? html`<div class="small muted">${short(s.failure.detail, 220)}</div>` : ''}<div class="small muted">${d ? `${fmt.ms(d.duration_ms)} · ${fmt.tok(d.tokens)} token đã tiêu · ${d.tool_calls} công cụ` : ''}</div></div></div>`
      : html`<div class="jr-out ok">${icon('check', 15)}<div><b>${who} xong</b> trong ${fmt.ms(d?.duration_ms)}, ${fmt.tok(d?.tokens)} token, ${d?.tool_calls ?? 0} công cụ${d?.output_retries ? `, phải làm lại ${d.output_retries} lần` : ''}.${yieldN != null ? html` Hub nhận <b>${yieldN}</b> bằng chứng mới${yieldN === 0 && !isPlanner ? html` <span class="badge warn">không thêm được gì</span>` : ''}.` : ''}</div></div>`;
  return html`<li class="jr-step ${failed ? 'bad' : openNow ? 'run' : isPlanner ? 'plan' : 'ok'}">
    <div class="jr-title">${title}<button class="btn sm ghost" data-seq="${ev}" title="Xem AI nhận gì, dùng công cụ nào, trả gì">${icon('eye', 13)}Xem chi tiết</button></div>
    ${why}${chips.length ? html`<div class="jr-chips">${chips}</div>` : ''}
    ${s.denied.length ? html`<div class="jr-note bad">${icon('alert', 14)}<div>${s.denied.length} lệnh bị chặn: ${s.denied.slice(0, 3).map((t) => html`<span class="chip bad mono">${t.payload.tool}</span> <span class="small">${failText(t.payload.reason || t.payload.code)}</span> `)}<div class="small muted">Chặn là cơ chế an toàn đang hoạt động; agent phải đổi cách làm.</div></div></div>` : ''}
    ${s.retries.length || s.rejects.length ? html`<div class="jr-note warn">${icon('refresh', 14)}<div>Cổng kiểm tra đã trả đầu ra ${s.retries.length + s.rejects.length} lần, AI phải làm lại để đúng định dạng/quy tắc.</div></div>` : ''}
    ${Object.keys(toolMap).length ? html`<details class="jr-tools"><summary>${icon('tool', 13)}Đã dùng ${s.tools.length} lần công cụ: ${Object.entries(toolMap).map(([t, n]) => html`<span class="chip accent mono">${t}${n > 1 ? ' ×' + n : ''}</span>`)}</summary>${s.tools.slice(0, 40).map(lineTool)}${s.tools.length > 40 ? html`<div class="muted small">… còn ${s.tools.length - 40} lần nữa, xem dòng thời gian.</div>` : ''}</details>` : ''}
    ${t3Bars(s)}${outcome}</li>`;
}

function suffView(rd) {
  const e = rd.suff; if (!e) return '';
  const p = e.payload, pv = p.provisional, miss = p.missing || [], conf = p.conflicts || [];
  const rl = pv ? ruleInfo(pv.rule) : null;
  return html`<li class="jr-step sys"><div class="jr-title"><b>Verdict engine</b> kiểm tra: đủ bằng chứng để chốt chưa? <button class="btn sm ghost" data-seq="${e.seq}">${icon('eye', 13)}Chi tiết</button></div>
    <div class="jr-out ${p.decisive ? 'ok' : 'info'}">${icon(p.decisive ? 'check' : 'info', 15)}<div>${pv ? html`Nhãn tạm: ${verdict(pv.label, pv.rule)}${rl ? html` <span class="small muted">— ${rl[1]}</span>` : ''}` : 'Chưa có nhãn tạm.'}
      <div class="small">${p.decisive ? html`<b>Đủ quyết định.</b> Không cần thêm bằng chứng để đổi nhãn.` : html`<b>Chưa đủ.</b> Còn thiếu ${miss.length} mục, ${conf.length} mâu thuẫn.`}</div>
      ${miss.length ? html`<details class="jr-miss"><summary class="small">Còn thiếu gì?</summary><ul>${miss.slice(0, 12).map((m) => html`<li><span class="chip">${m.need}</span> ${variantVn(m.variant)} <span class="muted small">— ${m.reason}</span></li>`)}${miss.length > 12 ? html`<li class="muted small">… và ${miss.length - 12} mục nữa</li>` : ''}</ul></details>` : ''}</div></div></li>`;
}

function critView(rd) {
  const e = rd.critique; if (!e) return '';
  const p = e.payload;
  return html`<li class="jr-step ${p.clean ? 'sys' : 'warn'}"><div class="jr-title"><b>Verifier</b> phản biện bằng chứng <button class="btn sm ghost" data-seq="${e.seq}">${icon('eye', 13)}Chi tiết</button></div>
    <div class="jr-out ${p.clean ? 'ok' : 'warn'}">${icon(p.clean ? 'check' : 'alert', 15)}<div>${p.clean ? 'Không tìm thấy lỗ hổng: bằng chứng đứng vững.' : html`Nêu ${(p.issues || []).length} vấn đề: ${(p.issues || []).map((i) => html`<span class="badge warn">${ISSUE_VN[i.kind] || i.kind}</span> `)}<div class="small muted">Planner sẽ được yêu cầu xử lý các vấn đề này ở vòng sau.</div>`}</div></div></li>`;
}

function planView(rd) {
  const e = rd.plan, c = rd.ctx?.payload; if (!e) return '';
  const p = e.payload, adv = c?.advice;
  const dev = (c && c.adherence && c.adherence !== 'followed') || p.rationale_code === 'DEVIATE_PLAYBOOK';
  return html`<li class="jr-step plan"><div class="jr-title"><b>Planner quyết định</b> ${p.action === 'stop' ? 'dừng' : 'giao'}: ${(p.tasks || []).map((t) => html`<span class="chip accent">${t.task_type} → ${agentName(t.target_role)}</span>`)}<button class="btn sm ghost" data-seq="${e.seq}">${icon('eye', 13)}Chi tiết</button></div>
    <div class="jr-why">${RATIONALE_VN[p.rationale_code] || p.rationale_code}.</div>
    ${adv ? html`<div class="jr-note ${dev ? 'warn' : 'info'}">${icon('book', 14)}<div>Sổ tay (quy tắc <span class="mono">${adv.rule}</span>) gợi ý ${(adv.tasks || []).join(' + ') || 'dừng'}. ${dev ? html`<b>Planner làm khác sổ tay</b>.` : 'Planner làm theo.'}</div></div>` : ''}</li>`;
}

function verdictView(r) {
  const v = r.verdict; if (!v) return '';
  const p = v.payload, [t, tone, ic] = labelOf(p.label), rl = ruleInfo(p.rule), st = r.stop?.payload;
  const evN = (p.evidence_ids || []).length;
  const tests = r.rounds.flatMap((x) => x.steps).filter((s) => s.to === 'tester').reduce((a, s) => { Object.entries(s.t3).forEach(([k, n]) => { a[k] = (a[k] || 0) + n; }); return a; }, {});
  const chain = [
    st ? html`<b>Dừng điều tra:</b> ${STOP_VN[st.reason] || st.reason}. Đã dùng ${st.used?.rounds ?? '–'} vòng, ${fmt.tok(st.used?.tokens)} token, ${st.used?.tool_calls ?? '–'} lần gọi công cụ.` : '',
    Object.keys(tests).length ? html`<b>Bằng chứng chạy thật:</b> ${Object.entries(tests).map(([k, n]) => `${n} ${k}`).join(', ')} trên SUT.` : '',
    html`<b>Quy tắc áp dụng ${p.rule}:</b> ${rl ? html`${rl[0]} — ${rl[1]}.` : 'xem bộ quy tắc của miền.'}`,
    html`<b>Nhãn ${t}</b> dựa trên ${evN} bản ghi bằng chứng${p.assurance ? `, mức bảo đảm ${p.assurance}` : ''}. Nhãn do bộ quy tắc cố định gán, không phải do AI phán đoán.`,
  ].filter(Boolean);
  return html`<div class="jr-verdict ${tone}"><div class="row"><span class="jr-vic">${icon(ic, 22)}</span><div class="grow"><div class="small muted">Kết luận cho ${r.id}</div><div class="jr-vt">${t} <span class="mono small muted">${p.rule}</span></div></div>
    <button class="btn" data-tabgo="evidence">${icon('shield', 14)}Xem ${evN} bằng chứng</button><button class="btn" data-seq="${v.seq}">${icon('eye', 14)}Chi tiết</button></div>
    <div class="jr-chain-h">Vì sao ra kết luận này?</div><ol class="jr-chain">${chain.map((c) => html`<li>${c}</li>`)}</ol></div>`;
}

export function storyView(model, opts = {}) {
  if (!model.reqs.length) return html`<div class="empty-note">Chưa có yêu cầu nào bắt đầu. Hành trình sẽ hiện ngay khi Hub bắt đầu điều tra.</div>`;
  const intro = opts.hideIntro ? '' : html`<details class="jr-intro-d"><summary>${icon('info', 14)}Cách đọc trang này</summary><div class="jr-intro"><div>Hệ thống kiểm chứng một yêu cầu của RFC theo vòng: <b>Planner</b> (AI) chọn việc → <b>Hub</b> giao cho agent → agent dùng công cụ → kết quả thành <b>bằng chứng</b> → <b>Verdict engine</b> (quy tắc cố định, không phải AI) xét đã đủ chưa. Mỗi bước dưới đây nói rõ <i>làm gì · vì sao · kết quả</i>; bấm <b>Xem chi tiết</b> để thấy nguyên văn AI nhận và trả gì.</div><button class="icon-btn" data-dismiss-intro aria-label="Ẩn hướng dẫn">${icon('x', 14)}</button></div></details>`;
  return html`${intro}${model.reqs.map((r) => {
    const st = r.start?.payload || {}, b = st.budget || {};
    return html`<section class="jr-req"><header class="jr-req-h"><div><div class="row"><h3 class="mono">${r.id}</h3>${st.modal ? html`<span class="chip">${st.modal}</span>` : ''}${st.rtype ? html`<span class="chip">loại ${st.rtype}</span>` : ''}</div>
      <div class="small muted">${st.rtype ? `Loại ${st.rtype}: ${RTYPE_VN[st.rtype] || ''}. ` : ''}${b.rounds ? `Ngân sách tối đa ${b.rounds} vòng · ${fmt.tok(b.tokens)} token · ${b.tool_calls} công cụ.` : ''}</div></div></header>
      ${rfcChapter(r)}
      ${r.rounds.filter((rd) => rd.n > 0).map((rd) => html`<div class="jr-round"><div class="jr-round-h"><span class="jr-n">${rd.n}</span><b>Vòng ${rd.n}</b><span class="muted small">${rd.steps.filter((s) => s.to !== 'planner').map((s) => s.task || s.to).join(' · ') || 'chuẩn bị'}</span></div>
        <ol class="jr-steps">${rd.steps.filter((s) => s.to === 'planner').map(stepView)}${planView(rd)}${rd.steps.filter((s) => s.to !== 'planner').map(stepView)}${critView(rd)}${suffView(rd)}</ol></div>`)}
      ${r.stop && !r.verdict ? html`<div class="jr-out info">${icon('info', 15)}<div>Hub dừng: ${STOP_VN[r.stop.payload.reason] || r.stop.payload.reason}.</div></div>` : ''}${verdictView(r)}</section>`;
  })}`;
}

/* ---------- biểu đồ làn theo thời gian ---------- */
export function swimlane(model) {
  const steps = model.reqs.flatMap((r) => r.rounds.flatMap((x) => x.steps));
  if (!steps.length) return '';
  const lanes = [...new Set(steps.map((s) => s.to))].sort((a, b) => (a === 'planner' ? -1 : b === 'planner' ? 1 : a.localeCompare(b)));
  const t0 = model.events[0].ts_ns, t1 = Math.max(model.events[model.events.length - 1].ts_ns, t0 + 1e9), span = (t1 - t0) / 1e9;
  const W = 900, L = 96, H = 30, top = 22, plotW = W - L - 10, x = (ts) => L + ((ts - t0) / 1e9 / span) * plotW;
  const nice = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600].find((s) => span / s <= 8) || 3600;
  const ticks = []; for (let t = 0; t <= span; t += nice) ticks.push(t);
  const colorOf = (s) => (s.failure || (s.done && !s.done.payload.ok) ? 'var(--critical)' : s.to === 'planner' ? 'var(--series-7)' : s.to === 'verifier' ? 'var(--warning)' : s.to === 'rfc_analyst' ? 'var(--series-5)' : s.to === 'tester' ? 'var(--series-3)' : 'var(--series-1)');
  const bars = steps.map((s) => {
    const li = lanes.indexOf(s.to), a = x(s.msg.ts_ns), end = s.done ? s.done.ts_ns : t1, w = Math.max(3, x(end) - a), y = top + li * H + 5;
    const tip = `${agentName(s.to)} · ${s.task || 'lên kế hoạch'} · ${s.done ? fmt.ms(s.done.payload.duration_ms) : 'đang chạy'} · ${fmt.tok(stepTokens(s))} token${s.failure ? ' · HỎNG' : ''}`;
    const ticksT = s.tools.filter((_, i) => i % Math.ceil(s.tools.length / 40 || 1) === 0).map((t) => `<line x1="${x(t.ts_ns)}" x2="${x(t.ts_ns)}" y1="${y + 3}" y2="${y + H - 13}" stroke="#fff" stroke-opacity=".7" stroke-width="1"/>`).join('');
    const den = s.denied.map((t) => `<text x="${x(t.ts_ns)}" y="${y + H - 13}" font-size="11" fill="#fff" text-anchor="middle" font-weight="700">×</text>`).join('');
    return `<g class="sl-bar ${!s.done && !s.failure ? 'run' : ''}" data-seq="${s.llm ? s.llm.seq : s.msg.seq}" tabindex="0" role="button" aria-label="${esc(tip)}"><title>${esc(tip)}</title><rect x="${a}" y="${y}" width="${w}" height="${H - 12}" rx="5" fill="${colorOf(s)}"/>${ticksT}${den}</g>`;
  }).join('');
  const vlines = model.reqs.map((r) => r.verdict ? `<line x1="${x(r.verdict.ts_ns)}" x2="${x(r.verdict.ts_ns)}" y1="${top - 4}" y2="${top + lanes.length * H}" stroke="var(--good)" stroke-width="1.5" stroke-dasharray="3 3"/>` : '').join('');
  const svg = `<svg class="swim" viewBox="0 0 ${W} ${top + lanes.length * H + 6}" role="img" aria-label="Biểu đồ làn: mỗi hàng một agent, trục ngang là thời gian">
    ${ticks.map((t) => `<g><line x1="${L + (t / span) * plotW}" x2="${L + (t / span) * plotW}" y1="${top - 4}" y2="${top + lanes.length * H}" stroke="var(--grid)"/><text x="${L + (t / span) * plotW}" y="12" font-size="10.5" fill="var(--muted)" text-anchor="middle">${esc(fmt.sec(t))}</text></g>`).join('')}
    ${lanes.map((l, i) => `<g><line x1="0" x2="${W}" y1="${top + (i + 1) * H}" y2="${top + (i + 1) * H}" stroke="var(--grid)"/><text x="${L - 8}" y="${top + i * H + 20}" font-size="12" fill="var(--text-2)" text-anchor="end">${esc(agentName(l))}</text></g>`).join('')}
    ${vlines}${bars}</svg>`;
  return html`<div class="swim-wrap">${raw(svg)}</div><div class="legend-line"><span><i style="background:var(--series-5)"></i>RFC Analyst</span><span><i style="background:var(--series-7)"></i>Planner</span><span><i style="background:var(--series-3)"></i>Tester</span><span><i style="background:var(--series-1)"></i>Agent đọc mã</span><span><i style="background:var(--warning)"></i>Verifier</span><span><i style="background:var(--critical)"></i>hỏng</span><span>vạch trắng = lần gọi công cụ · × = bị chặn</span></div>`;
}

/* ---------- bài học & thẻ điểm agent ---------- */
export function agentCards(model) {
  const m = {};
  const A = (r) => (m[r] ||= { role: r, runs: 0, ok: 0, fail: 0, tokens: 0, ms: 0, tools: 0, denied: 0, retries: 0, evidence: 0, zero: 0, loaded: new Set(), offered: new Set() });
  model.reqs.forEach((r) => r.rounds.forEach((rd) => rd.steps.forEach((s) => {
    const a = A(s.to), d = s.done?.payload; if (!d && !s.failure) return;
    a.runs++; if (d?.ok && !s.failure) a.ok++; else a.fail++;
    a.tokens += d?.tokens || 0; a.ms += d?.duration_ms || 0; a.tools += s.tools.length; a.denied += s.denied.length; a.retries += s.retries.length + s.rejects.length;
    if (s.to !== 'planner') { const n = s.result?.payload.new_evidence || 0; a.evidence += n; if (d?.ok && !s.failure && n === 0 && s.task !== 'CRITIQUE') a.zero++; }
    (s.llm?.payload.skills_loaded || []).forEach((k) => a.loaded.add(k)); (s.llm?.payload.skills_offered || []).forEach((k) => a.offered.add(k));
  })));
  return Object.values(m).sort((a, b) => b.tokens - a.tokens);
}

export function lessons(model) {
  const out = [], cards = agentCards(model), steps = model.reqs.flatMap((r) => r.rounds.flatMap((x) => x.steps.map((s) => ({ s, r }))));
  const totalTok = cards.reduce((a, c) => a + c.tokens, 0);
  /* 1. agent hỏng */
  const fails = steps.filter(({ s }) => s.failure || (s.done && !s.done.payload.ok));
  const byF = {}; fails.forEach(({ s }) => { const k = s.to + '|' + (s.failure?.error || s.done?.payload.failure); (byF[k] ||= []).push(s); });
  Object.entries(byF).forEach(([k, list]) => {
    const [role, code] = k.split('|'), tok = list.reduce((a, s) => a + stepTokens(s), 0), usage = code === 'UsageLimitExceeded';
    out.push({ tone: 'bad', title: `${agentName(role)} hỏng ${list.length} lần: ${failText(code)}`, seqs: list.map((s) => s.llm?.seq || s.msg.seq),
      what: `Các lần này đã tiêu ${fmt.tok(tok)} token (${fmt.pct(tok, totalTok)} tổng) mà không trả được kết quả dùng được.`,
      learn: usage ? 'Nhiệm vụ quá rộng so với hạn mức mỗi lần chạy: AI cứ đọc thêm cho tới khi bị cắt giữa chừng. Mất toàn bộ công sức đã bỏ ra.' : 'Lỗi lặp lại cùng một kiểu thường là vấn đề thiết kế nhiệm vụ chứ không phải may rủi.',
      fix: usage ? 'Thu hẹp phạm vi nhiệm vụ (ít khía cạnh hơn, dùng gợi ý của Locator), hoặc cho agent trả kết quả từng phần sớm hơn, hoặc nâng hạn mức riêng cho agent này.' : 'Xem chi tiết lần chạy hỏng để tìm nguyên nhân gốc trước khi tăng số lần thử.' });
  });
  /* 2. lệnh bị chặn */
  const den = {}; steps.forEach(({ s }) => s.denied.forEach((t) => { const k = `${s.to}|${t.payload.tool}|${t.payload.reason || t.payload.code}`; (den[k] ||= []).push(t); }));
  Object.entries(den).forEach(([k, list]) => { const [role, tool, why] = k.split('|');
    out.push({ tone: 'warn', title: `${agentName(role)} bị chặn ${list.length} lần khi dùng ${tool}`, seqs: list.map((t) => t.seq),
      what: `Lý do: ${failText(why)}. Ví dụ lệnh bị chặn: ${short(JSON.stringify(list[0].payload.args || {}), 120)}.`,
      learn: 'Agent đoán cú pháp công cụ thay vì biết trước điều gì được phép. Cơ chế chặn hoạt động đúng, nhưng mỗi lần chặn là một lượt gọi LLM lãng phí.',
      fix: 'Đưa danh sách lệnh/cờ được phép kèm ví dụ vào skill hoặc mô tả công cụ của agent đó.' }); });
  /* 3. làm lại do cổng */
  const rt = steps.reduce((a, { s }) => a + s.retries.length + s.rejects.length, 0);
  if (rt) out.push({ tone: 'warn', title: `Cổng kiểm tra buộc AI làm lại ${rt} lần`, seqs: steps.flatMap(({ s }) => [...s.retries, ...s.rejects]).map((e) => e.seq).slice(0, 20), what: 'Đầu ra của AI sai định dạng hoặc vi phạm quy tắc nên bị trả về.', learn: 'Cổng tất định đang làm đúng việc bảo vệ: AI chỉ đề xuất, không tự ghi bằng chứng.', fix: 'Nếu cùng một lỗi lặp lại, bổ sung ví dụ đầu ra đúng vào lời nhắc vai trò.' });
  /* 4. vòng không sinh bằng chứng */
  const zero = steps.filter(({ s }) => s.to !== 'planner' && s.task !== 'CRITIQUE' && s.done?.payload.ok && !s.failure && s.result?.payload.new_evidence === 0);
  if (zero.length) { const tok = zero.reduce((a, { s }) => a + stepTokens(s), 0); out.push({ tone: 'warn', title: `${zero.length} nhiệm vụ chạy xong nhưng không thêm bằng chứng nào`, seqs: zero.map(({ s }) => s.llm?.seq || s.msg.seq), what: `Đã tốn ${fmt.tok(tok)} token (${fmt.pct(tok, totalTok)} tổng). Gồm: ${[...new Set(zero.map(({ s }) => `${agentName(s.to)}/${s.task}`))].join(', ')}.`, learn: 'Một nhiệm vụ "thành công" nhưng không tạo ra gì thì không đưa nhãn đến gần hơn. Đây là tín hiệu agent đọc mà không tìm ra, hoặc đầu ra bị cổng loại.', fix: 'Kiểm tra vì sao đầu ra không thành bằng chứng (cổng từ chối? không tìm thấy mã?) trước khi lặp lại cùng nhiệm vụ.' }); }
  /* 5. đã đủ từ sớm */
  model.reqs.forEach((r) => {
    const firstDec = r.rounds.find((x) => x.suff?.payload.decisive); if (!firstDec || !r.verdict) return;
    const later = r.rounds.filter((x) => x.n > firstDec.n), tok = later.flatMap((x) => x.steps).reduce((a, s) => a + stepTokens(s), 0);
    if (later.length) out.push({ tone: 'info', title: `${r.id}: đã đủ quyết định từ vòng ${firstDec.n}, nhưng chạy tới vòng ${r.rounds[r.rounds.length - 1].n}`, seqs: [firstDec.suff.seq], what: `${later.length} vòng sau tiêu ${fmt.tok(tok)} token (${fmt.pct(tok, totalTok)} tổng). Lý do Planner đưa ra: ${later.map((x) => RATIONALE_VN[x.plan?.payload.rationale_code] || x.plan?.payload.rationale_code || '–').map((t, i) => `vòng ${later[i].n}: ${t}`).join('; ')}.`, learn: 'Chạy thêm sau khi đã đủ quyết định thường là phản biện trước khi chốt TUÂN THỦ (chủ ý an toàn: chốt nhầm đắt hơn vài vòng) và việc xử lý các vấn đề phản biện nêu ra. Cần đối chiếu xem các vòng đó có từng đổi nhãn không.', fix: `Nếu nhãn cuối trùng nhãn tạm ở vòng ${firstDec.n}, đo xem phản biện có từng đổi nhãn không; nếu không bao giờ đổi, có thể giảm số vòng phản biện.` });
  });
  /* 6. Planner làm khác sổ tay */
  const dev = model.reqs.flatMap((r) => r.rounds.filter((x) => x.ctx && ((x.ctx.payload.adherence && x.ctx.payload.adherence !== 'followed') || x.plan?.payload.rationale_code === 'DEVIATE_PLAYBOOK')));
  if (dev.length) out.push({ tone: 'info', title: `Planner làm khác sổ tay ${dev.length} lần`, seqs: dev.map((x) => x.ctx.seq), what: dev.map((x) => `vòng ${x.n}: ${x.plan?.payload.rationale_code || ''}`).join(' · '), learn: 'Đây là chỗ AI có tự chủ: nó thấy sổ tay đã thất bại trước đó và đổi cách. Đáng đối chiếu xem lần đổi có cải thiện kết quả không.', fix: 'Nếu AI hay làm khác theo cùng một kiểu, đưa kiểu đó vào sổ tay thành quy tắc chính thức.' });
  /* 7. skill được đưa nhưng không nạp */
  cards.forEach((c) => { const un = [...c.offered].filter((k) => !c.loaded.has(k)); if (un.length && c.offered.size) out.push({ tone: 'info', title: `${agentName(c.role)} không nạp ${un.length}/${c.offered.size} skill được đưa`, seqs: [], what: `Chưa dùng: ${un.join(', ')}.`, learn: 'Skill chỉ nạp khi AI thấy cần. Skill luôn bị bỏ qua có thể mô tả mơ hồ, hoặc thật sự không cần cho yêu cầu này.', fix: 'Qua nhiều lần chạy, nếu một skill không bao giờ được nạp thì viết lại mô tả của nó hoặc gỡ đi.' }); });
  /* 7b. RFC Analyst so với RBS đã duyệt */
  model.reqs.forEach((r) => {
    const p = r.rfc.proposal?.payload; if (!p) return; const seq = r.rfc.proposal.seq;
    if (!p.produced) out.push({ tone: 'bad', title: `${r.id}: RFC Analyst không trả được đề xuất (${failText(p.failure)})`, seqs: [seq], what: 'Bước dịch câu RFC sang RBS hỏng nên chưa có gì để đối chiếu.', learn: 'Thường là agent gọi lặp công cụ cho tới hết ngân sách thay vì trả kết quả.', fix: 'Xem các bước của agent: nếu lặp cùng một lệnh thì thu hẹp công cụ hoặc nhắc rõ trong lời nhắc.' });
    else if (!p.accepted) out.push({ tone: 'bad', title: `${r.id}: đề xuất RBS của AI bị cổng từ chối`, seqs: [seq], what: (p.checks || []).filter((c) => !c.ok).map((c) => `${GATE_VN[c.name] || c.name}: ${c.detail || 'không đạt'}`).join(' · '), learn: 'Cổng tất định chặn đúng chỗ: RBS sai cú pháp, sai từ vựng hoặc trích câu không có thật sẽ không thành oracle.', fix: 'Bổ sung ví dụ đúng vào lời nhắc/skill của RFC Analyst, hoặc mở rộng từ vựng adapter nếu thiếu thật.' });
    else if (p.compare && !p.compare.agree) out.push({ tone: p.compare.semantic_agree ? 'info' : 'warn', title: `${r.id}: RBS của AI ${p.compare.semantic_agree ? 'khớp về ý nhưng khác lựa chọn kiểm thử' : 'lệch ý với RBS người duyệt'}`, seqs: [seq], what: `Trường khác: ${(p.compare.diffs || []).join(', ')}.`, learn: p.compare.semantic_agree ? 'Chỉ khác biến thể/thời hạn kiểm thử, không đổi nghĩa câu RFC.' : 'Hai bên hiểu câu RFC khác nhau: một trong hai sai. Đây là chỗ người duyệt cần xem.', fix: 'Đối chiếu từng trường ở chương "Phân tích RFC" và quyết định bên nào đúng.' });
    else if (p.compare) out.push({ tone: 'ok', title: `${r.id}: RBS do AI dịch lại khớp hoàn toàn bản người viết`, seqs: [seq], what: 'Mù với RBS viết tay mà vẫn ra cùng từng trường.', learn: 'Dấu hiệu tốt cho bước RFC → RBS, nhưng một ca khớp chưa chứng minh gì; cần đo trên nhiều câu (scripts/measure_rfc_analyst.py).', fix: '' });
  });
  /* 8. điểm tốt */
  const t3 = steps.filter(({ s }) => s.to === 'tester').reduce((a, { s }) => a + Object.values(s.t3).reduce((x, y) => x + y, 0), 0);
  if (t3 && model.reqs.some((r) => r.verdict)) out.push({ tone: 'ok', title: `Kết luận dựa trên ${t3} ca chạy thật, không chỉ lời AI`, seqs: [], what: 'Kết quả kiểm thử do thành phần tất định ghi lại; AI chỉ chọn ca và đọc mã.', learn: 'Ngay cả khi một agent đọc mã hỏng, nhãn vẫn đứng được nhờ hành vi quan sát thật.', fix: '' });
  const rank = { bad: 0, warn: 1, info: 2, ok: 3 };
  return out.sort((a, b) => rank[a.tone] - rank[b.tone]);
}

export function lessonsView(model, nodes = {}) {
  const L = lessons(model), cards = agentCards(model);
  if (!model.reqs.length) return html`<div class="empty-note">Bài học sẽ hiện khi lần chạy có đủ dữ liệu.</div>`;
  const tot = cards.reduce((a, c) => a + c.tokens, 0);
  return html`<div class="section"><h4>Thẻ điểm từng agent</h4><div class="table-wrap"><table class="tbl compact"><thead><tr><th>Agent</th><th>Lượt</th><th>Thành công</th><th>Token</th><th>Thời gian TB</th><th>Công cụ</th><th>Bị chặn</th><th>Bằng chứng</th><th>Token/BC</th></tr></thead><tbody>
    ${cards.map((c) => html`<tr><td title="${AGENT_VN[c.role]?.[1] || ''}"><b>${agentName(c.role)}</b></td><td>${c.runs}</td><td><span class="badge ${c.fail ? (c.ok ? 'warn' : 'bad') : 'ok'}">${c.ok}/${c.runs}</span></td>
      <td><div>${fmt.tok(c.tokens)}</div><div class="bar" style="width:70px"><i style="width:${tot ? (c.tokens / tot) * 100 : 0}%"></i></div></td><td>${fmt.ms(c.runs ? c.ms / c.runs : null)}</td><td>${c.tools}</td><td>${c.denied ? html`<span class="badge warn">${c.denied}</span>` : '0'}</td>
      <td>${c.role === 'planner' ? html`<span class="muted">–</span>` : c.evidence}</td><td>${c.role === 'planner' ? html`<span class="muted">–</span>` : c.evidence ? fmt.tok(Math.round(c.tokens / c.evidence)) : html`<span class="muted">chưa có</span>`}</td></tr>`)}</tbody></table></div></div>
    <div class="section"><h4>Điều rút ra từ lần chạy này (${L.length})</h4>${L.length ? L.map((x) => html`<article class="lesson ${x.tone}"><div class="lesson-h">${icon(x.tone === 'ok' ? 'check' : x.tone === 'info' ? 'info' : 'alert', 16)}<b>${x.title}</b></div>
      <p class="lesson-w">${x.what}</p><div class="lesson-g"><div><span class="k">Hiểu</span>${x.learn}</div>${x.fix ? html`<div><span class="k">Thử</span>${x.fix}</div>` : ''}</div>
      ${x.seqs?.length ? html`<div class="lesson-s">${x.seqs.slice(0, 6).map((q) => html`<button class="btn sm" data-seq="${q}">#${q}</button>`)}${x.seqs.length > 6 ? html`<span class="muted small">+${x.seqs.length - 6}</span>` : ''}</div>` : ''}</article>`) : html`<div class="empty-note">Không có điểm bất thường: mọi agent chạy sạch.</div>`}</div>
    <div class="muted small">Các nhận xét sinh tự động từ trace (không gọi LLM), nên chỉ nêu những gì đo được. Muốn cải thiện bền vững, ghi lại vào nhật ký cải tiến sau khi đối chiếu qua nhiều lần chạy.</div>`;
}

/* ---------- theo dõi một agent: suy nghĩ, gọi công cụ, kết quả, theo thứ tự thời gian ---------- */
const tryJson = (t) => { try { return JSON.stringify(JSON.parse(t), null, 1); } catch { return t; } };
const clip = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n) + '\n… (đã cắt, xem bản đầy đủ)' : s; };

/* Hội thoại LLM của một lượt chạy → danh sách bước. `t` là transcript chuẩn hoá do /events/<seq> trả. */
export function flowView(t) {
  if (!t) return '';
  const rets = Object.fromEntries(t.steps.filter((s) => s.type === 'tool_return').map((s) => [s.call_id, s]));
  const items = [];
  t.steps.forEach((s) => {
    if (s.type === 'tool_call') items.push(String(s.tool).startsWith('final_result') ? { final: s } : { call: s, ret: rets[s.call_id] });
    else if (['assistant', 'retry', 'thinking'].includes(s.type)) items.push({ s });
  });
  if (!items.length) return html`<div class="muted small">Lượt này không có bước trung gian.</div>`;
  return html`<ol class="ag-flow">${items.map((f) => {
    if (f.call) return html`<li class="ag-step tool"><span class="ag-ic">${icon('tool', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${f.call.tool}</b><span class="muted small">gọi công cụ</span></div>
      <pre class="code ag-args">${JSON.stringify(f.call.args, null, 1)}</pre>
      ${f.ret ? html`<details class="ag-ret"><summary>Kết quả trả về <span class="muted small">${short(String(f.ret.text).replace(/\s+/g, ' '), 110)}</span></summary><pre class="code">${clip(f.ret.text, 4000)}</pre></details>` : html`<div class="muted small">chưa có kết quả</div>`}</div></li>`;
    if (f.final) return html`<li class="ag-step final"><span class="ag-ic">${icon('check', 13)}</span><div class="ag-b"><div class="ag-t"><b>Trả kết quả cuối</b><span class="muted small">trước khi qua cổng kiểm chứng</span></div><details><summary class="muted small">Xem nội dung</summary><pre class="code">${clip(JSON.stringify(f.final.args, null, 1), 4000)}</pre></details></div></li>`;
    const k = f.s.type;
    return html`<li class="ag-step ${k}"><span class="ag-ic">${icon(k === 'retry' ? 'refresh' : k === 'thinking' ? 'cpu' : 'eye', 13)}</span><div class="ag-b"><div class="ag-t"><b>${k === 'retry' ? 'Cổng từ chối, AI phải làm lại' : k === 'thinking' ? 'Suy nghĩ' : 'AI nói'}</b></div>
      <div class="ag-text ${k === 'thinking' ? 'think' : ''}">${clip(f.s.text, 3000)}</div></div></li>`;
  })}</ol>`;
}

/* Luồng trực tiếp của một lượt đang chạy, theo kiểu Claude Code: lời AI nói, suy nghĩ, lời gọi công cụ hiện NGAY khi mô hình phát ra
   (sự kiện agent_step), rồi kết quả công cụ khớp vào đúng lời gọi khi nó xong (sự kiện tool_call). */
const normTool = (t) => String(t || '').replace(/__/g, '.');
const sameArgs = (a, b) => { try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; } };
function liveFlow(s, name, role, lastTs) {
  const pool = s.tools.slice(), take = (tool, args) => { const n = normTool(tool); let i = pool.findIndex((t) => normTool(t.payload.tool) === n && sameArgs(t.payload.args, args)); if (i < 0) i = pool.findIndex((t) => normTool(t.payload.tool) === n); return i < 0 ? null : pool.splice(i, 1)[0]; };
  const items = s.live.map((e) => {
    const p = e.payload;
    if (p.step === 'call' && String(p.tool).startsWith('final_result')) return html`<li class="ag-step final"><span class="ag-ic">${icon('check', 13)}</span><div class="ag-b"><div class="ag-t"><b>Đề xuất kết quả cuối</b><span class="muted small">chờ cổng kiểm chứng</span></div><details><summary class="muted small">Xem nội dung</summary><pre class="code">${clip(JSON.stringify(p.args, null, 1), 4000)}</pre></details></div></li>`;
    if (p.step === 'call') {
      const r = take(p.tool, p.args), out = r ? String(r.payload.output || '').replace(/^[[A-Z]+]s*tool=S+s*/, '') : null;
      return html`<li class="ag-step tool ${r ? '' : 'pending'}"><span class="ag-ic">${icon('tool', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${normTool(p.tool)}</b>${r ? '' : html`<span class="badge info pulse">${icon('activity', 12)}đang chạy</span>`}</div>
        <pre class="code ag-args">${JSON.stringify(p.args, null, 1)}</pre>
        ${r ? html`<details class="ag-ret" open><summary>Kết quả <span class="muted small">${short(out.replace(/s+/g, ' '), 100)}</span></summary><pre class="code">${clip(out, 3000)}</pre></details>` : ''}</div></li>`;
    }
    const k = p.step;
    return html`<li class="ag-step ${k === 'retry' ? 'retry' : k === 'thinking' ? 'thinking' : 'assistant'}"><span class="ag-ic">${icon(k === 'retry' ? 'refresh' : k === 'thinking' ? 'cpu' : 'eye', 13)}</span><div class="ag-b"><div class="ag-t"><b>${k === 'retry' ? 'Cổng từ chối, AI phải làm lại' : k === 'thinking' ? 'Suy nghĩ' : name}</b></div><div class="ag-text ${k === 'thinking' ? 'think' : ''}">${clip(p.text, 3000)}</div></div></li>`;
  });
  const rest = pool.map((t) => html`<li class="ag-step tool"><span class="ag-ic">${icon('tool', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${normTool(t.payload.tool)}</b></div><pre class="code ag-args">${JSON.stringify(t.payload.args || {}, null, 1)}</pre></div></li>`);
  const denied = s.denied.map((t) => html`<li class="ag-step bad"><span class="ag-ic">${icon('x', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${normTool(t.payload.tool)}</b><span class="badge bad">bị chặn: ${failText(t.payload.reason || t.payload.code)}</span></div><pre class="code ag-args">${JSON.stringify(t.payload.args || {}, null, 1)}</pre></div></li>`);
  return html`${items.length || rest.length || denied.length ? html`<ol class="ag-flow">${items}${rest}${denied}</ol>` : ''}${t3Bars(s)}${liveWait(s, name, role, lastTs, !s.live.length)}`;
}

/* Đang chờ: cho thấy thời gian đã chờ, đầu vào được giao, và giải thích vì sao chưa có sự kiện (trace chỉ ghi khi một bước xong). */
function liveWait(s, name, role, lastTs, explain = true) {
  const ns = s.msg.ts_ns, quiet = lastTs && lastTs > ns ? (lastTs - ns) / 1e9 : 0;
  const body = s.msg.payload.body || {};
  const why = role === 'tester' ? 'Tester chọn kịch bản, rồi bộ điều khiển chạy từng ca lên SUT thật. Mỗi ca xong mới ghi một sự kiện, nên có thể im lặng khá lâu.'
    : role === 'planner' ? 'Planner đang đọc bằng chứng và chờ mô hình trả kế hoạch.'
      : 'Agent đang chờ mô hình trả lời hoặc một công cụ chạy xong. Trace chỉ ghi khi một bước hoàn tất.';
  return html`<div class="ag-wait"><span class="spin"></span><div><b>${name} đang làm việc</b> · đã <span data-since="${ns}">${fmt.sec(Math.max(0, (Date.now() * 1e6 - ns) / 1e9))}</span>${s.tools.length ? ` · ${s.tools.length} công cụ đã gọi` : ' · chưa có công cụ nào hoàn tất'}
    ${explain ? html`<div class="small muted" style="font-weight:400">${why}</div>` : ''}</div></div>
    <details class="ag-ret" style="margin-top:6px"><summary>Đầu vào agent được giao</summary><pre class="code">${clip(JSON.stringify(body, null, 1), 3000)}</pre></details>`;
}

/* Ngăn theo dõi một agent. trs = { [seq llm]: transcript } đã nạp; tải dần nên có thể thiếu. */
export function agentInspector(model, role, trs = {}, opts = {}) {
  const info = AGENT_VN[role], name = agentName(role);
  const steps = model.reqs.flatMap((r) => r.rounds.flatMap((x) => x.steps)).filter((s) => s.to === role);
  const c = agentCards(model).find((x) => x.role === role);
  const models = [...new Set(steps.map((s) => s.llm?.payload.model).filter(Boolean))];
  const head = html`<div data-inspector="${role}" class="ag-head"><div class="muted">${info ? info[1] : 'thành phần của hệ thống'}.</div>
    <div class="ag-stats">${c ? html`<span><b>${c.runs}</b> lượt</span><span><b>${c.ok}/${c.runs}</b> thành công</span><span><b>${fmt.tok(c.tokens)}</b> token</span><span><b>${c.tools}</b> công cụ</span>${c.denied ? html`<span class="warn"><b>${c.denied}</b> bị chặn</span>` : ''}` : ''}${models.length ? html`<span class="mono">${models.join(', ')}</span>` : ''}</div>
    <div class="row"><button class="btn sm" data-filter-role="${role}">${icon('list', 13)}Lọc Hội thoại theo agent này</button><span class="muted small">${opts.live ? 'Công cụ hiện ngay khi gọi; suy nghĩ và hội thoại LLM hiện khi lượt chạy kết thúc.' : ''}</span></div></div>`;
  if (!steps.length) return html`${head}<div class="empty-note" style="margin-top:14px">${role === HUB || role === 'verdict' || role === 'evidence' ? 'Đây là thành phần tất định, không có lượt suy nghĩ của AI. Quyết định của nó nằm trong Hành trình và Dòng thời gian.' : 'Agent này chưa được giao việc trong lần chạy này.'}</div>`;
  const body = steps.map((s, i) => {
    const d = s.done?.payload, run = stepOpen(s), failed = s.failure || (d && !d.ok), isLast = i === steps.length - 1;
    const tr = s.llm ? trs[s.llm.seq] : null;
    const toolsLive = s.tools.length ? html`<ol class="ag-flow">${s.tools.map((t) => html`<li class="ag-step tool"><span class="ag-ic">${icon('tool', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${t.payload.tool}</b></div><pre class="code ag-args">${JSON.stringify(t.payload.args || {}, null, 1)}</pre>
      <details class="ag-ret"><summary>Kết quả <span class="muted small">${short(String(t.payload.output || '').replace(/^\[[A-Z]+\]\s*tool=\S+\s*/, '').replace(/\s+/g, ' '), 100)}</span></summary><pre class="code">${clip(t.payload.output, 3000)}</pre></details></div></li>${''}`)}${s.denied.map((t) => html`<li class="ag-step bad"><span class="ag-ic">${icon('x', 13)}</span><div class="ag-b"><div class="ag-t"><b class="mono">${t.payload.tool}</b><span class="badge bad">bị chặn: ${failText(t.payload.reason || t.payload.code)}</span></div><pre class="code ag-args">${JSON.stringify(t.payload.args || {}, null, 1)}</pre></div></li>`)}</ol>` : '';
    const lastTs = model.events[model.events.length - 1]?.ts_ns;
    const content = run ? liveFlow(s, name, role, lastTs)
      : tr ? flowView(tr) : s.llm ? html`<div class="ag-wait muted"><span class="spin"></span>Đang tải hội thoại LLM…</div>${toolsLive}` : html`${toolsLive || html`<div class="muted small">Không có bước nào được ghi.</div>`}`;
    const pr = s.params || {}, ps = [];
    if (pr.aspects?.length) ps.push(`khía cạnh: ${pr.aspects.map((a) => ASPECT_VN[a] || a).join(', ')}`);
    if (pr.missing_variants?.length) ps.push(`${pr.missing_variants.length} biến thể cần chạy`);
    if (pr.start_hints === 'locator') ps.push('bắt đầu từ gợi ý Locator');
    return html`<details class="ag-run ${failed ? 'bad' : run ? 'run' : ''}" ${run || isLast ? 'open' : ''}><summary><span class="ag-n">#${i + 1}</span><b>${s.task || (role === 'planner' ? 'Lập kế hoạch' : 'Nhiệm vụ')}</b><span class="muted small">${s.req} · vòng ${s.round}</span>
      <span class="grow"></span>${run ? html`<span class="badge info pulse">${icon('activity', 12)}đang chạy</span>` : failed ? html`<span class="badge bad">${icon('x', 12)}hỏng</span>` : html`<span class="badge ok">${icon('check', 12)}xong</span>`}
      <span class="muted small nowrap">${d ? `${fmt.ms(d.duration_ms)} · ${fmt.tok(d.tokens)} token` : ''}</span></summary>
      <div class="ag-body">${ps.length ? html`<div class="small muted" style="margin-bottom:8px">Được giao: ${ps.join(' · ')}</div>` : ''}${failed ? html`<div class="jr-out bad">${icon('x', 15)}<div><b>Không hoàn thành.</b> ${failText(s.failure?.error || d?.failure)}.${s.failure?.detail ? html`<div class="small muted">${short(s.failure.detail, 240)}</div>` : ''}</div></div>` : ''}${content}
        ${s.llm ? html`<div style="margin-top:8px"><button class="btn sm ghost" data-open="${s.llm.seq}">${icon('eye', 13)}Lời nhắc hệ thống, đầu vào và đầu ra đầy đủ</button></div>` : ''}</div></details>`;
  });
  return html`${head}<div class="ag-runs">${body}</div>`;
}

/* ---------- chương "Phân tích RFC": agent dịch lại câu RFC (mù với bản người viết), cổng kiểm, đối chiếu ---------- */
const RBS_FIELDS = [['sentence_id', 'Câu RFC'], ['modal', 'Modal'], ['rtype', 'Loại'], ['actor', 'Chủ thể'], ['state', 'Trạng thái'], ['trigger', 'Kích hoạt'], ['where', 'Điều kiện'], ['expect', 'Kỳ vọng'], ['within_ms', 'Trong (ms)'], ['forbid', 'Cấm'], ['accept_alternatives', 'Chấp nhận thay thế'], ['variants', 'Biến thể kiểm thử']];
const callTxt = (c) => `${c.name}${c.args?.length ? '(' + c.args.join(', ') + ')' : ''}`;
const variantTxt = (v) => `${v.kind}(${[v.field, v.value, v.k != null ? 'k=' + v.k : '', v.stratified ? 'phân tầng' : ''].filter((x) => x !== '' && x != null).join(', ')})`;
function rbsField(key, v) {
  if (v == null) return '–';
  switch (key) {
    case 'trigger': return callTxt(v);
    case 'where': return `${v.field} ${v.op} ${v.value}`;
    case 'expect': case 'forbid': case 'accept_alternatives': return v.length ? v.map(callTxt).join(' → ') : '–';
    case 'variants': return v.length ? v.map(variantTxt).join(', ') : '–';
    default: return String(v);
  }
}
const GATE_VN = { sentence_ids: 'Câu RFC có thật trong văn bản', parse: 'RBS đúng cú pháp', oracle: 'Dùng đúng từ vựng, biên dịch được oracle', rbs_sentence: 'Câu RBS trích có trong RFC', output: 'Agent trả được đề xuất' };

export function rfcChapter(r) {
  const rd0 = r.rounds.find((x) => x.n === 0), steps = rd0 ? rd0.steps : [];
  const st = r.rfc.start?.payload, pr = r.rfc.proposal?.payload, sk = r.rfc.skipped?.payload;
  if (!st && !pr && !sk && !steps.length) return '';
  const running = steps.some(stepOpen) && !pr;
  const cmp = pr?.compare, semantic = cmp ? cmp.semantic_agree ?? cmp.agree : null;
  const state = sk ? ['mute', 'bỏ qua', sk.reason === 'NO_RFC_TEXT' ? 'chưa có văn bản RFC trong inputs/rfc' : 'không tra được câu RFC của yêu cầu này']
    : running ? ['info', 'đang phân tích', 'AI đang đọc câu RFC và dịch sang RBS']
      : !pr ? ['mute', 'chưa có kết quả', '']
        : !pr.produced ? ['bad', 'agent không trả được đề xuất', failText(pr.failure)]
          : !pr.accepted ? ['bad', 'bị cổng từ chối', 'đề xuất không qua kiểm tra tất định']
            : cmp?.agree ? ['ok', 'khớp hoàn toàn với RBS đã duyệt', 'cùng từng trường, kể cả biến thể kiểm thử']
              : semantic ? ['ok', 'khớp về ý, khác lựa chọn kiểm thử', `khác: ${(cmp.diffs || []).join(', ')}`]
                : ['warn', 'lệch với RBS đã duyệt', `trường lệch: ${(cmp?.semantic_diffs || cmp?.diffs || []).join(', ')}`];
  const ic = { ok: 'check', bad: 'x', warn: 'alert', info: 'activity', mute: 'info' }[state[0]];
  const diff = new Set(cmp?.semantic_diffs || cmp?.diffs || []);
  const rows = cmp?.approved && cmp?.proposed ? RBS_FIELDS.map(([k, label]) => {
    const a = rbsField(k, cmp.approved[k]), b = rbsField(k, cmp.proposed[k]), bad = k !== 'sentence_id' && (cmp.diffs || []).includes(k);
    return html`<tr class="${bad ? 'row-bad' : ''}"><td class="muted">${label}</td><td class="mono">${b}</td><td class="mono">${a}</td><td>${bad ? html`<span class="badge ${diff.has(k) ? 'bad' : 'warn'}">${icon('x', 12)}${diff.has(k) ? 'lệch ý' : 'lựa chọn kiểm thử'}</span>` : html`<span class="badge ok">${icon('check', 12)}khớp</span>`}</td></tr>`;
  }) : '';
  return html`<div class="jr-round rfc-ch"><div class="jr-round-h"><span class="jr-n">${icon('book', 13)}</span><b>Phân tích RFC</b><span class="badge ${state[0]} ${running ? 'pulse' : ''}">${icon(ic, 12)}${state[1]}</span><span class="muted small">${state[2]}</span></div>
    <div class="jr-note info" style="margin-left:0">${icon('info', 14)}<div>AI <b>không được thấy RBS viết tay</b>; chỉ nhận câu RFC, các câu cùng mục, gói ngữ cảnh và từ vựng adapter. Kết quả chỉ để đối chiếu: kết luận bên dưới vẫn dựa trên RBS đã duyệt.</div></div>
    ${st ? html`<blockquote class="rfc-quote"><div class="small muted mono">${st.sentence_id} · ${(st.section_path || []).join(' › ')}</div>${st.sentence}</blockquote>` : ''}
    ${steps.length ? html`<ol class="jr-steps">${steps.map(stepView)}</ol>` : ''}
    ${pr?.produced ? html`<div class="rfc-grid"><div><h5 class="rfc-h">RBS do AI đề xuất</h5><pre class="code">${pr.non_behavioral ? `non_behavioral: ${pr.non_behavioral_reason || '(không nêu lý do)'}` : pr.rbs_text}</pre></div>
      <div><h5 class="rfc-h">Kiểm tra tất định (không dùng AI)</h5><ul class="rfc-checks">${(pr.checks || []).map((c) => html`<li class="${c.ok ? 'ok' : 'bad'}">${icon(c.ok ? 'check' : 'x', 13)}<div>${GATE_VN[c.name] || c.name}${c.detail ? html`<div class="small muted">${short(c.detail, 220)}</div>` : ''}</div></li>`)}</ul></div></div>` : ''}
    ${rows ? html`<h5 class="rfc-h">Đối chiếu từng trường với RBS đã duyệt</h5><div class="table-wrap"><table class="tbl compact"><thead><tr><th>Trường</th><th>AI đề xuất</th><th>Người đã duyệt</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
    ${cmp?.note ? html`<div class="small muted" style="margin-top:6px">${cmp.note}</div>` : ''}</div>`;
}
