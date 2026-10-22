"""Cách miền RFC giao thức diễn giải phần đặc thù trong bản kê adapter: từ vựng hành vi, miền giá trị, quy tắc nhất
quán."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.spec.vocabulary import ConsistencyRule, FieldDomain, Vocabulary


class ProtocolVocabularySpec(BaseModel):
    """Các khoá của `vocabulary` trong adapter.yaml mà miền này hiểu. Khoá lạ bị từ chối để bắt lỗi gõ sai."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[str, ...]
    states: tuple[str, ...]
    alerts: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    handshake_msgs: tuple[str, ...] = ()


def vocabulary_spec(manifest: AdapterManifest) -> ProtocolVocabularySpec:
    return ProtocolVocabularySpec.model_validate(manifest.vocabulary)


def to_vocabulary(manifest: AdapterManifest) -> Vocabulary:
    v = vocabulary_spec(manifest)
    enums: dict[str, tuple[str, ...]] = {}
    if v.alerts:
        enums["code"] = v.alerts
    if v.content_types:
        enums["content_type"] = v.content_types
    if v.handshake_msgs:
        enums["msg_type"] = v.handshake_msgs
    return Vocabulary(
        events=v.events,
        states=v.states,
        enums=enums,
        field_domains={k: FieldDomain.model_validate(d) for k, d in manifest.field_domains.items()},
        consistency_rules=tuple(ConsistencyRule.model_validate(r) for r in manifest.consistency_rules),
    )


def vocabulary_terms(manifest: AdapterManifest) -> frozenset[str]:
    """Các giá trị agent được phép nhắc tới; mọi chuỗi quan sát ngoài tập này bị thay bằng hằng đã đối chiếu."""
    v = vocabulary_spec(manifest)
    sigs = to_vocabulary(manifest).signatures()
    calls = {f"send_alert({a})" for a in v.alerts}
    return frozenset({*sigs, *v.states, *v.alerts, *v.content_types, *v.handshake_msgs, *calls})
