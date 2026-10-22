/* Vòng phản hồi của con người: nháp nhận định (lưu cục bộ để không mất khi tải lại), cờ trên từng bằng chứng, đánh giá từng agent,
   và bảng nhận định gắn dưới kết luận. Nhận định gửi lên là bản ghi RIÊNG, chỉ ghi thêm; nhãn của hệ thống không bao giờ bị sửa (BR3). */
import { api, app, ensureWho, fmt, html, icon, on, toast, verdict, who } from './lib.js';

let META = null;
export async function reviewMeta() { return (META ||= await api('/api/reviews/meta')); }

const key = (run, req) => `rfcv-draft/${run}/${req}`;
const blank = () => ({ decision: '', label: '', reason: '', causes: [], flags: {}, agents: {} });
export function getDraft(run, req) { try { return { ...blank(), ...JSON.parse(localStorage.getItem(key(run, req)) || '{}') }; } catch { return blank(); } }
export function patchDraft(run, req, fn) { const d = getDraft(run, req); fn(d); localStorage.setItem(key(run, req), JSON.stringify(d)); return d; }
export function clearDraft(run, req) { localStorage.removeItem(key(run, req)); }
export const draftSize = (d) => Object.keys(d.flags).length + Object.keys(d.agents).length + (d.decision ? 1 : 0);

export const FLAGS = { key: ['Then chốt', 'ok'], wrong: ['Sai', 'bad'], irrelevant: ['Không liên quan', 'warn'] };
const DEC = { agree: ['Đồng ý', 'check', 'ok'], disagree: ['Không đồng ý', 'x', 'bad'], unsure: ['Chưa chắc', 'info', 'warn'] };
export const decBadge = (d) => { const [t, ic, c] = DEC[d] || [d, 'info', 'mute']; return html`<span class="badge ${c}">${icon(ic, 12)}${t}</span>`; };

/* Cờ trên một bằng chứng (bảng so sánh, thẻ chú thích trên mã, ngăn chi tiết): ba nút biểu tượng liền nhau, không bẻ dòng, chú giải khi rê chuột. */
const FLAG_ICON = { key: 'star', wrong: 'x', irrelevant: 'minus' };
export function flagMenu(run, req, eid, enabled = true) {
  const cur = getDraft(run, req).flags[eid]?.flag;
  if (!enabled && !cur) return '';
  return html`<span class="flagm" data-flagm role="group" aria-label="Gắn cờ bằng chứng">${Object.entries(FLAGS).map(([k, [t, c]]) => html`<button class="fl ${cur === k ? 'on ' + c : ''}" ${enabled ? '' : 'disabled'} data-flag="${eid}|${k}" data-run="${run}" data-req="${req}" data-tip="${t}" aria-label="${t}" aria-pressed="${String(cur === k)}">${icon(FLAG_ICON[k], 13)}</button>`)}</span>`;
}
/* Đánh giá một lượt trả lời của agent (tốt/kém). */
export function agentRate(run, req, role, msgId, enabled = true) {
  const id = `${role}|${msgId || ''}`, cur = getDraft(run, req).agents[id]?.rating;
  if (!enabled && !cur) return '';
  return html`<span class="rate"><span class="muted small">Đánh giá lượt này</span><span class="flagm labeled" role="group" aria-label="Đánh giá agent"><button class="fl ${cur === 'good' ? 'on ok' : ''}" ${enabled ? '' : 'disabled'} data-arate="${id}|good" data-run="${run}" data-req="${req}">${icon('check', 13)}Tốt</button><button class="fl ${cur === 'bad' ? 'on bad' : ''}" ${enabled ? '' : 'disabled'} data-arate="${id}|bad" data-run="${run}" data-req="${req}">${icon('x', 13)}Kém</button></span></span>`;
}
/* Gắn xử lý cho cờ/đánh giá agent trong một vùng; `after` được gọi để vẽ lại. */
export function wireReview(root, after) {
  on(root, 'click', '[data-flag]', (b, e) => {
    e.preventDefault(); e.stopPropagation();
    const [eid, flag] = b.dataset.flag.split('|'), { run, req } = b.dataset;
    patchDraft(run, req, (d) => { if (d.flags[eid]?.flag === flag) delete d.flags[eid]; else d.flags[eid] = { flag, note: d.flags[eid]?.note || '' }; });
    after();
  });
  on(root, 'click', '[data-arate]', (b, e) => {
    e.preventDefault(); e.stopPropagation();
    const [role, msg, rating] = b.dataset.arate.split('|'), { run, req } = b.dataset, id = `${role}|${msg}`;
    patchDraft(run, req, (d) => { if (d.agents[id]?.rating === rating) delete d.agents[id]; else d.agents[id] = { role, msg_id: msg || null, rating, note: '' }; });
    after();
  });
}

