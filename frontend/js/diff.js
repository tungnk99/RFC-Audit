/* So sánh hai văn bản theo dòng (LCS, bỏ phần đầu/cuối giống nhau trước để nhanh). Dùng cho bộ soạn thảo: xem đúng cái gì sắp đổi. */

export function diffLines(a, b) {
  let s = 0;
  while (s < a.length && s < b.length && a[s] === b[s]) s++;
  let ea = a.length, eb = b.length;
  while (ea > s && eb > s && a[ea - 1] === b[eb - 1]) { ea--; eb--; }
  const A = a.slice(s, ea), B = b.slice(s, eb), out = [];
  for (let i = 0; i < s; i++) out.push({ k: ' ', text: a[i] });
  if (A.length * B.length > 4_000_000) { A.forEach((t) => out.push({ k: '-', text: t })); B.forEach((t) => out.push({ k: '+', text: t })); }
  else {
    const n = A.length, m = B.length, L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) { if (A[i] === B[j]) { out.push({ k: ' ', text: A[i] }); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) out.push({ k: '-', text: A[i++] }); else out.push({ k: '+', text: B[j++] }); }
    while (i < n) out.push({ k: '-', text: A[i++] });
    while (j < m) out.push({ k: '+', text: B[j++] });
  }
  for (let i = ea; i < a.length; i++) out.push({ k: ' ', text: a[i] });
  return out;
}

/* Dạng hợp nhất có đánh số dòng và gập các đoạn không đổi dài (giữ `ctx` dòng ngữ cảnh). */
export function unified(oldText, newText, ctx = 3) {
  const d = diffLines(oldText.split('\n'), newText.split('\n')); let n1 = 0, n2 = 0;
  const rows = d.map((r) => ({ ...r, n1: r.k === '+' ? null : ++n1, n2: r.k === '-' ? null : ++n2 }));
  const keep = rows.map((r, i) => r.k !== ' ' || rows.slice(Math.max(0, i - ctx), i + ctx + 1).some((x) => x.k !== ' '));
  const out = []; let hidden = 0;
  rows.forEach((r, i) => { if (keep[i]) { if (hidden) { out.push({ k: 'gap', text: `⋯ ${hidden} dòng không đổi` }); hidden = 0; } out.push(r); } else hidden++; });
  if (hidden) out.push({ k: 'gap', text: `⋯ ${hidden} dòng không đổi` });
  return { rows: out, added: d.filter((r) => r.k === '+').length, removed: d.filter((r) => r.k === '-').length };
}
