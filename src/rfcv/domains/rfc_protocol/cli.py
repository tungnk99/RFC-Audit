"""Lệnh CLI do miền RFC giao thức đóng góp: `rfcv rbs ...` và `rfcv rfc ...`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

rbs_app = typer.Typer(help="Công cụ cho đặc tả hành vi (RBS).", no_args_is_help=True)
rfc_app = typer.Typer(help="Công cụ cho văn bản RFC.", no_args_is_help=True)


@rbs_app.command("check")
def rbs_check(
    rbs_file: Path,
    adapter_dir: Annotated[Path, typer.Option("--adapter", help="Thư mục adapter")],
) -> None:
    """Phân tích RBS, kiểm tra theo từ vựng adapter, biên dịch oracle và in tập biến thể."""
    from rfcv.adapters.manifest import load_manifest
    from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
    from rfcv.domains.rfc_protocol.spec.oracle_compiler import OracleCompileError, compile_oracle
    from rfcv.domains.rfc_protocol.spec.rbs import RbsSyntaxError, parse_rbs

    manifest = load_manifest(adapter_dir)
    try:
        oracle = compile_oracle(parse_rbs(rbs_file.read_text(encoding="utf-8")), to_vocabulary(manifest))
    except (RbsSyntaxError, OracleCompileError) as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        json.dumps({"oracle_hash": oracle.oracle_hash, **oracle.model_dump(mode="json")}, ensure_ascii=False, indent=2)
    )


@rfc_app.command("extract")
def rfc_extract(
    xml_file: Path,
    rfc: Annotated[int, typer.Option(help="Số RFC, ví dụ 8446")],
    section: Annotated[list[str] | None, typer.Option(help="Mục trong phạm vi; lặp lại để thêm")] = None,
) -> None:
    """Tách câu yêu cầu BCP 14 từ bản RFCXML v3, in mỗi câu một dòng JSON."""
    from rfcv.domains.rfc_protocol.rfc_gate import extract_requirements

    for s in extract_requirements(xml_file.read_text(encoding="utf-8"), rfc, section):
        typer.echo(json.dumps(s.__dict__, ensure_ascii=False))