/* ---------- bảng nhận định gắn dưới kết luận ---------- */
export function reviewPanel(f, o) {
  const run = o.run, req = f.requirement_id, d = getDraft(run, req), meta = o.meta, mine = o.reviews.filter((r) => r.requirement_id === req);
  const can = o.canReview, label = f.label;
  const staged = [...Object.entries(d.flags).map(([eid, v]) => ({ t: 'flag', id: eid, ...v })), ...Object.entries(d.agents).map(([id, v]) => ({ t: 'agent', id, ...v }))];
  return html`<section class="review fsec" id="rv-${req}" data-req="${req}"><h4>⑤ Đánh giá của con người</h4>
    ${mine.length ? html`<div class="rv-list">${mine.map(reviewItem)}</div>` : html`<div class="muted small" style="margin-bottom:10px">Chưa ai duyệt kết luận này.</div>`}
    ${!can ? html`<div class="banner info">${icon('info', 16)}<div class="small">${app.readOnly ? 'Máy chủ đang ở chế độ chỉ đọc nên không ghi được nhận định.' : 'Lần chạy chưa kết thúc: duyệt sau khi có kết luận cuối.'}</div></div>` : html`
    <div class="rv-form"><div class="rv-q">Bạn có đồng ý với kết luận ${verdict(label, f.rule)} của hệ thống?</div>
      <div class="rv-dec" role="group" aria-label="Quyết định">${Object.entries(DEC).map(([k, [t, ic, c]]) => html`<button class="dec ${d.decision === k ? 'on ' + c : ''}" data-rv-dec="${k}">${icon(ic, 15)}${t}</button>`)}</div>
      ${d.decision === 'disagree' ? html`<div class="rv-row"><label for="rv-label-${req}">Theo bạn, nhãn đúng là</label><select id="rv-label-${req}" data-rv-label><option value="">— chọn —</option>${meta.labels.map((l) => html`<option value="${l}" ${d.label === l ? 'selected' : ''}>${l === 'COMPLIANT' ? 'TUÂN THỦ' : l === 'VIOLATION' ? 'VI PHẠM' : 'CẦN XEM XÉT'}</option>`)}</select></div>
        <div class="rv-row col"><label>Nguyên nhân (chọn một hoặc nhiều)</label><div class="rv-causes">${Object.entries(meta.causes).map(([k, t]) => html`<label class="cause ${d.causes.includes(k) ? 'on' : ''}"><input type="checkbox" data-rv-cause="${k}" ${d.causes.includes(k) ? 'checked' : ''}>${t}</label>`)}</div></div>` : ''}
      ${d.decision ? html`<div class="rv-row col"><label for="rv-reason-${req}">${d.decision === 'agree' ? 'Ghi chú (không bắt buộc)' : d.decision === 'unsure' ? 'Cần thêm gì để quyết định? (bắt buộc)' : 'Lý do (bắt buộc, tối thiểu 10 ký tự)'}</label><textarea id="rv-reason-${req}" data-rv-reason rows="3" maxlength="4000" placeholder="${d.decision === 'disagree' ? 'Vì sao kết luận của hệ thống chưa đúng? Dẫn dòng mã hoặc bằng chứng nếu có.' : ''}">${d.reason}</textarea></div>` : ''}
      ${staged.length ? html`<div class="rv-staged"><b class="small">Sẽ gửi kèm:</b>${staged.map((s) => (s.t === 'flag' ? html`<span class="chip ${FLAGS[s.flag][1]}">${icon('flag', 11)}${FLAGS[s.flag][0]} · <span class="mono">${s.id.slice(7, 17)}…</span></span>` : html`<span class="chip ${s.rating === 'good' ? 'ok' : 'bad'}">${icon('bot', 11)}${s.role} · ${s.rating === 'good' ? 'tốt' : 'kém'}</span>`))}</div>` : html`<div class="muted small">Mẹo: gắn cờ bằng chứng (⚑ Then chốt / Sai / Không liên quan) và đánh giá từng lượt agent ngay khi xem, chúng được gửi kèm nhận định.</div>`}
      ${o.error ? html`<div class="banner bad">${icon('alert', 16)}<div><ul>${o.error.map((e) => html`<li>${e}</li>`)}</ul></div></div>` : ''}
      <div class="row"><button class="btn primary" data-rv-submit ${d.decision ? '' : 'disabled'}>${icon('check', 14)}Gửi nhận định</button>${draftSize(d) ? html`<button class="btn ghost" data-rv-clear>Xoá nháp</button>` : ''}<span class="muted small">Ghi bằng tên <b>${who() || 'chưa khai'}</b>. Nhận định lưu riêng, chỉ ghi thêm, <b>không đổi nhãn</b> của hệ thống (BR3).</span></div></div>`}</section>`;
}
function reviewItem(r) {
  const diff = r.decision === 'disagree';
  return html`<div class="rv-item ${r.decision}"><div class="row" style="gap:8px"><span class="avatar">${(r.reviewer || '?').trim().slice(0, 1).toUpperCase()}</span><b>${r.reviewer}</b>${decBadge(r.decision)}${diff && r.label ? html`<span class="muted small">cho rằng</span>${verdict(r.label)}` : ''}<span class="muted small">${fmt.time(r.ts)}</span></div>
    ${r.reason ? html`<div class="rv-reason">${r.reason}</div>` : ''}
    <div>${(r.causes || []).map((c) => html`<span class="chip warn">${META?.causes?.[c] || c}</span>`)}${(r.evidence_flags || []).length ? html`<span class="chip">${r.evidence_flags.length} bằng chứng gắn cờ</span>` : ''}${(r.agent_feedback || []).length ? html`<span class="chip">${r.agent_feedback.length} đánh giá agent</span>` : ''}</div></div>`;
}

