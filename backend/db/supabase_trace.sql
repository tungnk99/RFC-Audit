-- Chạy một lần trong Supabase → SQL Editor.
-- Bản sao của bảng events trong trace.db. (run_id, seq) là khoá: gửi lại không tạo dòng trùng.
create table if not exists public.trace_events (
    run_id         text   not null,
    seq            bigint not null,
    ts_ns          bigint not null,
    kind           text   not null,
    role           text,
    requirement_id text,
    payload        jsonb  not null,
    created_at     timestamptz not null default now(),
    primary key (run_id, seq)
);

create index if not exists trace_events_kind_idx on public.trace_events (kind);
create index if not exists trace_events_req_idx  on public.trace_events (run_id, requirement_id);

-- Bật RLS và không tạo policy: khoá anon/public không đọc hay ghi được.
-- SUPABASE_KEY trong backend/.env phải là service_role (bỏ qua RLS), chỉ dùng phía server.
alter table public.trace_events enable row level security;
