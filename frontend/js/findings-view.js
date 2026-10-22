/* Trình bày phân tích kết luận: vì sao nhãn như vậy, vi phạm (hoặc tuân thủ) ở đâu trong mã, kiểm thử quan sát khác kỳ vọng thế nào.
   Dữ liệu từ /api/runs/<id>/findings, tất định từ bằng chứng đã ghi. Đoạn mã là dữ liệu không tin cậy nên luôn đi qua html`` (tự thoát). */
import { fmt, html, icon, raw, verdict } from './lib.js';
import { flagMenu, reviewPanel } from './review.js';

const ASPECT = { CONDITION: 'Điều kiện kích hoạt', THRESHOLD: 'Ngưỡng', REACTION: 'Phản ứng', ORDER_STATE: 'Thứ tự / trạng thái', EFFECT: 'Tác động' };
const paramText = (c) => Object.entries(c.params || {}).map(([k, v]) => `${k} = ${v}`).join(', ');
const firstNum = (c) => Object.values(c.params || {}).find((v) => typeof v === 'number');

/* Gộp các ca có cùng kỳ vọng + quan sát + kết quả thành một dòng ("record.length = 16641 … 65535 · 12 ca"). */
function groupCases(cases) {
  const g = new Map();
  for (const c of cases) {
    const k = [c.side, c.expected_text, c.observed_text, c.outcome].join('|');
    const x = g.get(k) || { ...c, n: 0, nums: [], ids: [] };
    x.n++; const v = firstNum(c); if (v != null) x.nums.push(v); x.ids.push(c.evidence_id); g.set(k, x);
  }
  return [...g.values()].sort((a, b) => (a.outcome !== 'FAIL') - (b.outcome !== 'FAIL') || b.n - a.n);
}
const inputText = (g) => {
  const key = Object.keys(g.params || {})[0];
  if (!key) return g.variant;
  if (g.nums.length > 1) return `${key} = ${Math.min(...g.nums)} … ${Math.max(...g.nums)}`;
  return paramText(g);
};

export function headline(f) {
  const cases = f.tests.cases, fails = cases.filter((c) => c.outcome === 'FAIL'), pass = cases.filter((c) => c.outcome === 'PASS').length;
  const loc = f.location, bad = loc?.aspects.find((a) => a.value === 'MISMATCH');
  const where = loc ? ` Mã tại ${loc.file}:${loc.line_start}–${loc.line_end}${loc.symbol ? ` (${loc.symbol})` : ''}${bad?.observed ? `: ${bad.observed}` : ''}.` : '';
  if (f.label === 'VIOLATION') {
    const first = fails.find((c) => c.decisive) || fails[0], nums = fails.map(firstNum).filter((v) => v != null);
    const span = nums.length > 1 ? ` (${Object.keys(first?.params || {})[0]} = ${Math.min(...nums)} … ${Math.max(...nums)})` : '';
    return { tone: 'bad', text: `Vi phạm: ${first ? first.why : 'có ca kiểm thử thất bại hợp lệ'}. Xảy ra ở ${fails.length} ca${span}.${where}` };
  }
  if (f.label === 'COMPLIANT') return { tone: 'ok', text: `Tuân thủ: ${pass}/${cases.length} ca kiểm thử PASS${f.coverage.linked ? ', kết quả được liên kết độ phủ với mã' : ''}.${loc ? ` Mã tại ${loc.file}:${loc.line_start}–${loc.line_end}${loc.symbol ? ` (${loc.symbol})` : ''} khớp đặc tả.` : ''}` };
  return { tone: 'warn', text: `Chưa kết luận được: ${f.rule_text || 'cần người xem xét'}` };
}

const sideName = (s) => (s === 'trigger' ? 'Đầu vào kích hoạt (phải bị từ chối)' : 'Đầu vào hợp lệ (không được phản ứng)');

function requirement(f) {
  const r = f.rbs || {};
  return html`<div class="fsec"><h4>① Yêu cầu của đặc tả</h4><div class="req-grid">
    <div><span class="k">Nguồn</span><span>${r.source || '–'} ${f.modal ? html`<span class="chip accent">${f.modal}</span>` : ''}</span></div>
    ${r.state ? html`<div><span class="k">Trạng thái ban đầu</span><span>${r.state}</span></div>` : ''}
    <div><span class="k">Khi</span><code>${r.trigger || '–'}</code></div><div><span class="k">Phải</span><code>${r.expect || '–'}</code></div>
    ${r.forbid ? html`<div><span class="k">Cấm</span><code>${r.forbid}</code></div>` : ''}</div></div>`;
}

