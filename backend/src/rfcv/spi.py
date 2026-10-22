"""Giao diện nhà cung cấp dịch vụ (SPI): các hợp đồng mà plugin và domain pack phải tuân theo.

Lõi của rfcv không biết RFC, TLS hay bất kỳ miền nào. Mọi thứ đặc thù miền đi vào qua
`DomainPack` và các plugin đăng ký ở `rfcv.plugins.Registry`. Mô-đun này chỉ chứa kiểu dữ liệu,
không import thành phần lõi nào (chỉ tham chiếu kiểu khi kiểm tra tĩnh), nên mọi nơi có thể nhập nó.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from rfcv.evidence.verdict_engine import RuleSet


class Polarity(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    NEUTRAL = "NEUTRAL"


class Effect(StrEnum):
    """Tác động của một công cụ. Quy định ranh giới quyền: chỉ READ và SANDBOXED_RUN được phép mặc định."""

    READ = "read"
    SANDBOXED_RUN = "sandboxed_run"  # chạy trong sandbox không mạng, huỷ sau mỗi lần
    WRITE = "write"
    NETWORK = "network"
    HOST_EXEC = "host_exec"


SAFE_EFFECTS: frozenset[Effect] = frozenset({Effect.READ, Effect.SANDBOXED_RUN})


@dataclass(frozen=True)
class ToolDescriptor:
    """Khai báo một công cụ để Policy store kiểm tra lúc nạp (hàm xử lý được cấp riêng lúc lắp ráp)."""

    name: str
    effect: Effect = Effect.READ
    reads_untrusted: bool = False  # True: công cụ đọc dữ liệu không tin cậy, chỉ agent vùng cách ly được có


@dataclass(frozen=True)
class EvidenceKind:
    """Một loại bằng chứng: mô hình payload, tầng, ai được ghi, cách tính chiều và cách tóm tắt cho agent."""

    name: str
    tier: str
    model: type[BaseModel]
    producers: frozenset[str]
    polarity: Callable[[Any], Polarity]
    summarize: Callable[[Any, frozenset[str]], dict[str, Any]]
    # Bản tóm tắt phình theo số bằng chứng (BL-12): hàng "thường" (không có gì đáng chú ý) chỉ khác nhau ở `fold_fields`
    # được gộp thành một hàng kèm `count` và danh sách giá trị. Hàng khác thường, hay được nhãn và xung đột trích dẫn,
    # vẫn đứng riêng.
    is_routine: Callable[[Any], bool] | None = None
    fold_fields: tuple[str, ...] = ()
    version: int = 1
    # upgrades[n] nâng payload (dict) từ phiên bản n lên n + 1 khi đọc dữ liệu cũ.
    upgrades: Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]] = field(
        default_factory=dict[int, Callable[[dict[str, Any]], dict[str, Any]]]
    )


@dataclass(frozen=True)
class TaskDefinition:
    """Một kiểu nhiệm vụ Planner được giao: đích cố định và tham số có kiểu."""

    name: str
    target_role: str
    params_model: type[BaseModel]
    deterministic: bool = False  # True: do thành phần tất định xử lý, không gọi LLM


@dataclass(frozen=True)
class LoopPolicy:
    """Các quy ước của vòng điều tra mà miền có thể đổi."""

    planner_role: str = "planner"
    critique_task: str | None = "CRITIQUE"
    # Nhãn tạm cần một lần phản biện sạch trước khi dừng (mặc định chỉ COMPLIANT, vì dễ sai nhất).
    critique_before: frozenset[str] = frozenset({"COMPLIANT"})
    # Mã lý do Planner phải khai khi cố ý làm khác sổ tay; dùng để ghi trace "đi theo hay chệch sổ tay".
    deviation_code: str | None = None


# ---- Sổ tay điều tra (kinh nghiệm dẫn đường) ---------------------------------------------------------
# Sổ tay là DỮ LIỆU khai báo, không phải mã: đọc được, băm được thành phiên bản, kiểm được lúc đóng băng registry, và
# in thành lời nhắc từ cùng một nguồn. Mọi trường điều kiện là chuỗi hữu hạn, nên không mở đường cho văn bản tự do.

# Nguồn dữ liệu mà một gợi ý được phép gắn vào tham số nhiệm vụ (tập cố định, lõi hiểu được).
BIND_SOURCES: frozenset[str] = frozenset(
    {"missing.variants", "missing.first_variant", "conflict.aspect", "critique.evidence_id"}
)


@dataclass(frozen=True)
class When:
    """Điều kiện khớp tình huống. Trường để mặc định nghĩa là không ràng buộc."""

    rtypes: frozenset[str] = frozenset()
    provisional: frozenset[str] = frozenset()  # nhãn tạm; "NONE" = chưa có nhãn tạm
    need: str | None = None  # có mục còn thiếu thuộc tầng này
    missing: bool | None = None  # True/False: còn / không còn mục thiếu
    conflict: bool | None = None
    critique: str | None = None  # "none" | "clean" | "issues"
    critique_kind: str | None = None  # có vấn đề thuộc loại này
    first_round: bool | None = None
    not_dispatched: frozenset[str] = frozenset()  # các kiểu nhiệm vụ chưa từng được giao


@dataclass(frozen=True)
class Suggest:
    """Một nhiệm vụ nên giao: kiểu, tham số tĩnh, và tham số lấy từ tình huống (`bind`: tên tham số -> nguồn)."""

    task_type: str
    params: Mapping[str, Any] = field(default_factory=dict[str, Any])
    bind: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class PlaybookRule:
    """Quy tắc kinh nghiệm: gặp tình huống `when` thì nên giao `suggest` (hoặc dừng nếu `stop`)."""

    id: str
    when: When
    suggest: tuple[Suggest, ...] = ()
    rationale_code: str = ""
    stop: bool = False
    priority: int = 100  # nhỏ hơn khớp trước
    note: str = ""  # câu giải thích ngắn, in vào lời nhắc


@dataclass(frozen=True)
class AgentSpec:
    """Khai báo (bằng MÃ) một agent của miền: vùng tin cậy, schema nó trả, nhiệm vụ nó nhận, và đã nối vào luồng chạy chưa.

    Hồ sơ vai trò và lời nhắc là DỮ LIỆU nằm ngoài mã nguồn, ở `<agents_root>/<name>/{role.yaml,prompt.md}`. Vùng tin cậy và
    schema đầu ra được khai báo ở đây và `role.yaml` phải khớp: dữ liệu cấu hình không được đổi kiến trúc.
    Thành phần tất định (không LLM) như Locator khai báo ở đây cho bản đồ đầy đủ, nhưng không có hồ sơ (`zone` rỗng).
    """

    name: str
    stage: str  # planning | investigation | pre (trước điều tra) | post (sau kết luận) | deterministic
    wired: bool  # đã có đường chạy thật (nhiệm vụ có handler, hoặc hub gọi trực tiếp)
    zone: str = ""  # "privileged" | "quarantine"; rỗng = thành phần tất định, không có role.yaml
    output_schema: str = ""
    tasks: Sequence[TaskDefinition] = ()
    schemas: Mapping[str, type[BaseModel]] = field(default_factory=dict[str, type[BaseModel]])
    summary: str = ""

    @property
    def has_role(self) -> bool:
        return bool(self.zone)


class DomainRuntime(Protocol):
    """Phần chạy của một miền: dựng handler cho nhiệm vụ và nạp danh sách yêu cầu cần điều tra."""

    def required_providers(self) -> Sequence[str]: ...

    def handlers(self, rt: Any) -> Mapping[str, Any]: ...

    def investigations(self, rt: Any, source: Path) -> Sequence[Any]: ...


@dataclass(frozen=True)
class DomainPack:
    """Gói miền: mọi tri thức đặc thù một loại đặc tả (ví dụ giao thức mạng theo RFC)."""

    name: str
    version: str
    evidence_kinds: Sequence[EvidenceKind]
    schemas: Mapping[str, type[BaseModel]]
    tasks: Sequence[TaskDefinition]
    rationale_codes: Sequence[str]
    rule_sets: Sequence[RuleSet]
    tools: Sequence[ToolDescriptor]
    required_roles: Sequence[str]
    # Miền có thể tổ chức theo agent (mỗi agent một thư mục) hoặc theo hai thư mục roles/ và prompts/.
    roles_dir: Path | None = None
    prompts_dir: Path | None = None
    agents: Sequence[AgentSpec] = ()
    loop: LoopPolicy = field(default_factory=LoopPolicy)
    # Các kiểm tra riêng của miền cho Adapter checker: (adapter_dir, manifest) -> list[CheckItem]
    adapter_checks: Sequence[Callable[[Path, Any], list[Any]]] = ()
    # Lệnh CLI do miền đóng góp: tên nhóm lệnh -> typer.Typer
    cli_apps: Mapping[str, Any] = field(default_factory=dict[str, Any])
    runtime: DomainRuntime | None = None
    # Sổ tay điều tra của miền (xem PlaybookRule); rỗng nghĩa là miền không đưa kinh nghiệm dẫn đường.
    playbook: Sequence[PlaybookRule] = ()
    # Loại vấn đề Verifier được nêu (`Critique@1.issues[].kind`); rỗng thì `kind` là chuỗi tự do.
    critique_kinds: Sequence[str] = ()
