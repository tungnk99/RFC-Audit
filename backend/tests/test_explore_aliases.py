"""Cổng lệnh của Code Reader: các cách viết thông dụng của cờ ĐÃ ĐƯỢC PHÉP được chấp nhận (chuẩn hoá về dạng chuẩn), còn mọi cờ
mới thì vẫn bị cấm. Trong lần chạy trên wolfSSL thật, agent bị từ chối ở `--glob`, `--iglob`, `head -40`, `-m5`...; đó là cờ vô hại."""

from __future__ import annotations

from pathlib import Path

import pytest

from rfcv.gates import explore_policy
from rfcv.gates.explore_policy import CodeScope, CommandRejected


@pytest.fixture
def scope(tmp_path: Path) -> CodeScope:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "internal.c").write_text("x\n", encoding="utf-8")
    return CodeScope(root=tmp_path, include=("src/**", "src"), exclude=("**/*.key", "certs/**"))


def canon(cmd: str, scope: CodeScope) -> list[list[str]]:
    return explore_policy.validate(cmd, scope)


@pytest.mark.parametrize(
    ("cmd", "expected_first"),
    [
        ("rg -n foo --glob '*.c' src", ["rg", "-n", "foo", "-g", "*.c", "src"]),
        ("rg -n foo --iglob '*.c' src", ["rg", "-n", "foo", "-g", "*.c", "src"]),
        ("rg -n foo --glob='*.c' src", ["rg", "-n", "foo", "-g", "*.c", "src"]),
        ("rg -n foo --max-count 5 src", ["rg", "-n", "foo", "-m", "5", "src"]),
        ("rg foo -m5 src", ["rg", "foo", "-m", "5", "src"]),
        ("rg foo -g'*.h' src", ["rg", "foo", "-g", "*.h", "src"]),
        ("rg foo -A3 src", ["rg", "foo", "-A", "3", "src"]),
        ("rg foo --type c src", ["rg", "foo", "-t", "c", "src"]),
        ("rg foo --ignore-case --line-number src", ["rg", "foo", "-i", "-n", "src"]),
        ("grep -rn foo src", ["grep", "-r", "-n", "foo", "src"]),
        ("grep -rnE 'a|b' src", ["grep", "-r", "-n", "-E", "a|b", "src"]),
    ],
)
def test_common_spellings_of_allowed_flags_are_accepted_in_canonical_form(
    cmd: str, expected_first: list[str], scope: CodeScope
) -> None:
    assert canon(cmd, scope)[0] == expected_first


@pytest.mark.parametrize(
    ("cmd", "expected_last"),
    [
        ("rg -n foo src | head -40", ["head", "-n", "40"]),
        ("rg -n foo src | head -n40", ["head", "-n", "40"]),
        ("rg -n foo src | tail -5", ["tail", "-n", "5"]),
        ("rg -n foo src | head -n 20", ["head", "-n", "20"]),
    ],
)
def test_head_and_tail_accept_a_bare_count(cmd: str, expected_last: list[str], scope: CodeScope) -> None:
    assert canon(cmd, scope)[-1] == expected_last


def test_a_flag_value_that_looks_like_a_flag_is_left_alone(scope: CodeScope) -> None:
    """Giá trị của -e là mẫu tìm kiếm, kể cả khi bắt đầu bằng dấu trừ: không được đổi nó."""
    assert canon("rg -e '-40' src", scope)[0] == ["rg", "-e", "-40", "src"]


@pytest.mark.parametrize(
    ("cmd", "code"),
    [
        ("rg --pre cat x src", "FLAG_BLOCKED"),
        ("rg --pre=cat x src", "FLAG_BLOCKED"),
        ("rg foo --hidden src", "FLAG_NOT_ALLOWED"),
        ("rg foo -U src", "FLAG_NOT_ALLOWED"),
        ("rg foo --follow src", "FLAG_NOT_ALLOWED"),
        ("rg foo --files src", "FLAG_NOT_ALLOWED"),
        ("grep -R foo src", "FLAG_NOT_ALLOWED"),
        ("grep -rR foo src", "FLAG_NOT_ALLOWED"),
        ("head -c 100 src/internal.c", "FLAG_NOT_ALLOWED"),
        ("rg foo src | head -n", "PARSE_ERROR"),
        ("rg foo src > out", "FORBIDDEN_SYNTAX"),
        ("rg 'a' src ; ls", "FORBIDDEN_SYNTAX"),
        ("rg foo ../../etc", "PATH_OUT_OF_SCOPE"),
        ("rg foo --glob '*.c' /etc", "PATH_OUT_OF_SCOPE"),
    ],
)
def test_new_capabilities_are_still_refused(cmd: str, code: str, scope: CodeScope) -> None:
    with pytest.raises(CommandRejected) as exc:
        explore_policy.validate(cmd, scope)
    assert exc.value.code == code


def test_rejection_message_lists_the_allowed_flags_so_the_agent_can_self_correct(scope: CodeScope) -> None:
    with pytest.raises(CommandRejected) as exc:
        explore_policy.validate("rg foo --hidden src", scope)
    assert "-g" in str(exc.value) and "-m" in str(exc.value)
