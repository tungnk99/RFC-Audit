"""Composition root: lắp ráp mọi thành phần của một lần chạy từ cấu hình và registry.

`build_runtime` là nơi duy nhất biết cách nối kho bằng chứng, nhật ký, policy, cổng, runtime agent và hub điều phối.
Mọi thứ thay được ở đây (nhà cung cấp mô hình, backend, chỉ mục mã, bộ chạy SUT, runtime agent) đều đi qua `Providers`
hoặc registry plugin, nên thêm công nghệ mới không phải sửa lõi.

Thiếu nhà cung cấp mà miền yêu cầu thì báo rõ thiếu gì (`MissingProviderError`) thay vì chạy dở.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from rfcv.adapters.manifest import AdapterManifest, load_manifest
from rfcv.core.budget import RequirementBudget
from rfcv.core.execution_loop import ExecutionLoop
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig
from rfcv.core.policy import PolicyError, PolicyStore
from rfcv.core.prompts import prompts_digest
from rfcv.core.runner import RoleRunner
from rfcv.core.skills import SkillRegistry, default_registry, undeclared_skills
from rfcv.core.trace import TraceLog
from rfcv.core.trace_mirror import SupabaseMirror
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.registry import RequirementRegistry, State
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import RuleSet, VerdictRecord
from rfcv.gates.code_gate import build_code_tools
from rfcv.gates.explore_policy import CodeScope
from rfcv.gates.tool_gateway import ToolGateway, ToolSpec
from rfcv.manifest import RunManifest, package_versions, registry_fingerprint
from rfcv.plugins import Registry, current_registry, use_registry
from rfcv.spi import DomainPack


class MissingProviderError(RuntimeError):
    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__("thiếu nhà cung cấp: " + ", ".join(missing))
        self.missing = tuple(missing)


@dataclass(frozen=True)
class Providers:
    """Nhà cung cấp truyền tường minh; thứ nào để trống thì lấy từ registry theo tên trong cấu hình."""

    backend: Any | None = None
    code_index: Any | None = None
    executor: Any | None = None
    sut_launcher: Any | None = None
    role_runner: RoleRunner | None = None
    models: Mapping[str, Any] | None = None  # ghi đè mô hình theo vai trò (kiểm thử, nhúng)
    extra_tools: Sequence[ToolSpec] = ()


@dataclass(frozen=True)
class RuntimeConfig:
    adapter_dir: Path
    run_dir: Path
    skills_root: Path | None = None
    agents_root: Path | None = None  # tầng ghi đè agent ngoài mã nguồn (dữ liệu: role.yaml, prompt.md)
    models_path: Path | None = None
    code_root: Path | None = None
    run_id: str | None = None
    tenant: str = "default"
    seed: int = 0
    agent_runtime: str = "pydantic_ai"
    code_index: str | None = None  # tên trong registry `rfcv.code_indexes`
    executor: str | None = None  # tên trong registry `rfcv.executors`
    sut_launcher: str | None = None  # tên trong registry `rfcv.sut_launchers`
    enable_skills: bool = True
    budget: RequirementBudget | None = None
    image_digests: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass
class Runtime:
    run_id: str
    config: RuntimeConfig
    registry: Registry
    pack: DomainPack
    manifest: AdapterManifest
    rules: RuleSet
    policy: PolicyStore
    store: EvidenceStore
    trace: TraceLog
    requirements: RequirementRegistry
    artifacts: ArtifactStore
    gateway: ToolGateway
    llm: LLMGateway
    skills: SkillRegistry | None
    providers: Providers
    run_manifest: RunManifest
    seed: int
    loop: ExecutionLoop | None = None

    def close(self) -> None:
        self.store.close()
        # Nhà cung cấp giữ tài nguyên (container sandbox, kết nối chỉ mục) tự dọn khi lần chạy kết thúc.
        for prov in (self.providers.executor, self.providers.code_index):
            close = getattr(prov, "close", None)
            if callable(close):
                close()

    async def run_all(self, source: Path) -> list[VerdictRecord]:
        """Điều tra lần lượt từng yêu cầu miền nạp được từ `source`, ghi vòng đời vào Requirement registry."""
        if self.loop is None or self.pack.runtime is None:
            raise RuntimeError("miền không khai báo phần chạy")
        verdicts: list[VerdictRecord] = []
        with use_registry(self.registry):
            for inv in self.pack.runtime.investigations(self, source):
                rid = inv.requirement.requirement_id
                self.requirements.add(rid, {"rtype": inv.requirement.rtype, "modal": inv.requirement.modal}, "loader")
                self.requirements.transition(rid, State.SPECIFIED, "oracle_compiler")
                self.requirements.transition(rid, State.INVESTIGATING, "execution_loop")
                verdict = await self.loop.investigate(inv)
                self.requirements.transition(rid, State.DECIDED, "verdict_engine")
                verdicts.append(verdict)
        return verdicts


def _resolve_rules(reg: Registry, pack: DomainPack, manifest: AdapterManifest) -> RuleSet:
    if manifest.verdict_profile is not None:
        try:
            return reg.rule_sets[manifest.verdict_profile]
        except KeyError as exc:
            raise MissingProviderError([f"verdict_profile:{manifest.verdict_profile}"]) from exc
    if len(pack.rule_sets) == 1:
        return pack.rule_sets[0]
    raise MissingProviderError([f"verdict_profile (miền '{pack.name}' có {len(pack.rule_sets)} bộ quy tắc)"])


def build_runtime(
    config: RuntimeConfig, providers: Providers | None = None, registry: Registry | None = None
) -> Runtime:
    reg = registry or current_registry()
    prov = providers or Providers()
    with use_registry(reg):
        manifest = load_manifest(config.adapter_dir)
        pack = reg.domain(manifest.domain)
        rules = _resolve_rules(reg, pack, manifest)
        run_id = config.run_id or f"run-{uuid.uuid4().hex[:12]}"
        config = replace(config, run_id=run_id)  # factory nhà cung cấp cần biết thư mục của lần chạy
        run_dir = config.run_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        code_root = config.code_root or run_dir / "repo"

        # 1. nhà cung cấp: truyền tường minh thắng, nếu không thì tra registry theo tên
        def make(table: Mapping[str, Any], name: str | None) -> Any:
            return table[name](manifest, config) if name and name in table else None

        resolved = replace(
            prov,
            backend=prov.backend or make(reg.backends, manifest.backend),
            code_index=prov.code_index or make(reg.code_indexes, config.code_index),
            executor=prov.executor or make(reg.executors, config.executor),
            sut_launcher=prov.sut_launcher or make(reg.sut_launchers, config.sut_launcher),
        )
        needed = pack.runtime.required_providers() if pack.runtime else ()
        missing = [n for n in needed if getattr(resolved, n, None) is None]
        if missing:
            raise MissingProviderError(missing)

        # 2. policy, kho, nhật ký (SQLite mặc định; thay bằng cài đặt khác của các Protocol repository)
        policy = PolicyStore.load(None, reg, pack.name, config.agents_root)
        store = EvidenceStore(run_dir / "evidence.db", tenant=config.tenant)
        trace = TraceLog(run_dir / "trace.db", SupabaseMirror.from_env(os.environ))
        requirements = RequirementRegistry(run_dir / "registry.db")
        artifacts = ArtifactStore(run_dir / "artifacts")

        # 3. cổng công cụ: chỉ công cụ có khai báo trong registry mới đăng ký được
        gateway = ToolGateway(policy, trace, reg.tools)
        if resolved.code_index is not None and resolved.executor is not None:
            # Bộ chạy lệnh thật gắn bản sao phạm vi làm gốc /repo; kiểm tra đường dẫn của explore phải dùng đúng gốc đó.
            scope = CodeScope(
                root=getattr(resolved.executor, "root", None) or code_root,
                include=tuple(manifest.code_scope.include),
                exclude=tuple(manifest.code_scope.exclude) or CodeScope(code_root).exclude,
            )
            for spec in build_code_tools(resolved.code_index, resolved.executor, scope):
                gateway.register(spec)
        for spec in resolved.extra_tools:
            gateway.register(spec)

        # 4. mô hình và skill
        if config.models_path is not None:
            llm = LLMGateway.load(config.models_path, overrides=resolved.models)
            if resolved.models is None:
                llm.validate()
                unassigned = llm.uncovered(policy.roles)
                if unassigned:
                    raise PolicyError(f"{config.models_path}: agent chưa được gán mô hình (mục agents): {unassigned}")
        else:
            llm = LLMGateway(ModelsConfig(), overrides=resolved.models)
        skills = (
            default_registry(config.skills_root, manifest.adapter)
            if config.enable_skills and config.skills_root is not None and config.skills_root.is_dir()
            else None
        )
        if skills is not None and config.skills_root is not None:
            unknown = undeclared_skills({r: policy.profile(r).skills for r in policy.roles}, config.skills_root)
            if unknown:
                raise PolicyError(f"role.yaml khai báo skill không có trong {config.skills_root}: {', '.join(unknown)}")

        # 5. runtime agent
        runner = resolved.role_runner
        if runner is None:
            factory = reg.agent_runtimes.get(config.agent_runtime)
            if factory is None:
                raise MissingProviderError([f"agent_runtime:{config.agent_runtime}"])
            runner = factory(policy, gateway, llm, trace, skills=skills)

        # 6. bản kê lần chạy: mọi đầu vào ảnh hưởng kết luận
        digests = {
            "policy": policy.digest,
            "prompts": prompts_digest(policy, policy.roles),
            "models": llm.digest,
            "skills": skills.digest if skills else "none",
            "adapter": manifest.digest,
            "rules": rules.version,
            "registry": registry_fingerprint(reg),
            **{f"image:{k}": v for k, v in config.image_digests.items()},
        }
        # Commit, digest bản sao, phiên bản tree-sitter, image sandbox: mọi vị trí T1 phải đối chiếu được (C3).
        for prov in (resolved.code_index, resolved.executor):
            entries: Any = getattr(prov, "manifest_entries", None)
            if entries is not None:
                digests.update(entries())
        run_manifest = RunManifest(
            run_id=run_id,
            tenant=config.tenant,
            domain=pack.name,
            domain_version=pack.version,
            adapter=manifest.adapter,
            adapter_version=manifest.version,
            digests=digests,
            packages=package_versions(),
            config={"seed": config.seed, "agent_runtime": config.agent_runtime},
        )
        run_manifest.write(run_dir / "manifest.json")

        rt = Runtime(
            run_id=run_id,
            config=config,
            registry=reg,
            pack=pack,
            manifest=manifest,
            rules=rules,
            policy=policy,
            store=store,
            trace=trace,
            requirements=requirements,
            artifacts=artifacts,
            gateway=gateway,
            llm=llm,
            skills=skills,
            providers=resolved,
            run_manifest=run_manifest,
            seed=config.seed,
        )
        # Công cụ của miền cần runtime đã lắp (ví dụ locator.suggest cần chỉ mục và adapter). Agent được dựng lười ở lần
        # gọi đầu, nên đăng ký ở đây vẫn kịp.
        domain_tools: Any = getattr(pack.runtime, "tools", None)
        if domain_tools is not None:
            for spec in domain_tools(rt):
                gateway.register(spec)
        handlers: Mapping[str, Any] = pack.runtime.handlers(rt) if pack.runtime else {}
        rt.loop = ExecutionLoop(
            run_id=run_id,
            runner=runner,
            policy=policy,
            store=store,
            trace=trace,
            handlers=handlers,
            budget=config.budget,
            tasks=reg.tasks,
            loop=pack.loop,
            rules=rules,
        )
        return rt