function comparison(f, o) {
  const groups = groupCases(f.tests.cases);
  if (!groups.length) return '';
  return html`<div class="fsec"><h4>② Kỳ vọng so với thực tế (kiểm thử hộp đen)</h4><div class="table-wrap"><table class="tbl cmp"><thead><tr><th>Đầu vào</th><th>Kỳ vọng (RFC)</th><th>Thực tế (SUT)</th><th>Kết quả</th></tr></thead><tbody>
    ${groups.map((g) => html`<tr class="click ${g.outcome === 'FAIL' ? 'row-bad' : ''}" data-ev="${g.ids[0]}"><td><div class="mono small">${inputText(g)}</div><div class="muted small">${g.n} ca · ${g.side === 'trigger' ? 'vượt ngưỡng' : 'hợp lệ'}</div></td>
      <td><code>${g.expected_text}</code></td><td><code class="${g.outcome === 'FAIL' ? 'diff' : ''}">${g.observed_text}</code>${g.why ? html`<div class="why">${icon('alert', 12)}${g.why}</div>` : ''}</td>
      <td>${g.outcome === 'PASS' ? html`<span class="badge ok">${icon('check', 12)}PASS</span>` : g.outcome === 'FAIL' ? html`<span class="badge bad">${icon('x', 12)}FAIL</span>` : html`<span class="badge warn">${g.outcome}</span>`}${o ? html`<div style="margin-top:6px">${flagMenu(o.run, f.requirement_id, g.ids[0], o.canReview)}</div>` : ''}</td></tr>`)}</tbody></table></div>
    <div class="hint">Bấm một dòng để xem bằng chứng gốc. Mỗi ca được chạy lại và đối chiếu với các bản tham chiếu độc lập.</div></div>`;
}

function codeBlock(f) {
  const loc = f.location;
  if (!loc) return html`<div class="fsec"><h4>③ Vị trí trong mã nguồn</h4><div class="muted">Agent chưa định vị được đoạn mã thực hiện yêu cầu này (chưa có bằng chứng vị trí T1).</div></div>`;
  const r = f.rbs || {}, wantAlert = /send_alert\((\w+)\)/.exec(r.expect || '')?.[1], thr = /(\d+)/.exec(r.trigger || '')?.[1];
  const expectOf = (a) => (a.aspect === 'REACTION' && wantAlert ? `send_alert(${wantAlert})` : a.aspect === 'THRESHOLD' && thr ? thr : null);
  return html`<div class="fsec"><h4>③ Vị trí trong mã nguồn</h4>
    <div class="row" style="margin-bottom:10px"><span class="loc"><b class="mono">${loc.file}</b><span class="mono">:${loc.line_start}–${loc.line_end}</span></span>${loc.symbol ? html`<span class="chip accent mono">${loc.symbol}()</span>` : ''}${loc.check_kind ? html`<span class="chip">${loc.check_kind}</span>` : ''}<a href="#" class="btn sm" data-code="${loc.file}|${loc.line_start}">${icon('file', 13)}Mở tệp với bằng chứng</a>
      ${loc.call_path.length ? html`<span class="path">${loc.call_path.map((p, i) => html`${i ? html`<i>→</i>` : ''}<span class="mono">${p}</span>`)}</span>` : ''}</div>
    <div class="aspects">${loc.aspects.map((a) => html`<div class="aspect ${a.value === 'MISMATCH' ? 'bad' : 'ok'}"><div class="row" style="justify-content:space-between"><b>${ASPECT[a.aspect] || a.aspect}</b>${a.value === 'MISMATCH' ? html`<span class="badge bad">${icon('x', 12)}lệch</span>` : html`<span class="badge ok">${icon('check', 12)}khớp</span>`}</div>
      ${a.observed != null ? html`<div class="small"><span class="muted">Mã làm:</span> <code>${a.observed}</code></div>` : ''}${expectOf(a) ? html`<div class="small"><span class="muted">RFC đòi:</span> <code>${expectOf(a)}</code></div>` : ''}
      <div class="muted small">dòng ${a.lines[0] === a.lines[1] ? a.lines[0] : `${a.lines[0]}–${a.lines[1]}`}</div></div>`)}</div>
    ${loc.snippet.length ? html`<div class="codeview" role="region" aria-label="Đoạn mã">${loc.snippet.map((l) => html`<div class="cl ${l.flag || ''} ${l.inside ? '' : 'out'}"><span class="ln">${l.n}</span><span class="mk">${l.flag === 'mismatch' ? '✗' : l.flag === 'match' ? '✓' : ''}</span><code>${l.text}</code>${l.hit ? html`<span class="hit" title="Dòng này được thực thi khi kiểm thử kích hoạt (độ phủ)">${icon('zap', 12)}</span>` : ''}</div>`)}</div>
      <div class="legend-line"><span><b style="color:var(--critical-text)">✗</b> lệch kỳ vọng</span><span><b style="color:var(--good-text)">✓</b> khớp</span><span>${icon('zap', 12)} được thực thi khi kích hoạt</span><span class="muted">Mã là dữ liệu không tin cậy, chỉ hiển thị.</span></div>` : html`<div class="muted small">Không còn đoạn mã trong trace (agent đọc bằng công cụ khác).</div>`}
    <div class="cov ${f.coverage.linked ? 'ok' : ''}">${icon(f.coverage.linked ? 'check' : 'info', 14)}${f.coverage.linked ? `Độ phủ xác nhận khi kiểm thử kích hoạt, các dòng ${f.coverage.lines_hit.join(', ')} thật sự được thực thi: bằng chứng mã (T1) liên kết với kết quả kiểm thử (T3).` : 'Chưa liên kết độ phủ giữa mã và kiểm thử.'}</div></div>`;
}

