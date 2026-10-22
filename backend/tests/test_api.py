"""Lớp API của giao diện web: danh mục, chuẩn hoá hội thoại LLM, chạy nền qua RunManager (LLM thay bằng kịch bản), luồng
SSE, và các ranh giới an toàn của máy chủ. Không gọi LLM thật."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from rfcv.api import catalog, runstore, transcript
from rfcv.api.runs import RunManager, RunSpec, scrub
from rfcv.api.server import build_app, load_model_keys
from rfcv.assembly import Providers, Runtime, RuntimeConfig
from test_assembly import ScriptedRunner, make_providers

KEY_ENV = "DEEPSEEK_API_KEY"
SECRET = "sk-test-secret-value-1234567890"


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, SECRET)


def make_manager(tmp_path: Path, runners: list[ScriptedRunner]) -> RunManager:
    def customize(spec: RunSpec, cfg: RuntimeConfig) -> Providers | None:
        runner = ScriptedRunner()
        runners.append(runner)
        return make_providers(runner)

    def on_built(rt: Runtime) -> None:
        runners[-1].gateway = rt.gateway

    return RunManager(ROOT, runs_dir=tmp_path / "runs", code_roots=[tmp_path], customize=customize, on_built=on_built)


def wait_done(m: RunManager, run_id: str, timeout: float = 30) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        rec = m.record(run_id)
        if rec and rec["status"] not in ("queued", "running"):
            return rec
        time.sleep(0.1)
    raise AssertionError(f"quá hạn: {m.record(run_id)}")


# ---- danh mục -----------------------------------------------------------------------------------------------------


def test_catalog_lists_protocols_requirements_and_agents(keyed: None) -> None:
    cat = catalog.build_catalog(ROOT, agents_root=ROOT / "agents", code_roots=[ROOT])
    tls = next(a for a in cat["adapters"] if a["id"] == "tls13")
    assert [r["id"] for r in tls["requirements"]] == ["TLS13-0042"]
    assert tls["requirements"][0]["rtype"] == "B" and tls["requirements"][0]["modal"] == "MUST"
    assert {s["doc"] for s in tls["specs"]} == {"RFC8446", "RFC9846"}
    names = {a["name"] for a in cat["agents"]}
    assert {"planner", "code_reader", "tester", "verifier"} <= names
    assert cat["models"]["models"]["deepseek-flash"]["key_set"] is True


def test_catalog_never_exposes_key_values(keyed: None) -> None:
    cat = catalog.build_catalog(ROOT, agents_root=ROOT / "agents", code_roots=[ROOT])
    assert SECRET not in json.dumps(cat)


def test_scrub_removes_key_values_from_error_text(keyed: None) -> None:
    assert SECRET not in scrub(f"401 bad key {SECRET}")


# ---- chuẩn hoá hội thoại LLM ----------------------------------------------------------------------------------------


MESSAGES: list[dict[str, Any]] = [
    {
        "kind": "request",
        "instructions": "skills: x",
        "parts": [
            {"part_kind": "system-prompt", "content": "Bạn là Code Reader"},
            {"part_kind": "user-prompt", "content": '{"task": "LOCATE"}'},
            {"part_kind": "instruction-baseline", "content": ""},
        ],
    },
    {
        "kind": "response",
        "parts": [
            {"part_kind": "tool-call", "tool_name": "code__read_range", "tool_call_id": "c1", "args": '{"start": 1}'}
        ],
    },
    {
        "kind": "request",
        "parts": [
            {"part_kind": "tool-return", "tool_name": "code__read_range", "tool_call_id": "c1", "content": "dòng mã"}
        ],
    },
    {
        "kind": "response",
        "parts": [
            {"part_kind": "tool-call", "tool_name": "final_result", "tool_call_id": "c2", "args": '{"file": "a.c"}'}
        ],
    },
]


def test_transcript_normalises_input_tools_and_final_output() -> None:
    t = transcript.transcript(MESSAGES)
    assert [s["type"] for s in t["steps"]] == [
        "instructions",
        "system",
        "input",
        "tool_call",
        "tool_return",
        "tool_call",
    ]
    assert t["steps"][3]["args"] == {"start": 1}
    assert t["tools_used"] == {"code__read_range": 1}
    assert t["output"] == {"file": "a.c"}


def test_slim_event_drops_transcript_and_truncates_tool_output() -> None:
    llm = {"seq": 1, "kind": "llm_run", "role": "planner", "payload": {"msg_id": "m1", "messages": MESSAGES}}
    slim = transcript.slim_event(llm)
    assert "messages" not in slim["payload"] and slim["payload"]["n_messages"] == len(MESSAGES)
    big = {"seq": 2, "kind": "tool_call", "role": "x", "payload": {"tool": "t", "args": {}, "output": "x" * 5000}}
    assert len(transcript.slim_event(big)["payload"]["output"]) == 800
    assert transcript.full_event(llm)["transcript"]["output"] == {"file": "a.c"}


# ---- chạy nền, luồng, an toàn -----------------------------------------------------------------------------------------


def test_parse_request_reports_every_problem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    m = make_manager(tmp_path, [])
    _, errors = m.parse_request({"mode": "real", "adapters": []})
    text = " ".join(errors)
    assert "chưa chọn giao thức" in text and KEY_ENV in text
    _, errors = m.parse_request({"mode": "real", "adapters": [{"id": "tls13"}], "code_root": str(tmp_path)})
    assert any("chưa chọn chỉ mục mã" in e for e in errors) and any("bộ chạy SUT" in e for e in errors)


def test_parse_request_rejects_code_root_outside_allowed_roots(keyed: None, tmp_path: Path) -> None:
    m = make_manager(tmp_path / "ok", [])
    (tmp_path / "ok").mkdir(exist_ok=True)
    _, errors = m.parse_request({"mode": "real", "adapters": [{"id": "tls13"}], "code_root": str(ROOT)})
    assert any("ngoài các thư mục máy chủ cho phép" in e for e in errors)


@pytest.fixture
def served(keyed: None, tmp_path: Path) -> Iterator[tuple[TestClient, RunManager]]:
    runners: list[ScriptedRunner] = []
    manager = make_manager(tmp_path, runners)
    with TestClient(build_app(ROOT, frontend=ROOT.parent / "frontend", manager=manager)) as client:
        yield client, manager


def call(
    client: TestClient, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    h = {"Content-Type": "application/json", **(headers or {})}
    r = client.request(method, path, content=json.dumps(body) if body is not None else None, headers=h)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.content)


def test_full_run_through_http_with_live_stream_and_detail(
    served: tuple[TestClient, RunManager],
) -> None:
    conn, manager = served
    status, res = call(
        conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13", "requirements": ["TLS13-0042"]}]}
    )
    assert status == 201, res
    run_id = res["runs"][0]["run_id"]
    rec = wait_done(manager, run_id)
    assert rec["status"] == "finished", rec
    assert [v["label"] for v in rec["verdicts"]] == ["VIOLATION"]

    status, detail = call(conn, "GET", f"/api/runs/{run_id}")
    assert status == 200 and detail["summary"]["requirements"][0]["label"] == "VIOLATION"
    assert detail["manifest"]["adapter"]["name"] == "tls13"

    status, ev = call(conn, "GET", f"/api/runs/{run_id}/events?after=0")
    kinds = [e["kind"] for e in ev["events"]]
    assert {"message", "role_run", "task_result", "verdict"} <= set(kinds)
    msg = next(e for e in ev["events"] if e["kind"] == "message" and e["role"] == "code_reader")
    assert msg["payload"]["body"]["task_type"] == "LOCATE" and msg["summary"]
    status, full = call(conn, "GET", f"/api/runs/{run_id}/events/{msg['seq']}")
    assert status == 200 and full["payload"]["to_role"] == "code_reader"

    status, evid = call(conn, "GET", f"/api/runs/{run_id}/evidence")
    assert {x["kind"] for x in evid["evidence"]} >= {"scenario_result", "location"}
    status, one = call(conn, "GET", f"/api/runs/{run_id}/evidence/{evid['evidence'][0]['evidence_id']}")
    assert status == 200 and one["record"]["payload"]["kind"]
    assert call(conn, "GET", f"/api/runs/{run_id}/verify")[1]["ok"] is True

    # SSE: lần chạy đã xong thì phát lại toàn bộ rồi kết thúc bằng sự kiện `end`
    resp = conn.get(f"/api/runs/{run_id}/stream?after=0")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    assert "event: trace" in text and "event: end" in text
    assert f'"last_seq": {ev["last_seq"]}' in text

    listed = call(conn, "GET", "/api/runs")[1]["runs"]
    assert [r["run_id"] for r in listed] == [run_id]
    assert runstore.has_trace(manager.runs_dir / run_id)
    assert (manager.runs_dir / run_id / "requirements" / "TLS13-0042.rbs").is_file()


def test_selecting_a_subset_of_requirements_stages_only_those(
    served: tuple[TestClient, RunManager],
) -> None:
    conn, manager = served
    status, res = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13", "requirements": []}]})
    assert status == 201
    rec = wait_done(manager, res["runs"][0]["run_id"])
    assert rec["status"] == "finished" and len(rec["verdicts"]) == 1


def test_server_boundaries(served: tuple[TestClient, RunManager], tmp_path: Path) -> None:
    conn, _ = served
    assert call(conn, "GET", "/api/health")[0] == 200
    assert call(conn, "GET", "/api/health", headers={"Host": "evil.example"})[0] in (400, 403)  # DNS rebinding
    assert call(conn, "POST", "/api/runs", {}, headers={"Content-Type": "text/plain"})[0] == 415
    assert call(conn, "GET", "/api/runs/..%2f..%2fetc")[0] == 404
    assert call(conn, "GET", "/api/runs/run-nope")[0] == 404
    assert call(conn, "GET", f"/api/fs?path={ROOT}")[0] == 403  # ngoài --code-root
    assert call(conn, "GET", f"/api/fs?path={tmp_path}")[0] == 200
    status, body = call(conn, "GET", "/..%2f..%2fbackend%2f.env")  # đi ra ngoài thư mục frontend không đọc được
    assert status == 200 and b"api_key" not in body.lower() and b"DEEPSEEK" not in body
    status, res = call(conn, "POST", "/api/runs", {"adapters": []})
    assert status == 422 and res["errors"]


def test_cancel_queued_run(keyed: None, tmp_path: Path) -> None:
    runners: list[ScriptedRunner] = []
    gate = threading.Event()
    inner = make_manager(tmp_path, runners)
    first_call = [True]

    def customize(spec: RunSpec, cfg: RuntimeConfig) -> Providers | None:
        if first_call.pop() if first_call else False:
            gate.wait(10)  # giữ lần chạy đầu ở trạng thái "đang chạy" để lần hai còn xếp hàng
        return inner._customize(spec, cfg)  # type: ignore[misc,reportPrivateUsage]

    m = RunManager(
        ROOT, runs_dir=tmp_path / "runs", code_roots=[tmp_path], customize=customize, on_built=inner._on_built
    )  # type: ignore[reportPrivateUsage]
    specs, errors = m.parse_request({"mode": "demo", "adapters": [{"id": "tls13"}]})
    assert not errors
    first, second = m.submit(specs)[0], m.submit(specs)[0]
    time.sleep(0.5)
    assert m.record(first["run_id"])["status"] == "running"  # type: ignore[index]
    assert m.record(second["run_id"])["status"] == "queued"  # type: ignore[index]
    assert m.cancel(second["run_id"]) is True
    gate.set()
    first_rec = wait_done(m, first["run_id"])
    assert first_rec["status"] == "finished", first_rec["error"]
    assert wait_done(m, second["run_id"])["status"] == "cancelled"
    assert m.cancel(second["run_id"]) is False


def test_load_model_keys_only_loads_declared_key_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        f'# c\n{KEY_ENV}="abc123456789"\nSUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY=zzz\n', encoding="utf-8"
    )
    import os

    assert load_model_keys(env, ROOT / "config" / "models.yaml") == [KEY_ENV]
    assert os.environ[KEY_ENV] == "abc123456789" and "SUPABASE_URL" not in os.environ


async def test_demo_providers_wire_into_the_runtime_without_llm(tmp_path: Path) -> None:
    """Chế độ demo: tên cài đặt giả khớp adapter (wolfssl/rustls/openssl) nên Test driver chạy được trọn luồng."""
    from rfcv.assembly import build_runtime
    from rfcv.eval.demo_providers import demo_providers
    from rfcv.evidence.verdict_engine import Label

    runner = ScriptedRunner()
    providers = demo_providers("faulty")
    providers = Providers(**{**providers.__dict__, "role_runner": runner})
    cfg = RuntimeConfig(
        adapter_dir=ROOT / "adapters" / "tls13",
        run_dir=tmp_path / "runs",
        skills_root=ROOT / "skills",
        run_id="run-demo",
    )
    rt = build_runtime(cfg, providers)
    runner.gateway = rt.gateway
    try:
        verdicts = await rt.run_all(ROOT / "adapters" / "tls13" / "examples")
    finally:
        rt.close()
    assert [v.label for v in verdicts] == [Label.VIOLATION]


# ---- API cho các tab quản lý ------------------------------------------------------------------------------------------


def test_management_endpoints_describe_agents_skills_protocols_and_system(
    served: tuple[TestClient, RunManager],
) -> None:
    conn, _ = served
    status, agent = call(conn, "GET", "/api/agents/code_reader")
    assert status == 200 and agent["zone"] == "quarantine" and agent["prompt"]
    assert {t["name"] for t in agent["tools"]} >= {"code.read_range", "locator.suggest"}
    assert next(t for t in agent["tools"] if t["name"] == "code.read_range")["reads_untrusted"] is True
    assert call(conn, "GET", "/api/agents/nope")[0] == 404

    status, skills = call(conn, "GET", "/api/skills")
    names = {s["name"]: s for s in skills["skills"]}
    assert status == 200 and "code_reader" in names["check-ifdef-compiled-lines"]["used_by"]
    scope = names["tls-record-length-bounds"]["scope"]
    status, doc = call(conn, "GET", f"/api/skills/{scope}/tls-record-length-bounds")
    assert status == 200 and doc["text"]
    assert call(conn, "GET", "/api/skills/core/..%2f..%2fadapters")[0] == 404
    assert call(conn, "GET", f"/api/skills/{scope}/tls-record-length-bounds?file=..%2fSKILL.md")[0] == 404

    status, adapter = call(conn, "GET", "/api/adapters/tls13")
    assert status == 200 and adapter["requirements"][0]["id"] == "TLS13-0042"
    assert any(c["check"] == "form.manifest" and c["status"] == "PASS" for c in adapter["checks"])
    assert call(conn, "GET", "/api/adapters/..%2f..")[0] == 404

    status, system = call(conn, "GET", "/api/system")
    assert status == 200 and system["versions"]["fastapi"] and "deepseek-flash" in system["models"]["models"]
    assert SECRET not in json.dumps(system)  # khoá không bao giờ lộ ra, chỉ có tên biến


def test_stats_and_run_actions_over_a_finished_run(served: tuple[TestClient, RunManager]) -> None:
    conn, manager = served
    status, res = call(conn, "POST", "/api/runs/validate", {"adapters": [{"id": "tls13"}], "mode": "demo"})
    assert status == 200 and res["ok"] is True and res["runs"] == 1
    status, res = call(conn, "POST", "/api/runs/validate", {"adapters": [{"id": "tls13"}], "mode": "real"})
    assert res["ok"] is False and res["errors"]
    status, created = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})
    run_id = created["runs"][0]["run_id"]
    wait_done(manager, run_id)

    status, stats = call(conn, "GET", "/api/stats?days=7")
    assert status == 200 and stats["totals"]["runs"] == 1 and stats["verdicts"] == {"VIOLATION": 1}
    assert stats["totals"]["evidence"] > 0 and {r["role"] for r in stats["roles"]} >= {"planner", "tester"}
    assert sum(d["runs"] for d in stats["daily"]) == 1

    listed = call(conn, "GET", "/api/runs?digest=true")[1]["runs"]
    assert listed[0]["digest"]["evidence"] > 0

    status, bundle = call(conn, "GET", f"/api/runs/{run_id}/export")
    assert status == 200 and bundle["run"]["run_id"] == run_id and bundle["events"] and bundle["evidence"]

    status, again = call(conn, "POST", f"/api/runs/{run_id}/rerun", {})
    assert status == 201 and again["runs"][0]["run_id"] != run_id
    rec2 = wait_done(manager, again["runs"][0]["run_id"])
    assert rec2["status"] == "finished", rec2["error"]


def test_findings_explain_where_and_how_the_requirement_is_violated(served: tuple[TestClient, RunManager]) -> None:
    conn, manager = served
    created = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]
    run_id = created["runs"][0]["run_id"]
    wait_done(manager, run_id)
    status, res = call(conn, "GET", f"/api/runs/{run_id}/findings")
    assert status == 200
    f = res["findings"][0]
    assert (f["label"], f["rule"]) == ("VIOLATION", "V2") and "FAIL hợp lệ" not in f["rule_text"] and f["rule_text"]
    assert f["rbs"]["trigger"].startswith("receive(record)") and "record_overflow" in f["rbs"]["expect"]
    loc = f["location"]
    assert loc["file"] == "src/internal.c" and (loc["line_start"], loc["line_end"]) == (812, 816)
    mismatch = [a for a in loc["aspects"] if a["value"] == "MISMATCH"]
    assert mismatch and mismatch[0]["aspect"] == "REACTION" and "decode_error" in mismatch[0]["observed"]
    assert any(line["flag"] == "mismatch" and "SendAlert" in line["text"] for line in loc["snippet"])
    fails = [c for c in f["tests"]["cases"] if c["outcome"] == "FAIL"]
    assert fails and fails[0]["why"] and fails[0]["observed_text"] and f["decisive"]
    assert call(conn, "GET", "/api/runs/run-nope/findings")[0] == 404


def test_code_view_annotates_lines_with_evidence_and_refuses_arbitrary_paths(
    served: tuple[TestClient, RunManager],
) -> None:
    conn, manager = served
    run_id = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]["runs"][0]["run_id"]
    wait_done(manager, run_id)
    status, idx = call(conn, "GET", f"/api/runs/{run_id}/code")
    assert status == 200 and idx["files"][0]["path"] == "src/internal.c" and idx["files"][0]["bad"] >= 1
    status, doc = call(conn, "GET", f"/api/runs/{run_id}/code/file?path=src/internal.c")
    assert status == 200 and doc["hits"] and any(line["n"] == 815 for line in doc["lines"])
    bad = [a for a in doc["annotations"] if a["severity"] == "bad" and a["kind"] == "aspect"]
    assert bad and bad[0]["evidence_id"].startswith("sha256:") and "decode_error" in bad[0]["detail"]
    for path in ("../../.env", "..%2f..%2f.env", "src/other.c", "C:/Windows/win.ini"):
        assert call(conn, "GET", f"/api/runs/{run_id}/code/file?path={path}")[0] == 404


def test_repo_browser_tree_search_symbols_and_scope(served: tuple[TestClient, RunManager]) -> None:
    """Duyệt mã kiểu Git trên chỉ mục tree-sitter thật: cây, cửa sổ tệp, tìm kiếm, định nghĩa/nơi gọi, và chặn tệp ngoài phạm vi."""
    from rfcv.codeindex.builder import build_index

    conn, manager = served
    run_id = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]["runs"][0]["run_id"]
    wait_done(manager, run_id)
    repo = manager.runs_dir / run_id / "code" / "repo"
    (repo / "src").mkdir(parents=True)
    lines = [f"/* filler {i} */" for i in range(1, 901)]
    lines[299] = "int ProcessReply(WOLFSSL* ssl)"
    lines[300], lines[301] = "{", "    return GetRecordHeader(ssl, 0);"
    lines[302] = "}"
    lines[799] = "static int GetRecordHeader(WOLFSSL* ssl, word32* size)"
    lines[800], lines[811], lines[814], lines[815], lines[829] = (
        "{",
        "    if (*size > 16640) {",
        "        SendAlert(ssl, 2, 40);",
        "        return -1;",
        "}",
    )
    (repo / "src" / "internal.c").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (repo / "src" / "other.c").write_text("int Helper(void) { return 0; }\n", encoding="utf-8")
    build_index(repo, repo.parent / "index.db")

    status, tree = call(conn, "GET", f"/api/runs/{run_id}/code")
    assert status == 200 and tree["source"] == "index"
    by = {f["path"]: f for f in tree["files"]}
    assert (
        set(by) == {"src/internal.c", "src/other.c"}
        and by["src/internal.c"]["bad"] >= 1
        and by["src/other.c"]["annotations"] == 0
    )

    status, doc = call(conn, "GET", f"/api/runs/{run_id}/code/file?path=src/internal.c&around=815")
    assert (
        status == 200
        and doc["source"] == "index"
        and doc["total"] == 900
        and doc["lines"][814]["text"].strip().startswith("SendAlert")
    )
    assert {s["name"] for s in doc["symbols"]} >= {"ProcessReply", "GetRecordHeader"}
    status, win = call(conn, "GET", f"/api/runs/{run_id}/code/file?path=src/internal.c&start=810&end=820")
    assert [x["n"] for x in win["lines"]] == list(range(810, 821))
    assert call(conn, "GET", f"/api/runs/{run_id}/code/file?path=src/other.c")[0] == 200
    for bad in ("../../.env", "src/nope.c", "C:/Windows/win.ini"):
        assert call(conn, "GET", f"/api/runs/{run_id}/code/file?path={bad}")[0] == 404

    found = call(conn, "GET", f"/api/runs/{run_id}/code/search?q=sendalert")[1]
    assert any(m["path"] == "src/internal.c" and m["line"] == 815 for m in found["matches"])
    assert "src/other.c" in call(conn, "GET", f"/api/runs/{run_id}/code/search?q=other")[1]["files"]
    assert call(conn, "GET", f"/api/runs/{run_id}/code/search?q=x")[1]["matches"] == []

    sym = call(conn, "GET", f"/api/runs/{run_id}/code/symbol?name=GetRecordHeader")[1]
    assert (
        sym["indexed"] and sym["definitions"][0]["line_start"] == 800 and sym["callers"][0]["caller"] == "ProcessReply"
    )
    assert (
        call(conn, "GET", f"/api/runs/{run_id}/code/symbol?name=ProcessReply")[1]["callees"][0]["callee"]
        == "GetRecordHeader"
    )
    assert call(conn, "GET", f"/api/runs/{run_id}/code/symbol?name=a;drop table")[1]["definitions"] == []


# ---- vòng phản hồi của người duyệt -------------------------------------------------------------------------------------


def _finished_run(conn: TestClient, manager: RunManager) -> str:
    run_id = call(conn, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]["runs"][0]["run_id"]
    wait_done(manager, run_id)
    return run_id


def test_review_loop_never_overwrites_the_system_label_and_is_append_only(
    served: tuple[TestClient, RunManager],
) -> None:
    import sqlite3

    conn, manager = served
    run_id = _finished_run(conn, manager)
    path = f"/api/runs/{run_id}/reviews"
    base = {"requirement_id": "TLS13-0042", "reviewer": "an"}

    # bất đồng phải có nhãn, nguyên nhân và lý do; thiếu thì từ chối kèm thông báo rõ
    status, res = call(conn, "POST", path, {**base, "decision": "disagree"})
    assert status == 422 and any("nhãn" in e or "lý do" in e or "nguyên nhân" in e for e in res["errors"])
    status, res = call(
        conn,
        "POST",
        path,
        {**base, "decision": "disagree", "label": "COMPLIANT", "reason": "ngắn", "causes": ["false_positive"]},
    )
    assert status == 422
    status, res = call(conn, "POST", path, {**base, "decision": "agree", "causes": ["khong_co"]})
    assert status == 422 and any("phân loại" in e for e in res["errors"])
    assert call(conn, "POST", path, {**base, "requirement_id": "NOPE-1", "decision": "agree"})[0] == 404
    assert (
        call(
            conn,
            "POST",
            path,
            {**base, "decision": "agree", "evidence_flags": [{"evidence_id": "sha256:" + "0" * 64, "flag": "wrong"}]},
        )[0]
        == 422
    )

    ev = call(conn, "GET", f"/api/runs/{run_id}/evidence")[1]["evidence"][0]["evidence_id"]
    status, ok = call(
        conn,
        "POST",
        path,
        {
            **base,
            "decision": "disagree",
            "label": "COMPLIANT",
            "reason": "Cảnh báo handshake_failure cũng chấp nhận được theo triển khai này",
            "causes": ["bad_oracle", "rfc_ambiguity"],
            "evidence_flags": [{"evidence_id": ev, "flag": "wrong", "note": "oracle đòi quá chặt"}],
            "agent_feedback": [{"role": "code_reader", "rating": "good"}],
        },
    )
    assert status == 201 and ok["review"]["system"]["label"] == "VIOLATION" and ok["review"]["label"] == "COMPLIANT"
    assert call(conn, "POST", path, {"requirement_id": "TLS13-0042", "reviewer": "binh", "decision": "agree"})[0] == 201

    # BR3: nhãn của hệ thống không đổi; nhận định là bản ghi riêng
    detail = call(conn, "GET", f"/api/runs/{run_id}")[1]
    assert detail["summary"]["requirements"][0]["label"] == "VIOLATION"
    db = manager.runs_dir / run_id / "evidence.db"
    raw = sqlite3.connect(db)
    assert (
        raw.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 1
        and raw.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2
    )
    for stmt in ("UPDATE reviews SET body='{}'", "DELETE FROM reviews"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(stmt)
    raw.close()
    assert call(conn, "GET", f"/api/runs/{run_id}/verify")[1]["ok"] is True

    states = call(conn, "GET", path)[1]["states"]
    assert states == {"TLS13-0042": "disputed"}
    item = next(i for i in call(conn, "GET", "/api/reviews/queue")[1]["items"] if i["run_id"] == run_id)
    assert item["state"] == "disputed" and item["why"] == "violation_confirm" and item["reviews"] == 2

    s = call(conn, "GET", "/api/reviews/summary")[1]
    assert s["decided"] == 2 and s["agree"] == 1 and s["agreement_rate"] == 0.5
    assert {"system": "VIOLATION", "human": "COMPLIANT", "n": 1} in s["matrix"]
    assert {c["cause"] for c in s["causes"]} == {"bad_oracle", "rfc_ambiguity"} and s["agent_ratings"] == [
        {"role": "code_reader", "good": 1, "bad": 0}
    ]
    assert s["disputes"][0]["reviewer"] == "an"
    exported = call(conn, "GET", "/api/reviews/export")[1].decode()
    assert exported.count("\n") == 2 and "rules_version" in exported and "TLS13-0042" in exported
    assert "Phản hồi của người duyệt" in call(conn, "GET", "/api/reviews/digest")[1].decode()

    # nhận định mới của cùng người thay thế bản cũ trong thống kê, bản cũ vẫn nằm trong kho
    call(conn, "POST", path, {**base, "decision": "agree"})
    assert call(conn, "GET", "/api/reviews/summary")[1]["agreement_rate"] == 1.0
    assert len(call(conn, "GET", path)[1]["reviews"]) == 3


def test_sampling_is_deterministic_and_read_only_mode_blocks_every_write(keyed: None, tmp_path: Path) -> None:
    from rfcv.api.reviews import SAMPLE_PERCENT, in_sample
    from rfcv.api.server import build_app

    assert [in_sample("run-a", f"R{i}") for i in range(50)] == [in_sample("run-a", f"R{i}") for i in range(50)]
    share = sum(in_sample("run-x", f"REQ-{i}") for i in range(2000)) / 2000
    assert abs(share - SAMPLE_PERCENT / 100) < 0.03

    app = build_app(ROOT, frontend=ROOT.parent / "frontend", manager=make_manager(tmp_path, []), read_only=True)
    with TestClient(app) as ro:
        assert call(ro, "GET", "/api/health")[1]["read_only"] is True
        for path, body in (
            ("/api/runs", {"adapters": [{"id": "tls13"}]}),
            ("/api/runs/run-x/reviews", {"requirement_id": "A", "reviewer": "x", "decision": "agree"}),
            ("/api/runs/run-x/cancel", {}),
        ):
            assert call(ro, "POST", path, body)[0] == 403
        assert call(ro, "GET", "/api/reviews/queue")[0] == 200


# ---- soạn thảo có kiểm soát --------------------------------------------------------------------------------------------


@pytest.fixture
def editable(keyed: None, tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """Bản sao của backend/ (adapters, agents, skills, config) để thử sửa mà không đụng tệp thật."""
    import shutil

    root = tmp_path / "root"
    for d in ("adapters", "agents", "skills", "config"):
        shutil.copytree(ROOT / d, root / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    from rfcv.api.server import build_app

    manager = RunManager(root, runs_dir=tmp_path / "runs", code_roots=[tmp_path])
    with TestClient(
        build_app(root, frontend=ROOT.parent / "frontend", manager=manager, agents_root=root / "agents")
    ) as client:
        yield client, root


def test_rbs_edit_goes_through_the_oracle_compiler_with_history_conflict_detection_and_rollback(
    editable: tuple[TestClient, Path],
) -> None:
    conn, root = editable
    listing = call(conn, "GET", "/api/edit/list")[1]
    assert {r["kind"] for r in listing["resources"]} >= {"rbs", "prompt", "role", "skill", "models"}
    cur = call(conn, "GET", "/api/edit/read?kind=rbs&name=tls13/TLS13-0042")[1]
    assert cur["text"].startswith("requirement TLS13-0042") and cur["sha"].startswith("sha256:")

    def check(text: str) -> dict[str, Any]:
        return call(conn, "POST", "/api/edit/validate", {"kind": "rbs", "name": "tls13/TLS13-0042", "text": text})[1]

    good = check(cur["text"])
    assert good["ok"] and good["info"]["oracle_hash"].startswith("sha256:") and good["info"]["variants"]
    assert not check(
        "requirement TLS13-0042 from RFC8446§5.2#p4s3 modal MUST type B\nactor server\ntrigger bogus syntax"
    )["ok"]
    assert any("trùng tên tệp" in e for e in check(cur["text"].replace("TLS13-0042 from", "TLS13-0099 from"))["errors"])
    assert not check(cur["text"].replace("send_alert(record_overflow)", "send_alert(khong_co_trong_tu_vung)"))[
        "ok"
    ]  # từ vựng của adapter

    edited = cur["text"].replace("within 2000ms", "within 3000ms")
    save = {
        "kind": "rbs",
        "name": "tls13/TLS13-0042",
        "text": edited,
        "base_sha": cur["sha"],
        "note": "nới ngưỡng thử",
        "actor": "an",
    }
    assert call(conn, "POST", "/api/edit/save", {**save, "note": ""})[0] == 422  # bắt buộc ghi lý do
    assert call(conn, "POST", "/api/edit/save", {**save, "actor": ""})[0] == 422
    status, res = call(conn, "POST", "/api/edit/save", {**save, "base_sha": "sha256:" + "0" * 64})
    assert status == 409 and res["current_sha"] == cur["sha"]  # người khác đã đổi: không ghi đè
    status, ok = call(conn, "POST", "/api/edit/save", save)
    assert (
        status == 201
        and (root / "adapters/tls13/examples/TLS13-0042.rbs").read_text(encoding="utf-8").count("3000ms") == 1
    )
    assert call(conn, "POST", "/api/edit/save", {**save, "base_sha": ok["sha"]})[0] == 422  # không có thay đổi

    hist = call(conn, "GET", "/api/edit/history?kind=rbs&name=tls13/TLS13-0042")[1]["history"]
    assert [h["action"] for h in hist] == ["save", "baseline"] and hist[0]["actor"] == "an"
    audit = call(conn, "GET", "/api/edit/audit")[1]["entries"][0]
    assert (
        audit["actor"] == "an"
        and audit["before"] == cur["sha"]
        and audit["after"] == ok["sha"]
        and audit["note"] == "nới ngưỡng thử"
    )

    base = next(h for h in hist if h["action"] == "baseline")
    status, back = call(
        conn,
        "POST",
        "/api/edit/restore",
        {"kind": "rbs", "name": "tls13/TLS13-0042", "version": base["id"], "actor": "an", "note": "hoàn tác"},
    )
    assert status == 200 and back["sha"] == cur["sha"]
    assert (root / "adapters/tls13/examples/TLS13-0042.rbs").read_text(encoding="utf-8") == cur["text"]

    # thêm yêu cầu mới, rồi nó xuất hiện trong danh mục
    new = cur["text"].replace("TLS13-0042", "TLS13-0100")
    status, made = call(
        conn,
        "POST",
        "/api/edit/save",
        {
            "kind": "rbs",
            "name": "tls13/TLS13-0100",
            "text": new,
            "base_sha": None,
            "note": "thêm yêu cầu",
            "actor": "an",
        },
    )
    assert status == 201 and made["created"] is True
    assert {
        r["id"]
        for r in next(a for a in call(conn, "GET", "/api/catalog")[1]["adapters"] if a["id"] == "tls13")["requirements"]
    } == {"TLS13-0042", "TLS13-0100"}


def test_agent_profile_models_and_skill_edits_are_gated_by_the_core_validators(
    editable: tuple[TestClient, Path],
) -> None:
    conn, _ = editable

    def check(kind: str, name: str, text: str) -> dict[str, Any]:
        return call(conn, "POST", "/api/edit/validate", {"kind": kind, "name": name, "text": text})[1]

    prompt = call(conn, "GET", "/api/edit/read?kind=prompt&name=code_reader")[1]["text"]
    res = check("prompt", "code_reader", prompt + "\nLuôn trích đúng số dòng.\n")
    assert res["ok"] and res["info"]["prompts_digest"]
    planner = call(conn, "GET", "/api/edit/read?kind=prompt&name=planner")[1]["text"]
    changed = check(
        "prompt", "planner", planner.replace("<!-- playbook:begin -->", "<!-- playbook:begin -->\n- sửa tay", 1)
    )
    assert changed["ok"] and any("playbook" in w for w in changed["warnings"])

    role = call(conn, "GET", "/api/edit/read?kind=role&name=code_reader")[1]["text"]
    assert check("role", "code_reader", role)["ok"]
    assert not check("role", "code_reader", role.replace("zone: quarantine", "zone: privileged"))[
        "ok"
    ]  # vùng tin cậy là kiến trúc, không phải tham số
    assert not check("role", "code_reader", "- không phải ánh xạ")["ok"]

    models = call(conn, "GET", "/api/edit/read?kind=models&name=models")[1]["text"]
    assert check("models", "models", models)["ok"]
    assert any(
        "khoá API" in e
        for e in check("models", "models", models + "\n# api_key: sk-abcdefghijklmnopqrstuvwxyz123456\n")["errors"]
    )
    assert not check("models", "models", models.replace("planner: deepseek-flash", "planner: mo-hinh-khong-co"))["ok"]

    skill = call(conn, "GET", "/api/edit/read?kind=skill&name=core/check-ifdef-compiled-lines")[1]["text"]
    assert check("skill", "core/check-ifdef-compiled-lines", skill)["ok"]
    assert not check(
        "skill", "core/check-ifdef-compiled-lines", skill.replace("name: check-ifdef-compiled-lines", "name: ten-khac")
    )["ok"]


def test_editing_is_limited_to_the_resource_whitelist_and_blocked_in_read_only_mode(
    editable: tuple[TestClient, Path], tmp_path: Path
) -> None:
    conn, root = editable
    for kind, name in (
        ("rbs", "../../etc/passwd"),
        ("rbs", "tls13/../../x"),
        ("prompt", "../adapters"),
        ("skill", "core/../../config"),
        ("code", "x"),
        ("rbs", "nope/TLS13-0001"),
    ):
        assert call(conn, "GET", f"/api/edit/read?kind={kind}&name={name}")[0] in (404, 422)
        assert call(
            conn,
            "POST",
            "/api/edit/save",
            {"kind": kind, "name": name, "text": "x" * 20, "base_sha": None, "note": "xxx", "actor": "an"},
        )[0] in (404, 422)
    assert not (root.parent / "x").exists()

    from rfcv.api.server import build_app

    app = build_app(
        root,
        frontend=ROOT.parent / "frontend",
        manager=RunManager(root, runs_dir=tmp_path / "r2"),
        agents_root=root / "agents",
        read_only=True,
    )
    with TestClient(app) as ro:
        body = {
            "kind": "models",
            "name": "models",
            "text": "models: {}",
            "base_sha": None,
            "note": "xxx",
            "actor": "an",
        }
        assert (
            call(ro, "POST", "/api/edit/save", body)[0] == 403
            and call(
                ro,
                "POST",
                "/api/edit/restore",
                {"kind": "models", "name": "models", "version": "x", "note": "", "actor": "an"},
            )[0]
            == 403
        )
        assert (
            call(ro, "POST", "/api/edit/validate", body)[0] == 200
            and call(ro, "GET", "/api/edit/list")[1]["read_only"] is True
        )
