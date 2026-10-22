import { $, $$, api, closeModal, empty, fmt, html, icon, mount, on, openModal, pageHead, toast } from '../lib.js';

const form = { adapters: {}, mode: 'demo', demo_case: 'faulty', code_root: '', code_index: '', executor: '', sut_launcher: '', budget: {} };
const PRESETS = { fast: ['Nhanh', { rounds: 4, tokens: 400000, seconds: 300, tool_calls: 40 }], std: ['Chuẩn', {}], deep: ['Sâu', { rounds: 12, tokens: 3000000, seconds: 3600, tool_calls: 300 }] };
const BUDGET = [['rounds', 'Số vòng tối đa', 8], ['tokens', 'Token tối đa', 1500000], ['seconds', 'Thời gian tối đa (giây)', 1800], ['tool_calls', 'Lời gọi công cụ tối đa', 120]];

export default async function (ctx) {
  const [cat, stats] = await Promise.all([api('/api/catalog'), api('/api/stats?days=0')]);
  if (!ctx.alive()) return;
  const adapters = cat.adapters.filter((a) => !a.error);
  if (!Object.keys(form.adapters).length && adapters.length === 1) form.adapters[adapters[0].id] = new Set(adapters[0].requirements.map((r) => r.id));
  for (const id of Object.keys(form.adapters)) if (!adapters.find((a) => a.id === id)) delete form.adapters[id];
  const caps = cat.capabilities;
  let pre = { state: 'wait', errors: [] }, timer;

  const body = () => html`
    ${pageHead('Chạy kiểm chứng', 'Chọn giao thức RFC và yêu cầu cần kiểm chứng, chọn nguồn mã, rồi để các agent điều tra. Mỗi giao thức là một lần chạy riêng, xếp hàng chạy lần lượt.')}
    <div class="new-layout"><div>
      <section class="card"><div class="step-title"><span class="n">1</span><h2>Giao thức RFC và yêu cầu</h2></div>
        ${adapters.length ? adapters.map((a) => proto(a)) : empty('Không tìm thấy adapter nào', 'Thêm adapter vào thư mục adapters/ rồi tải lại.')}</section>
      <section class="card"><div class="step-title"><span class="n">2</span><h2>Nguồn mã và chế độ chạy</h2></div>
        <label class="opt ${form.mode === 'demo' ? 'on' : ''}"><input type="radio" name="mode" value="demo" ${form.mode === 'demo' ? 'checked' : ''}>
          <div class="grow"><b>Demo mô phỏng</b> <span class="badge warn">${icon('alert', 12)}không phải kết quả thực nghiệm</span>
            <div class="hint">Các agent (LLM thật) làm việc với SUT, bộ kiểm thử và mã nguồn GIẢ trong bộ nhớ. Dùng để xem cơ chế phối hợp, không cho biết độ chính xác trên mã thật. Chỉ áp dụng cho giao thức TLS 1.3.</div>
            ${form.mode === 'demo' ? html`<div class="field" style="margin-top:12px;max-width:420px"><label for="demo-case">Kịch bản SUT giả</label><select id="demo-case">${caps.demo_cases.map((c) => html`<option value="${c.name}" ${form.demo_case === c.name ? 'selected' : ''}>${c.label}</option>`)}</select></div>` : ''}</div></label>
        <label class="opt ${form.mode === 'real' ? 'on' : ''}"><input type="radio" name="mode" value="real" ${form.mode === 'real' ? 'checked' : ''}>
          <div class="grow"><b>Chạy trên mã nguồn thật</b>
            <div class="hint">Chọn kho mã của bản triển khai (đúng commit), chỉ mục mã, bộ chạy lệnh và bộ chạy SUT.</div>
            ${form.mode === 'real' ? realFields(caps) : ''}</div></label>
      </section>
      <section class="card"><div class="card-head"><div class="step-title" style="margin:0"><span class="n">3</span><h2>Ngân sách mỗi yêu cầu</h2></div>
        <div class="seg">${Object.entries(PRESETS).map(([k, [l]]) => html`<button data-preset="${k}">${l}</button>`)}</div></div>
        <div class="grid g4">${BUDGET.map(([k, l, d]) => html`<div class="field"><label for="b-${k}">${l}</label><input id="b-${k}" type="number" data-budget="${k}" placeholder="${fmt.int(d)}" value="${form.budget[k] ?? ''}"></div>`)}</div>
        <div class="hint" style="margin-top:8px">Để trống = mặc định. Hết ngân sách trước khi đủ bằng chứng thì yêu cầu dừng với nhãn cần xem xét, không kết luận bừa.</div></section>
    </div>
    <aside class="sticky">${summary()}</aside></div>`;

  const proto = (a) => { const on = !!form.adapters[a.id]; const picked = form.adapters[a.id] || new Set(); return html`
    <div class="proto ${on ? 'on' : ''}"><label class="proto-head"><input type="checkbox" data-adapter="${a.id}" ${on ? 'checked' : ''}>
      <div class="grow"><b style="font-size:15px">${a.id}</b> <span class="muted small">v${a.version} · ${a.domain}</span>
        <div style="margin-top:4px">${a.specs.map((s) => html`<span class="chip ${s.role === 'primary' ? 'accent' : ''}" title="Mục xét: ${s.sections.join(', ')}">${s.doc}${s.role === 'primary' ? '' : ' · tham chiếu'}${s.xml_available ? '' : html`<span class="ic warn-dot" title="Chưa có tệp RFCXML trong inputs/rfc: agent sẽ chỉ thấy RBS, không thấy câu RFC gốc">${icon('alert', 11)}</span>`}</span>`)}</div>
        <div class="muted small" style="margin-top:2px">${a.requirements.length} yêu cầu đã duyệt · SUT ${a.sut.repo.split('/').pop()} · thành phần: ${a.components.join(', ')}</div></div></label>
      ${on ? html`<div class="reqs"><div class="row small muted" style="margin-bottom:4px"><span>Yêu cầu (RBS)</span><a href="#" data-all="${a.id}">chọn hết</a><a href="#" data-none="${a.id}">bỏ hết</a></div>
        ${a.requirements.length ? a.requirements.map((r) => html`<div class="req"><input type="checkbox" data-req="${a.id}|${r.id}" ${picked.has(r.id) ? 'checked' : ''} aria-label="${r.id}">
          <details><summary><b>${r.id}</b> <span class="chip">${r.modal} · loại ${r.rtype}</span> <span class="muted small">${r.source}</span></summary><pre class="code" style="margin-top:8px">${r.text}</pre></details></div>`) : html`<div class="muted">Adapter chưa có yêu cầu đã duyệt.</div>`}</div>` : ''}</div>`; };

  const realFields = (caps) => html`<div class="grid g2" style="margin-top:12px">
    <div class="field" style="grid-column:1/-1"><label for="code-root">Thư mục mã nguồn (phía máy chủ)</label><div class="row" style="flex-wrap:nowrap"><input id="code-root" type="text" class="grow" value="${form.code_root}" placeholder="vd. C:\\src\\wolfssl"><button class="btn" id="browse" type="button">${icon('folder', 15)}Duyệt…</button></div></div>
    ${[['code-index', 'Chỉ mục mã', caps.code_indexes, 'code_index'], ['executor', 'Bộ chạy lệnh (sandbox)', caps.executors, 'executor']].map(([id, l, list, key]) => html`<div class="field"><label for="${id}">${l}</label><select id="${id}">${opts(list, form[key])}</select><span class="hint">${(list.find((x) => x.name === form[key]) || {}).note || ''}</span></div>`)}
    <div class="field"><label for="sut-launcher">Bộ chạy SUT</label><select id="sut-launcher">${opts(caps.sut_launchers, form.sut_launcher)}</select><span class="hint">${caps.sut_launchers.length ? '' : 'Chưa có bộ chạy SUT nào được cài đặt (mốc G1): chế độ này chưa chạy được.'}</span></div></div>`;
  const opts = (list, cur) => html`<option value="">— chọn —</option>${list.map((c) => html`<option value="${c.name}" ${cur === c.name ? 'selected' : ''} ${c.available ? '' : 'disabled'}>${c.name}${c.available ? '' : ' (không khả dụng)'}</option>`)}`;

  const counts = () => { const ids = Object.keys(form.adapters); return { protos: ids.length, reqs: ids.reduce((n, id) => n + (form.adapters[id].size || (adapters.find((a) => a.id === id)?.requirements.length ?? 0)), 0) }; };
  const summary = () => {
    const c = counts(); const t = stats.totals; const basis = t.requirements;
    const estTok = (basis ? t.tokens_per_requirement : 170000) * c.reqs, estSec = (basis ? t.seconds_per_requirement : 25) * c.reqs;
    const ok = pre.state === 'ok';
    return html`<section class="card"><h3 style="margin-bottom:10px">Tóm tắt</h3>
      <div class="sum-row"><span class="muted">Giao thức</span><b>${c.protos}</b></div><div class="sum-row"><span class="muted">Yêu cầu</span><b>${c.reqs}</b></div>
      <div class="sum-row"><span class="muted">Chế độ</span><b>${form.mode === 'demo' ? 'Demo mô phỏng' : 'Mã thật'}</b></div>
      <div class="sum-row"><span class="muted">Ước tính token</span><b>${c.reqs ? '~' + fmt.tok(estTok) : '–'}</b></div><div class="sum-row"><span class="muted">Ước tính thời gian</span><b>${c.reqs ? '~' + fmt.sec(estSec) : '–'}</b></div>
      <div class="hint">${basis ? `Dựa trên ${basis} yêu cầu đã chạy.` : 'Chưa có dữ liệu chạy trước; dùng số mặc định thận trọng.'} Chế độ demo gọi LLM thật, có tốn token.</div>
      <h3 style="margin:16px 0 8px">Kiểm tra trước khi chạy</h3>
      <ul class="checks">${pre.state === 'wait' ? html`<li class="wait">${icon('clock', 15)}Đang kiểm tra…</li>` : pre.state === 'ok' ? html`<li class="ok">${icon('check', 15)}Mọi điều kiện đã đủ</li>` : pre.errors.map((e) => html`<li class="bad">${icon('x', 15)}<span>${e}</span></li>`)}</ul>
      <button class="btn primary" id="start" style="width:100%;justify-content:center;margin-top:16px" ${ok ? '' : 'disabled'}>${icon('play', 15)}Bắt đầu kiểm chứng</button></section>`;
  };

  const request = () => ({ adapters: Object.entries(form.adapters).map(([id, reqs]) => ({ id, requirements: [...reqs] })), mode: form.mode, demo_case: form.demo_case, code_root: form.code_root, code_index: form.code_index, executor: form.executor, sut_launcher: form.sut_launcher, budget: form.budget });
  const validate = () => {
    clearTimeout(timer); pre = { state: 'wait', errors: [] }; refreshSummary();
    timer = setTimeout(async () => {
      try { const r = await api('/api/runs/validate', { body: request() }); pre = r.ok ? { state: 'ok', errors: [] } : { state: 'bad', errors: r.errors }; }
      catch (e) { pre = { state: 'bad', errors: e.data?.errors || [e.message] }; }
      if (ctx.alive()) refreshSummary();
    }, 250);
  };
  const refreshSummary = () => { const a = $('aside.sticky'); if (a) mount(a, summary()); };
  const redraw = () => { mount(ctx.el, body()); validate(); };

  on(ctx.el, 'change', '[data-adapter]', (el) => { const a = adapters.find((x) => x.id === el.dataset.adapter); if (el.checked) form.adapters[a.id] = new Set(a.requirements.map((r) => r.id)); else delete form.adapters[a.id]; redraw(); });
  on(ctx.el, 'change', '[data-req]', (el) => { const [a, r] = el.dataset.req.split('|'); el.checked ? form.adapters[a].add(r) : form.adapters[a].delete(r); validate(); });
  on(ctx.el, 'click', '[data-all]', (el, e) => { e.preventDefault(); const a = adapters.find((x) => x.id === el.dataset.all); form.adapters[a.id] = new Set(a.requirements.map((r) => r.id)); redraw(); });
  on(ctx.el, 'click', '[data-none]', (el, e) => { e.preventDefault(); form.adapters[el.dataset.none] = new Set(); redraw(); });
  on(ctx.el, 'change', '[name=mode]', (el) => { form.mode = el.value; redraw(); });
  on(ctx.el, 'change', '#demo-case', (el) => { form.demo_case = el.value; });
  on(ctx.el, 'input', '#code-root', (el) => { form.code_root = el.value; validate(); });
  on(ctx.el, 'change', '#code-index', (el) => { form.code_index = el.value; redraw(); });
  on(ctx.el, 'change', '#executor', (el) => { form.executor = el.value; redraw(); });
  on(ctx.el, 'change', '#sut-launcher', (el) => { form.sut_launcher = el.value; redraw(); });
  on(ctx.el, 'input', '[data-budget]', (el) => { el.value === '' ? delete form.budget[el.dataset.budget] : (form.budget[el.dataset.budget] = Number(el.value)); validate(); });
  on(ctx.el, 'click', '[data-preset]', (el) => { form.budget = { ...PRESETS[el.dataset.preset][1] }; redraw(); });
  on(ctx.el, 'click', '#browse', () => browse(form.code_root, (p) => { form.code_root = p; redraw(); }));
  on(ctx.el, 'click', '#start', async (btn) => {
    btn.disabled = true;
    try { const res = await api('/api/runs', { body: request() }); toast(`Đã xếp hàng ${res.runs.length} lần chạy`, 'ok'); location.hash = res.runs.length === 1 ? `#/runs/${res.runs[0].run_id}` : '#/runs'; }
    catch (e) { pre = { state: 'bad', errors: e.data?.errors || [e.message] }; refreshSummary(); }
  });
  ctx.onLeave(() => clearTimeout(timer));
  redraw();
}

