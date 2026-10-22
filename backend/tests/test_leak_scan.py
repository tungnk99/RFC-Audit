"""Quét rò rỉ sau mỗi lần chạy (BL-62, QS-07, YD-51, LG-1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ADAPTER_DIR
from rfcv.assembly import build_runtime
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig
from rfcv.core.trace import TraceLog
from rfcv.gates.leak_scan import REPORT_NAME, scan_run

SECRET = "sk-test-KHOA-BI-MAT-0123456789"
PRIVATE_LINE = 'const char *PRIVATE_KEY_MATERIAL = "3082025c02010002818100c8d9e1f0a1b2c3d4e5f6a7b8c9";'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo-src"
    (root / "src").mkdir(parents=True)
    (root / "certs").mkdir()
    (root / "src" / "internal.c").write_text(
        "/* Copyright (c) wolfSSL Inc. All rights reserved by the license terms */\n"
        "int GetRecordHeader(void) { return 0; /* dòng trong phạm vi, đủ dài để thành dấu hiệu */ }\n",
        encoding="utf-8",
    )
    (root / "certs" / "server.key").write_text(PRIVATE_LINE + "\n", encoding="utf-8")
    # dòng bản quyền giống hệt ở tệp ngoài phạm vi: dòng chung, không được báo nhầm
    (root / "certs" / "NOTICE").write_text(
        "/* Copyright (c) wolfSSL Inc. All rights reserved by the license terms */\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "runs" / "run-1"
    (d / "artifacts").mkdir(parents=True)
    (d / "repo" / "src").mkdir(parents=True)
    return d


def scan(run_dir: Path, repo: Path | None = None, secrets: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return scan_run(
        run_dir,
        secrets=secrets if secrets is not None else {"DEEPSEEK_API_KEY": SECRET},
        code_root=repo,
        include=("src/**",),
        exclude=("**/*.key", "certs/**"),
    )


def test_a_clean_run_reports_nothing_and_writes_a_report(run_dir: Path, repo: Path) -> None:
    log = TraceLog(run_dir / "trace.db")
    log.append("run-1", "tool_call", {"output": "int GetRecordHeader(void) mà không có gì nhạy cảm"})
    result = scan(run_dir, repo)
    assert result.clean and result.out_of_scope_checked and result.files_scanned >= 1
    report = json.loads((run_dir / REPORT_NAME).read_text(encoding="utf-8"))
    assert report["clean"] is True and report["leaks"] == []


def test_an_api_key_in_the_trace_is_found_without_echoing_it(run_dir: Path, repo: Path) -> None:
    log = TraceLog(run_dir / "trace.db")
    log.append("run-1", "llm_error", {"error": f"401 Unauthorized, header Authorization: Bearer {SECRET}"})
    result = scan(run_dir, repo)
    assert [(x.kind, x.file, x.detail) for x in result.leaks] == [("api_key", "trace.db", "DEEPSEEK_API_KEY")]
    assert SECRET not in json.dumps(result.to_json()) and SECRET not in (run_dir / REPORT_NAME).read_text("utf-8")


def test_an_api_key_in_an_artifact_is_found(run_dir: Path, repo: Path) -> None:
    (run_dir / "artifacts" / "ab").mkdir()
    (run_dir / "artifacts" / "ab" / "blob").write_bytes(b"\x00\x01 env dump: DEEPSEEK_API_KEY=" + SECRET.encode())
    assert [(x.kind, x.file) for x in scan(run_dir, repo).leaks] == [("api_key", "artifacts/ab/blob")]


def test_too_short_secrets_are_not_scanned(run_dir: Path) -> None:
    (run_dir / "notes.txt").write_text("abc", encoding="utf-8")
    assert scan(run_dir, None, {"X": "abc"}).clean


def test_content_of_a_file_outside_the_scope_is_found(run_dir: Path, repo: Path) -> None:
    log = TraceLog(run_dir / "trace.db")
    log.append("run-1", "tool_call", {"output": f"đọc thử: {PRIVATE_LINE}"})
    result = scan(run_dir, repo)
    assert [(x.kind, x.file, x.detail) for x in result.leaks] == [("out_of_scope", "certs/server.key", "dòng 1")]
    assert "3082025c" not in json.dumps(result.to_json())  # chỉ tên tệp và số dòng, không nội dung


def test_a_line_shared_with_an_in_scope_file_is_not_a_leak(run_dir: Path, repo: Path) -> None:
    log = TraceLog(run_dir / "trace.db")
    log.append(
        "run-1", "tool_call", {"output": "/* Copyright (c) wolfSSL Inc. All rights reserved by the license terms */"}
    )
    assert scan(run_dir, repo).clean  # dòng này có ở certs/NOTICE (ngoài) và src/internal.c (trong)


def test_the_staged_scope_copy_is_not_scanned(run_dir: Path, repo: Path) -> None:
    (run_dir / "repo" / "src" / "internal.c").write_text(f"// {SECRET}\n{PRIVATE_LINE}\n", encoding="utf-8")
    assert scan(run_dir, repo).clean  # `repo/` là bản sao phạm vi có chủ đích; rò rỉ ở đó không thuộc dữ liệu lần chạy


def test_without_a_code_root_only_secrets_are_checked_and_it_says_so(run_dir: Path) -> None:
    result = scan(run_dir, None)
    assert result.clean and not result.out_of_scope_checked
    assert any("code-root" in n or "gốc kho mã" in n for n in result.notes)


def test_llm_gateway_exposes_only_keys_that_are_set() -> None:
    cfg = ModelsConfig.model_validate(
        {
            "models": {
                "a": {"provider": "openai", "model": "x", "api_key_env": "KEY_A"},
                "b": {"provider": "openai", "model": "y", "api_key_env": "KEY_B"},
            },
            "agents": {},
        }
    )
    assert LLMGateway(cfg, env={"KEY_A": SECRET}).api_keys() == {"KEY_A": SECRET}
    assert LLMGateway(cfg, env={}).api_keys() == {}


async def test_a_full_run_scans_clean_and_a_planted_key_is_caught(tmp_path: Path) -> None:
    """Quét sau một lần chạy đầu-cuối thật (qua cổng công cụ, kho bằng chứng, trace): sạch; nhét khoá vào trace thì bị bắt."""
    from test_assembly import ScriptedRunner, make_config, make_providers

    runner = ScriptedRunner()
    rt = build_runtime(make_config(tmp_path), make_providers(runner))
    runner.gateway = rt.gateway
    cfg = ModelsConfig.model_validate(
        {"models": {"m": {"provider": "openai", "model": "x", "api_key_env": "RFCV_KEY"}}, "agents": {}}
    )
    rt.llm = LLMGateway(cfg, env={"RFCV_KEY": SECRET})
    try:
        await rt.run_all(ADAPTER_DIR / "examples")
        rt.trace.append(rt.run_id, "oops", {"msg": f"dùng khoá {SECRET}"})
    finally:
        rt.close()
    result = rt.scan_leaks()
    assert [(x.kind, x.file, x.detail) for x in result.leaks] == [("api_key", "trace.db", "RFCV_KEY")]
    assert (tmp_path / "runs" / rt.run_id / REPORT_NAME).is_file()
