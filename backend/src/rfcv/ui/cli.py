"""Giao diện dòng lệnh (thiết kế chính, Bảng 22).

Lệnh chung do lõi cung cấp; lệnh riêng của từng miền (ví dụ `rfcv rbs`, `rfcv rfc`) do domain pack đóng góp và được
gắn vào
lúc khởi động từ registry plugin.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import typer

from rfcv import __version__
from rfcv.plugins import current_registry

app = typer.Typer(help="rfcv: kiểm chứng tuân thủ đặc tả dựa trên bằng chứng.", no_args_is_help=True)
adapter_app = typer.Typer(help="Quản lý adapter.", no_args_is_help=True)
skills_app = typer.Typer(help="Agent Skills (chuẩn agentskills.io).", no_args_is_help=True)
app.add_typer(adapter_app, name="adapter")
app.add_typer(skills_app, name="skills")

# Lệnh của miền đã đăng ký (rbs, rfc, …). Lỗi plugin hiện ra ngay thay vì bị nuốt.
for _domain in current_registry().domains.values():
    for _name, _sub in _domain.cli_apps.items():
        app.add_typer(_sub, name=_name)

_NOT_YET = "chưa cài đặt ở mốc này (xem README, mục Lộ trình)"


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def plugins() -> None:
    """Liệt kê những gì đã đăng ký vào lõi: miền, loại bằng chứng, nhiệm vụ, công cụ, bộ quy tắc, nhà cung cấp."""
    reg = current_registry()
    rows = {
        "domains": {k: v.version for k, v in reg.domains.items()},
        "evidence_kinds": {k: f"{v.tier}@{v.version}" for k, v in reg.kinds.items()},
        "tasks": {k: v.target_role for k, v in reg.tasks.items()},
        "tools": {k: v.effect.value + (" (không tin cậy)" if v.reads_untrusted else "") for k, v in reg.tools.items()},
        "rule_sets": {k: v.version[:19] for k, v in reg.rule_sets.items()},
        "backends": sorted(reg.backends),
        "code_indexes": sorted(reg.code_indexes),
        "executors": sorted(reg.executors),
        "sut_launchers": sorted(reg.sut_launchers),
        "llm_providers": sorted(reg.llm_providers),
        "agent_runtimes": sorted(reg.agent_runtimes),
    }
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@app.command()
def agents(
    as_json: Annotated[bool, typer.Option("--json", help="In JSON thay vì bảng")] = False,
    agents_dir: Annotated[Path | None, typer.Option("--agents", help="Thư mục hồ sơ và lời nhắc agent")] = None,
) -> None:
    """Bản đồ agent của từng miền: thư mục, vùng tin cậy, nhiệm vụ nhận, schema trả, và đã nối vào luồng chạy chưa."""
    import yaml

    from rfcv.core.policy import find_agents_root

    root = agents_dir if agents_dir is not None else find_agents_root()
    rows: list[dict[str, object]] = []
    for pack in current_registry().domains.values():
        for a in pack.agents:
            role: dict[str, object] = {}
            if a.has_role and (root / a.name / "role.yaml").is_file():
                role = yaml.safe_load((root / a.name / "role.yaml").read_text(encoding="utf-8"))
            rows.append(
                {
                    "domain": pack.name,
                    "agent": a.name,
                    "data": str(root / a.name) if a.has_role else "-",
                    "zone": role.get("zone", "tất định"),
                    "stage": a.stage,
                    "tasks": [t.name for t in a.tasks],
                    "output": role.get("output_schema", "-"),
                    "skills": role.get("skills", []),
                    "wired": a.wired,
                    "summary": a.summary,
                }
            )
    if as_json:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    typer.echo(f"{'agent':<13} {'vùng':<11} {'giai đoạn':<14} {'nối':<5} nhiệm vụ nhận | skill khai báo")
    for r in rows:
        mark = "có" if r["wired"] else "CHƯA"
        tasks = ", ".join(r["tasks"]) or "-"  # type: ignore[arg-type]
        skills = ", ".join(r["skills"]) or "-"  # type: ignore[arg-type]
        typer.echo(f"{r['agent']!s:<13} {r['zone']!s:<11} {r['stage']!s:<14} {mark:<5} {tasks} | {skills}")
    unwired = [str(r["agent"]) for r in rows if not r["wired"]]
    if unwired:
        typer.echo(f"\nChưa nối vào luồng chạy: {', '.join(unwired)}")


code_app = typer.Typer(help="Khám phá mã: danh mục công cụ cho agent, chỉ mục mã.", no_args_is_help=True)
app.add_typer(code_app, name="code")


class _NullTrace:
    def append(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        role: str | None = None,
        requirement_id: str | None = None,
    ) -> int:
        return 0

    def events(self, kind: str | None = None) -> Iterator[dict[str, Any]]:
        return iter(())


class _NoExecutor:
    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


@code_app.command("tools")
def code_tools(
    role: Annotated[str, typer.Option(help="Vai trò agent")] = "code_reader",
    adapter: Annotated[Path, typer.Option(help="Thư mục adapter")] = Path("adapters/tls13"),
    agents_dir: Annotated[Path | None, typer.Option("--agents", help="Thư mục hồ sơ và lời nhắc agent")] = None,
) -> None:
    """In danh mục công cụ mà một vai trò nhận, đúng khuôn kết quả `tools/list` của MCP (tên, mô tả, inputSchema,
    annotations). Đây chính là phần mô tả mô hình thấy."""
    from types import SimpleNamespace

    from rfcv.adapters.manifest import load_manifest
    from rfcv.core.policy import PolicyStore
    from rfcv.gates.code_gate import InMemoryCodeIndex, build_code_tools
    from rfcv.gates.explore_policy import CodeScope
    from rfcv.gates.tool_gateway import ToolGateway

    reg = current_registry()
    manifest = load_manifest(adapter)
    pack = reg.domain(manifest.domain)
    policy = PolicyStore.load(None, reg, pack.name, agents_dir)
    gateway = ToolGateway(policy, _NullTrace(), reg.tools)
    index = InMemoryCodeIndex({})
    for spec in build_code_tools(index, _NoExecutor(), CodeScope(Path("."))):
        gateway.register(spec)
    domain_tools: Any = getattr(pack.runtime, "tools", None)
    if domain_tools is not None:
        rt = SimpleNamespace(manifest=manifest, run_id="cli", providers=SimpleNamespace(code_index=index))
        for spec in domain_tools(rt):
            gateway.register(spec)
    typer.echo(json.dumps(gateway.tools_list(role), ensure_ascii=False, indent=2))


@code_app.command("index")
def code_index_build(
    root: Annotated[Path, typer.Option(help="Thư mục kho mã (bản sao phạm vi)")],
    out: Annotated[Path, typer.Option(help="Tệp chỉ mục SQLite")],
) -> None:
    """Dựng chỉ mục tree-sitter tại chỗ (phát triển). Khi chạy thật, chỉ mục được dựng trong container code-indexer."""
    from rfcv.codeindex.builder import IndexBuildError, build_index

    try:
        meta = build_index(root, out)
    except IndexBuildError as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(meta, ensure_ascii=False, indent=2))


@adapter_app.command("check")
def adapter_check(adapter_dir: Path) -> None:
    """Kiểm định adapter: in kết quả từng kiểm tra."""
    from rfcv.adapters.checker import check_adapter, passed

    items = check_adapter(adapter_dir)
    for item in items:
        typer.echo(f"{item.status.value:<8} {item.check:<40} {item.detail}")
    raise typer.Exit(0 if passed(items) else 1)


@skills_app.command("check")
def skills_check(
    skills_root: Annotated[Path, typer.Argument(help="Thư mục gốc chứa core/ và <adapter>/")] = Path("skills"),
    adapter: Annotated[str | None, typer.Option(help="Tên adapter để nạp thêm skills/<adapter>")] = None,
    agents_dir: Annotated[Path | None, typer.Option("--agents", help="Thư mục hồ sơ và lời nhắc agent")] = None,
) -> None:
    """Kiểm định thư viện skill và in skill mà từng agent khai báo và sẽ thấy trong lần chạy với adapter này."""
    from rfcv.core.policy import PolicyError, PolicyStore
    from rfcv.core.skills import default_registry, undeclared_skills

    try:
        reg = default_registry(skills_root, adapter)
        policy = PolicyStore.load(None, current_registry(), None, agents_dir)
    except (ValueError, PolicyError) as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(1) from exc
    declared = {r: policy.profile(r).skills for r in policy.roles}
    for role, names in declared.items():
        typer.echo(f"{role:<14} {', '.join(reg.select(names)) or '-'}")
    typer.echo(f"digest {reg.digest}")
    unknown = undeclared_skills(declared, skills_root)
    if unknown:
        typer.echo(f"LỖI: role.yaml khai báo skill không có: {', '.join(unknown)}", err=True)
        raise typer.Exit(1)


@app.command("models")
def models_cmd(
    path: Annotated[Path, typer.Argument(help="Tệp cấu hình mô hình")] = Path("config/models.yaml"),
) -> None:
    """Mô hình được hỗ trợ và agent nào dùng mô hình nào. Cho biết biến chứa khoá đã đặt chưa, không bao giờ in khoá."""
    import os

    import yaml

    from rfcv.core.llm_gateway import LLMGateway, ModelsConfig

    try:
        cfg = ModelsConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("Mô hình hỗ trợ:")
    missing = False
    for name, spec in cfg.models.items():
        if spec.api_key_env is None:
            typer.echo(f"  {name:<18} {spec.provider}:{spec.model}  không cần khoá (máy chủ cục bộ)")
            continue
        is_set = bool(os.environ.get(spec.api_key_env))
        missing = missing or not is_set
        state = "đã đặt" if is_set else "CHƯA đặt trong môi trường"
        typer.echo(f"  {name:<18} {spec.provider}:{spec.model}  khoá {spec.api_key_env} ({state})")
    if missing:
        typer.echo("  (rfcv không tự nạp .env: hãy đặt biến vào môi trường trước khi chạy, xem README)")
    typer.echo("Agent → mô hình:")
    for agent, model in cfg.agents.items():
        typer.echo(f"  {agent:<16} {model}")
    unassigned = LLMGateway(cfg).uncovered(current_registry().role_names())
    if unassigned:
        typer.echo(f"LỖI: agent chưa được gán mô hình: {', '.join(unassigned)}", err=True)
        raise typer.Exit(1)


@app.command("trace")
def trace_cmd(
    run_dir: Annotated[Path, typer.Argument(help="Thư mục một lần chạy (có trace.db), ví dụ runs/run-ab12cd34ef56")],
    requirement: Annotated[str | None, typer.Option("--requirement", "-r", help="Chỉ một yêu cầu")] = None,
    tools: Annotated[bool, typer.Option("--tools", help="Gồm cả từng lời gọi công cụ (rất dài)")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="In từng sự kiện dạng JSON, mỗi dòng một sự kiện")] = False,
) -> None:
    """Xem lại luồng xử lý của một lần chạy: ai được giao gì, bằng chứng nào ra, vì sao dừng. Chỉ đọc."""
    from rfcv.core.trace import TraceLog, describe

    db = run_dir / "trace.db"
    if not db.is_file():
        typer.echo(f"LỖI: không có {db}", err=True)
        raise typer.Exit(1)
    log = TraceLog(db)
    first_ns: int | None = None
    for event in log.events():
        if requirement is not None and event["requirement_id"] not in (None, requirement):
            continue
        if not tools and event["kind"] in ("tool_call", "tool_denied"):
            continue
        if as_json:
            typer.echo(json.dumps(event, ensure_ascii=False))
            continue
        first_ns = event["ts_ns"] if first_ns is None else first_ns
        rnd = event["payload"].get("round")
        typer.echo(
            f"{event['seq']:>5} +{(event['ts_ns'] - first_ns) / 1e9:8.2f}s "
            f"v{rnd if rnd is not None else '-':<2} {event['role'] or '-'!s:<14} {event['kind']:<17} {describe(event)}"
        )


@app.command()
def verify(run_dir: Path) -> None:
    """Kiểm tra chuỗi hash của Evidence store trong một lần chạy."""
    from rfcv.evidence.store import EvidenceStore

    store = EvidenceStore(run_dir / "evidence.db")
    report = store.verify_chain()
    store.close()
    typer.echo(json.dumps(report.__dict__, ensure_ascii=False))
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def run(
    adapter: Annotated[Path, typer.Option(help="Thư mục adapter")],
    source: Annotated[Path | None, typer.Option(help="Thư mục yêu cầu đã duyệt; mặc định <adapter>/examples")] = None,
    run_dir: Annotated[Path, typer.Option(help="Nơi lưu các lần chạy")] = Path("runs"),
    skills: Annotated[Path, typer.Option(help="Thư mục gốc skill")] = Path("skills"),
    agents_dir: Annotated[Path | None, typer.Option("--agents", help="Thư mục hồ sơ và lời nhắc agent")] = None,
    models: Annotated[Path, typer.Option(help="Cấu hình mô hình theo vai trò")] = Path("config/models.yaml"),
    code_root: Annotated[Path | None, typer.Option(help="Nơi kho mã tại commit cố định")] = None,
    rfc_dir: Annotated[
        Path, typer.Option(help="Input store của RFC: rfc<số>.xml (RFCXML v3); thiếu thì agent chỉ thấy RBS")
    ] = Path("inputs/rfc"),
    code_index: Annotated[
        str | None, typer.Option(help="Tên chỉ mục mã trong registry (treesitter | treesitter-local)")
    ] = None,
    executor: Annotated[
        str | None, typer.Option(help="Tên bộ chạy lệnh sandbox trong registry (docker | local-unsandboxed)")
    ] = None,
    sut_launcher: Annotated[str | None, typer.Option(help="Tên bộ chạy SUT trong registry")] = None,
    tenant: Annotated[str, typer.Option()] = "default",
    explain: Annotated[
        bool,
        typer.Option(
            "--explain/--no-explain", help="Report agent viết giải thích cho từng kết luận (Output gate kiểm)"
        ),
    ] = True,
) -> None:
    """Chạy kiểm chứng: lắp ráp runtime từ cấu hình rồi điều tra từng yêu cầu."""
    from rfcv.assembly import MissingProviderError, RuntimeConfig, build_runtime

    cfg = RuntimeConfig(
        adapter_dir=adapter,
        run_dir=run_dir,
        skills_root=skills,
        agents_root=agents_dir,
        models_path=models if models.is_file() else None,
        code_root=code_root,
        rfc_dir=rfc_dir if rfc_dir.is_dir() else None,
        tenant=tenant,
        code_index=code_index,
        executor=executor,
        sut_launcher=sut_launcher,
        explain=explain,
    )
    from rfcv.codeindex.workspace import WorkspaceError

    try:
        rt = build_runtime(cfg)
    except MissingProviderError as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        typer.echo("Chưa có triển khai cho các thành phần trên; xem `rfcv plugins` và README, mục Lộ trình.", err=True)
        raise typer.Exit(2) from exc
    except WorkspaceError as exc:
        typer.echo(f"LỖI kho mã: {exc}", err=True)
        raise typer.Exit(2) from exc
    try:
        verdicts = asyncio.run(rt.run_all(source or adapter / "examples"))
    finally:
        rt.close()
    scan = rt.scan_leaks()  # QS-07: khoá API và tệp ngoài phạm vi không được xuất hiện trong dữ liệu lần chạy
    typer.echo(
        json.dumps(
            {"run_id": rt.run_id, "verdicts": [v.to_json() for v in verdicts], "leak_scan": scan.to_json()},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not scan.clean:
        typer.echo(f"CẢNH BÁO: phát hiện {len(scan.leaks)} dấu vết rò rỉ; xem {rt.run_id}/leak_scan.json", err=True)
        raise typer.Exit(3)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Địa chỉ nghe; mặc định chỉ máy cục bộ")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Cổng")] = 8765,
    root: Annotated[Path, typer.Option(help="Thư mục backend (có adapters/, runs/, config/, skills/)")] = Path("."),
    frontend: Annotated[Path | None, typer.Option(help="Thư mục giao diện; mặc định ../frontend")] = None,
    code_root: Annotated[
        list[Path] | None, typer.Option("--code-root", help="Thư mục người dùng được chọn làm mã nguồn (lặp được)")
    ] = None,
    env_file: Annotated[
        Path | None,
        typer.Option(help="Tệp .env để nạp RIÊNG khoá mô hình khai báo trong models.yaml (không nạp biến khác)"),
    ] = None,
    read_only: Annotated[
        bool, typer.Option("--read-only", help="Chỉ xem: chặn chạy, huỷ, ghi nhận định và sửa tệp")
    ] = False,
    no_auth: Annotated[
        bool, typer.Option("--no-auth", help="Tắt đăng nhập (chỉ dùng trên máy cá nhân; mọi người là admin cục bộ)")
    ] = False,
) -> None:
    """Mở giao diện web: chọn giao thức RFC và mã nguồn, chạy, theo dõi agent trực tiếp, xem trace, duyệt và phản hồi."""
    from rfcv.api.server import load_model_keys
    from rfcv.api.server import serve as make_server

    root = root.resolve()
    if env_file is not None:
        try:
            names = load_model_keys(env_file, root / "config" / "models.yaml")
        except (OSError, ValueError) as exc:
            typer.echo(f"LỖI: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"Đã nạp khoá từ {env_file}: {', '.join(names) or 'không có biến mới'}")
    typer.echo(f"rfcv UI: http://{host}:{port}/   (tài liệu API: /docs; Ctrl+C để dừng)")
    make_server(
        root,
        host=host,
        port=port,
        frontend=frontend or root.parent / "frontend",
        code_roots=code_root or [root.parent],
        read_only=read_only,
        auth=not no_auth,
    )


users_app = typer.Typer(help="Tài khoản giao diện web (admin | member).", no_args_is_help=True)
app.add_typer(users_app, name="users")


def _auth_store(root: Path) -> Any:
    from rfcv.api.auth import AuthStore

    return AuthStore(root.resolve() / ".rfcv-ui" / "auth.db")


_ROOT_OPT = Annotated[Path, typer.Option("--root", help="Thư mục backend")]


def _auth_call(fn: Any) -> None:
    from rfcv.api.auth import AuthError

    try:
        fn()
    except AuthError as exc:
        typer.echo(f"LỖI: {exc.message}", err=True)
        raise typer.Exit(1) from exc


@users_app.command("list")
def users_list(root: _ROOT_OPT = Path(".")) -> None:
    """Liệt kê tài khoản."""
    for u in _auth_store(root).users():
        typer.echo(f"{u.username:<20} {u.role:<7} {'đã khoá' if u.disabled else 'hoạt động'}")


@users_app.command("add")
def users_add(
    username: str,
    role: Annotated[str, typer.Option(help="admin | member")] = "member",
    display: Annotated[str, typer.Option(help="Tên hiển thị")] = "",
    root: _ROOT_OPT = Path("."),
) -> None:
    """Tạo tài khoản (hỏi mật khẩu, không hiện khi gõ)."""
    password = typer.prompt("Mật khẩu", hide_input=True, confirmation_prompt=True)
    _auth_call(lambda: _auth_store(root).create(username, password, role, display, actor="CLI"))
    typer.echo(f"Đã tạo {username} ({role})")


@users_app.command("passwd")
def users_passwd(username: str, root: _ROOT_OPT = Path(".")) -> None:
    """Đặt lại mật khẩu (thu hồi mọi phiên đang đăng nhập của tài khoản)."""
    password = typer.prompt("Mật khẩu mới", hide_input=True, confirmation_prompt=True)
    _auth_call(lambda: _auth_store(root).set_password(username, password, actor="CLI"))
    typer.echo("Đã đổi mật khẩu")


@users_app.command("role")
def users_role(username: str, role: str, root: _ROOT_OPT = Path(".")) -> None:
    """Đổi vai trò (admin | member)."""
    _auth_call(lambda: _auth_store(root).set_role(username, role, actor="CLI"))
    typer.echo("Đã đổi vai trò")


@users_app.command("disable")
def users_disable(username: str, root: _ROOT_OPT = Path(".")) -> None:
    """Khoá tài khoản."""
    _auth_call(lambda: _auth_store(root).set_disabled(username, True, actor="CLI"))
    typer.echo("Đã khoá")


@users_app.command("enable")
def users_enable(username: str, root: _ROOT_OPT = Path(".")) -> None:
    """Mở khoá tài khoản."""
    _auth_call(lambda: _auth_store(root).set_disabled(username, False, actor="CLI"))
    typer.echo("Đã mở khoá")


@users_app.command("remove")
def users_remove(username: str, root: _ROOT_OPT = Path(".")) -> None:
    """Xoá tài khoản."""
    _auth_call(lambda: _auth_store(root).delete(username, actor="CLI"))
    typer.echo("Đã xoá")


@app.command()
def specs(run_id: str) -> None:
    """Duyệt đặc tả bất đồng và mẫu 10%."""
    typer.echo(f"specs: {_NOT_YET}", err=True)
    raise typer.Exit(2)


@app.command()
def status(
    run_id: str,
    runs: Annotated[Path, typer.Option("--runs", help="Thư mục chứa các lần chạy")] = Path("runs"),
    as_json: Annotated[bool, typer.Option("--json", help="In JSON")] = False,
) -> None:
    """Tiến độ theo trạng thái và chi phí đã dùng (token; USD cần bảng giá, xem BL-76)."""
    from rfcv.ui.report import progress, resolve_run

    try:
        data = progress(resolve_run(run_id, runs))
    except FileNotFoundError as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(2) from exc
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    req, tok = data["requirements"], data["tokens"]
    typer.echo(f"Yêu cầu: {req['decided']}/{req['started']} đã có kết luận, {req['in_progress']} đang chạy")
    typer.echo("Theo nhãn: " + (", ".join(f"{k} {v}" for k, v in sorted(data["by_label"].items())) or "chưa có"))
    typer.echo(f"Token: {tok['total']:,} (" + ", ".join(f"{k} {v:,}" for k, v in sorted(tok["by_role"].items())) + ")")
    typer.echo(
        f"Lời gọi công cụ: {data['tool_calls']['total']} | thời gian: {data['seconds']}s | USD: chưa tính (cần bảng giá)"
    )


@app.command()
def rerun(run_id: str, commit: Annotated[str, typer.Option()]) -> None:
    """Kiểm chứng lại gia tăng khi mã thay đổi (M6)."""
    typer.echo(f"rerun: {_NOT_YET}", err=True)
    raise typer.Exit(2)


@app.command()
def review(run_id: str) -> None:
    """Bảng duyệt yêu cầu NEEDS_REVIEW: dùng giao diện web (`rfcv serve`, mục Duyệt & phản hồi)."""
    typer.echo(f"Mở giao diện: rfcv serve, rồi vào #/runs/{run_id}/tab/summary (mục Duyệt & phản hồi).", err=True)
    raise typer.Exit(2)


@app.command()
def report(
    run_id: str,
    format: Annotated[str, typer.Option("--format", help="html | json | sarif")] = "html",
    runs: Annotated[Path, typer.Option("--runs", help="Thư mục chứa các lần chạy")] = Path("runs"),
    out: Annotated[Path | None, typer.Option("--out", help="Ghi ra tệp thay vì in ra màn hình")] = None,
) -> None:
    """Sinh báo cáo của một lần chạy từ nhật ký và kho bằng chứng: HTML, JSON hoặc SARIF. Nhãn không bao giờ bị sửa."""
    from rfcv.ui.report import load_run, resolve_run, to_html, to_json, to_sarif

    if format not in ("html", "json", "sarif"):
        typer.echo(f"LỖI: --format phải là html, json hoặc sarif, không phải '{format}'", err=True)
        raise typer.Exit(2)
    try:
        loaded = load_run(resolve_run(run_id, runs))
    except FileNotFoundError as exc:
        typer.echo(f"LỖI: {exc}", err=True)
        raise typer.Exit(2) from exc
    text = (
        to_html(loaded)
        if format == "html"
        else json.dumps(to_json(loaded) if format == "json" else to_sarif(loaded), ensure_ascii=False, indent=2)
    )
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Đã ghi {out}")