async function browse(start, onPick) {
  const load = async (path) => {
    let res; try { res = await api('/api/fs?path=' + encodeURIComponent(path || '')); } catch (e) { res = { path: null, dirs: [], error: e.message }; }
    const sep = (res.path || '').includes('\\') ? '\\' : '/';
    const m = openModal(html`<div class="mh"><h3>Chọn thư mục mã nguồn</h3><div class="mono muted small">${res.path || 'Các thư mục máy chủ cho phép'}</div>${res.is_repo ? html`<span class="badge ok">${icon('git', 12)}kho git</span>` : ''}${res.error ? html`<div class="banner bad" style="margin-top:8px">${res.error}</div>` : ''}</div>
      <div class="mb">${res.parent ? html`<div class="cmdk-item" data-p="${res.parent}">${icon('chevron', 14)}.. (lên một cấp)</div>` : res.path ? html`<div class="cmdk-item" data-p="">${icon('chevron', 14)}Về danh sách gốc</div>` : ''}
        ${res.dirs.map((d) => html`<div class="cmdk-item" data-p="${res.path ? res.path + sep + d : d}">${icon('folder', 15)}${d}</div>`)}</div>
      <div class="mf"><button class="btn" id="m-cancel">Đóng</button><button class="btn primary" id="m-pick" ${res.path ? '' : 'disabled'}>Chọn thư mục này</button></div>`);
    $$('[data-p]', m).forEach((el) => (el.onclick = () => load(el.dataset.p)));
    $('#m-cancel', m).onclick = closeModal; $('#m-pick', m).onclick = () => { closeModal(); onPick(res.path); };
  };
  load(start);
}
