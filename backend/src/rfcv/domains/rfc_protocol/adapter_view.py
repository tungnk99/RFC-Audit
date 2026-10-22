"""Cách miền RFC giao thức diễn giải phần đặc thù trong bản kê adapter: từ vựng hành vi, miền giá trị, quy tắc nhất
quán."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.spec.vocabulary import ConsistencyRule, FieldDomain, Vocabulary

# Khoá cũ của adapter TLS, giữ để tương thích: mỗi khoá là một miền tham số của chữ ký sự kiện.
_LEGACY_ENUMS = {"alerts": "code", "content_types": "content_type", "handshake_msgs": "msg_type"}


class ProtocolVocabularySpec(BaseModel):
    """Các khoá của `vocabulary` trong adapter.yaml mà miền này hiểu. Khoá lạ bị từ chối để bắt lỗi gõ sai.

    `enums` là cách chung cho mọi giao thức: tên tham số trong chữ ký sự kiện → các giá trị được phép, ví dụ
    `respond(rcode)` với `rcode: [noerror, formerr]` (DNS) hay `send_goaway(error_code)` (HTTP/2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[str, ...]
    states: tuple[str, ...]
    enums: dict[str, tuple[str, ...]] = Field(default_factory=dict[str, tuple[str, ...]])
    alerts: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    handshake_msgs: tuple[str, ...] = ()

    def all_enums(self) -> dict[str, tuple[str, ...]]:
        out = dict(self.enums)
        for key, param in _LEGACY_ENUMS.items():
            values: tuple[str, ...] = getattr(self, key)
            if values:
                if param in out:
                    raise ValueError(f"miền '{param}' khai báo hai lần (enums.{param} và {key})")
                out[param] = values
        return out


def vocabulary_spec(manifest: AdapterManifest) -> ProtocolVocabularySpec:
    return ProtocolVocabularySpec.model_validate(manifest.vocabulary)


def to_vocabulary(manifest: AdapterManifest) -> Vocabulary:
    v = vocabulary_spec(manifest)
    return Vocabulary(
        events=v.events,
        states=v.states,
        enums=v.all_enums(),
        field_domains={k: FieldDomain.model_validate(d) for k, d in manifest.field_domains.items()},
        consistency_rules=tuple(ConsistencyRule.model_validate(r) for r in manifest.consistency_rules),
    )


def vocabulary_terms(manifest: AdapterManifest) -> frozenset[str]:
    """Các giá trị agent được phép nhắc tới; mọi chuỗi quan sát ngoài tập này bị thay bằng hằng đã đối chiếu.

    Gồm tên sự kiện, trạng thái, giá trị enum và mọi lời gọi một tham số có miền hữu hạn, ví dụ
    `send_alert(record_overflow)` hay `respond(formerr)`."""
    v = vocabulary_spec(manifest)
    vocab = to_vocabulary(manifest)
    sigs = vocab.signatures()
    calls = {
        f"{name}({value})"
        for name, variants in sigs.items()
        for params in variants
        if len(params) == 1 and params[0] in vocab.enums
        for value in vocab.enums[params[0]]
    }
    values = {value for values in vocab.enums.values() for value in values}
    return frozenset({*sigs, *v.states, *values, *calls})