/* ---------- gắn xử lý biểu mẫu nhận định trong một vùng ---------- */
export function wireForm(root, getCtx, after) {
  const req = (el) => el.closest('.review').dataset.req;
  on(root, 'click', '[data-rv-dec]', (b) => { const { run } = getCtx(); patchDraft(run, req(b), (d) => { d.decision = b.dataset.rvDec; if (d.decision !== 'disagree') d.label = ''; }); after(); });
  on(root, 'change', '[data-rv-label]', (s) => { const { run } = getCtx(); patchDraft(run, req(s), (d) => { d.label = s.value; }); });
  on(root, 'change', '[data-rv-cause]', (c) => { const { run } = getCtx(); patchDraft(run, req(c), (d) => { const k = c.dataset.rvCause; d.causes = c.checked ? [...new Set([...d.causes, k])] : d.causes.filter((x) => x !== k); }); after(); });
  on(root, 'input', '[data-rv-reason]', (t) => { const { run } = getCtx(); patchDraft(run, req(t), (d) => { d.reason = t.value; }); });
  on(root, 'click', '[data-rv-clear]', (b) => { const { run } = getCtx(); if (confirm('Xoá nháp (nhận định, cờ và đánh giá agent chưa gửi)?')) { clearDraft(run, req(b)); after(); } });
  on(root, 'click', '[data-rv-submit]', async (b) => {
    const { run, setError, onSubmitted } = getCtx(), rid = req(b), d = getDraft(run, rid);
    const reviewer = await ensureWho(); if (!reviewer) return;
    b.disabled = true;
    const body = { requirement_id: rid, reviewer, decision: d.decision, label: d.decision === 'disagree' ? d.label || null : null, reason: d.reason, causes: d.decision === 'disagree' ? d.causes : [],
      evidence_flags: Object.entries(d.flags).map(([evidence_id, v]) => ({ evidence_id, flag: v.flag, note: v.note || '' })), agent_feedback: Object.values(d.agents).map((a) => ({ role: a.role, rating: a.rating, note: a.note || '', msg_id: a.msg_id })) };
    try { await api(`/api/runs/${run}/reviews`, { body }); clearDraft(run, rid); setError(rid, null); toast('Đã ghi nhận định. Cảm ơn bạn.', 'ok'); await onSubmitted(); }
    catch (e) { setError(rid, e.data?.errors || [e.message]); after(); }
  });
}