function why(f) {
  const dec = f.tests.cases.filter((c) => c.decisive), rows = [];
  if (dec.length) {
    const stable = dec.every((c) => c.consistent !== false), envs = dec.every((c) => c.environments_consistent !== false), refs = dec.flatMap((c) => c.witness?.positive || []);
    rows.push([stable, `Kết quả ổn định: các ca quyết định được chạy lặp (tối đa ${Math.max(...dec.map((c) => c.runs || 1))} lần) cho kết quả giống nhau`]);
    rows.push([envs, 'Nhất quán giữa các môi trường chạy']);
    if (refs.length) rows.push([refs.every((w) => w.outcome === 'PASS'), `Nhân chứng độc lập: ${new Set(refs.map((w) => w.impl)).size} bản tham chiếu (${[...new Set(refs.map((w) => w.impl))].join(', ')}) đều PASS cùng kịch bản, nên lệch nằm ở SUT chứ không phải ở kịch bản`]);
  }
  rows.push([f.coverage.linked, f.coverage.linked ? 'Kết quả kiểm thử được liên kết với đoạn mã đã định vị' : 'Chưa liên kết kiểm thử với mã nguồn']);
  return html`<div class="fsec"><h4>④ Vì sao Verdict engine kết luận như vậy</h4><div class="why-rule"><b>Quy tắc ${f.rule}</b>: ${f.rule_text}</div>
    <ul class="checks">${rows.map(([ok, t]) => html`<li class="${ok ? 'ok' : 'wait'}">${icon(ok ? 'check' : 'info', 15)}<span>${t}</span></li>`)}</ul>
    <div class="hint">${f.decisive.length} bằng chứng quyết định trong tổng ${f.evidence_total}. Nhãn do bộ quy tắc cố định gán, không phải do agent; agent chỉ đề xuất bằng chứng.</div></div>`;
}

function counts(f) {
  const sides = Object.entries(f.tests.by_side);
  return html`<div class="side-counts">${sides.map(([s, c]) => { const tot = Object.values(c).reduce((a, b) => a + b, 0); return html`<div><div class="small muted">${sideName(s)}</div><div class="segbar" style="height:8px">${Object.entries(c).map(([o, n]) => html`<div class="seg-part" style="flex:${n};background:${o === 'PASS' ? 'var(--good)' : o === 'FAIL' ? 'var(--critical)' : 'var(--warning)'}" data-tip="${o}: ${n}"></div>`)}</div><div class="small">${Object.entries(c).map(([o, n]) => `${o} ${n}`).join(' · ')} <span class="muted">/ ${tot} ca</span></div></div>`; })}</div>`;
}

export function findingCard(f, o = null) {
  const h = headline(f);
  return html`<section class="finding"><div class="hero ${h.tone}"><div class="row" style="gap:12px"><b class="mono" style="font-size:16px">${f.requirement_id}</b>${verdict(f.label, f.rule)}${f.assurance ? html`<span class="chip">bảo đảm ${f.assurance}</span>` : ''}</div>
      <p class="headline">${h.text}</p>${f.tests.total ? counts(f) : ''}</div>
    ${requirement(f)}${comparison(f, o)}${codeBlock(f)}${why(f)}${o ? reviewPanel(f, o) : ''}</section>`;
}

/* Dòng tóm tắt gọn cho đầu trang. */
export function summaryLine(f, reviewState = 'pending') {
  const h = headline(f);
  const rs = { pending: ['chưa duyệt', 'mute'], agreed: ['người đã đồng ý', 'ok'], disputed: ['người không đồng ý', 'bad'], unsure: ['người chưa chắc', 'warn'] }[reviewState] || ['', 'mute'];
  return html`<div class="quick ${h.tone}"><div class="row" style="gap:10px">${verdict(f.label, f.rule)}<b class="mono">${f.requirement_id}</b></div><div class="grow">${h.text}<div style="margin-top:4px"><span class="badge ${rs[1]}">${icon('users', 12)}${rs[0]}</span></div></div><button class="btn sm" data-tab="summary">Xem phân tích ${icon('chevron', 13)}</button></div>`;
}
