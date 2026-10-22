"""Thêm một giao thức mới (BL-82, QS-40, YD-10): chỉ bằng dữ liệu của adapter và một backend, không sửa lõi, agent hay quy tắc.

Giao thức tổng hợp "toyline" (một dòng lệnh, một dòng trả lời) cố ý khác TLS, DNS, HTTP/2, QUIC, SSH ở mọi chỗ mà miền từng gắn với
giao thức đầu tiên: tên sự kiện phản ứng (`reply(status)`), miền giá trị, thao tác DSL, không có bắt tay. Test này gãy nếu ai đó lại
đưa giả định về một giao thức cụ thể vào phần dùng chung.
"""

from __future__ import annotations

from pathlib import Path

from helpers import REQ, t1, t3
from rfcv.adapters.checker import Status, check_adapter, passed
from rfcv.adapters.manifest import load_manifest
from rfcv.backends.base import EXPECT_ARGS, DslBackend
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary, vocabulary_terms
from rfcv.domains.rfc_protocol.payloads import Outcome
from rfcv.domains.rfc_protocol.rules import ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec
from rfcv.domains.rfc_protocol.spec.oracle_compiler import ObservedEvent, compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.evidence.verdict_engine import assess
from rfcv.plugins import Registry
from test_verdict_engine import chain

MANIFEST = """\
adapter: toyline
version: 0.1.0
backend: toyline-runner
domain: rfc_protocol
verdict_profile: rfc-protocol@3
specs:
  - {doc: RFC9999, role: primary}
vocabulary:
  events: [receive(line), reply(status), hangup]
  states: [idle]
  enums:
    status: [ok, too_long, bad_verb]
field_domains:
  line.length: {min: 0, max: 4096, canonical: [513]}
sut:
  repo: https://example.invalid/toyline
  recipe: sut/toyline.yaml
code_scope:
  include: ["src/**"]
"""

RBS = """\
requirement TOY-0001 from RFC9999§2#p1s2 modal MUST type B
actor server
state idle
trigger receive(line) where line.length > 512
expect reply(too_long) then hangup within 500ms
variants boundary(line.length, 513), max(line.length), random(line.length, k=3, stratified), valid_random(line.length, k=3)
"""

TEMPLATE = """\
id: toyline.line.too_long
requirement_types: [B]
rfc_refs: ["RFC9999§2"]
runner: toyline-runner
steps:
  - {op: connect}
  - {op: send_raw_record, args: {length: "$line.length", body: zeros}}
  - {op: expect, args: {within_ms: 500}}
bindings: {line.length: from_variant}
"""


class ToylineBackend(DslBackend):
    name = "toyline-runner"
    runner = "socket"
    dsl = DslSpec(
        ops={
            "connect": frozenset(),
            "send_raw_record": frozenset({"length", "body"}),
            "expect": EXPECT_ARGS,
        },
        values={"body": frozenset({"zeros", "random"})},
    )


def make_adapter(tmp_path: Path) -> Path:
    root = tmp_path / "adapters" / "toyline"
    for rel, text in {
        "adapter.yaml": MANIFEST,
        "examples/TOY-0001.rbs": RBS,
        "templates/too_long.yaml": TEMPLATE,
        "sut/toyline.yaml": "implementation: toyline\n",
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def registry() -> Registry:
    reg = Registry.build(freeze=False)
    reg.register_backend("toyline-runner", lambda manifest, config: ToylineBackend())
    return reg.freeze()


def test_a_new_protocol_passes_the_adapter_checker_with_no_core_change(tmp_path: Path) -> None:
    items = check_adapter(make_adapter(tmp_path), registry=registry())
    assert passed(items), [(i.check, i.detail) for i in items if i.status is Status.FAIL]
    checks = {i.check for i in items}
    assert {"form.rbs_example:TOY-0001.rbs", "form.template_dsl:too_long.yaml", "form.vocabulary"} <= checks


def test_its_rbs_compiles_and_the_oracle_judges_its_own_reaction_vocabulary(tmp_path: Path) -> None:
    manifest = load_manifest(make_adapter(tmp_path))
    oracle = compile_oracle(parse_rbs(RBS), to_vocabulary(manifest))
    assert {"reply(too_long)", "reply(ok)", "too_long"} <= vocabulary_terms(manifest)
    right = [ObservedEvent(name="reply", args=("too_long",), t_ms=5), ObservedEvent(name="hangup", t_ms=9)]
    assert oracle.evaluate(right) is Outcome.PASS
    assert oracle.evaluate([ObservedEvent(name="reply", args=("bad_verb",), t_ms=5)]) is Outcome.FAIL


def test_the_verdict_engine_compares_reactions_of_any_protocol() -> None:
    """Mâu thuẫn giữa mã (T1) và kiểm thử (T3) về mã lỗi không phụ thuộc tên sự kiện của giao thức."""
    req = ProtocolRequirement(REQ, "B", "MUST")
    clash = chain([t1(observed="reply(too_long)"), t3(outcome=Outcome.PASS, alert="bad_verb")])
    assert any(c.kind == "T1_vs_T3" for c in assess(req, clash).conflicts)
