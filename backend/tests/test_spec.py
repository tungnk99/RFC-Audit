"""RBS, kiểm tra từ vựng, Oracle compiler, so khớp hai luồng (M2)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import ADAPTER_DIR
from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
from rfcv.domains.rfc_protocol.payloads import Outcome
from rfcv.domains.rfc_protocol.spec.oracle_compiler import (
    CompiledOracle,
    ObservedEvent,
    OracleCompileError,
    compile_oracle,
    instantiate_random,
)
from rfcv.domains.rfc_protocol.spec.rbs import Call, RbsSyntaxError, parse_rbs
from rfcv.domains.rfc_protocol.spec.reconcile import reconcile
from rfcv.domains.rfc_protocol.spec.vocabulary import check

BASE = """requirement TLS13-0042 from RFC8446§5.2#p4s3 modal MUST type B
actor server
state connected
trigger receive(record) where record.length > 16640
expect send_alert(record_overflow) then close within 2000ms
forbid send(application_data)
variants boundary(record.length, 16641), max(record.length), random(record.length, k=3)
"""


def ev(name: str, *args: str, t: int = 10) -> ObservedEvent:
    return ObservedEvent(name=name, args=args, t_ms=t)


def test_parse_example() -> None:
    rbs = parse_rbs(BASE)
    assert rbs.modal == "MUST" and rbs.rtype == "B" and rbs.state == "connected"
    assert rbs.trigger == Call(name="receive", args=("record",))
    assert rbs.where is not None and rbs.where.value == 16640
    assert [str(c) for c in rbs.expect] == ["send_alert(record_overflow)", "close"]
    assert rbs.within_ms == 2000
    assert [v.kind for v in rbs.variants] == ["boundary", "max", "random"]


def test_multiword_modal_and_alternatives() -> None:
    text = BASE.replace("modal MUST", "modal MUST NOT").replace(
        "forbid send(application_data)", "forbid send(application_data)\naccept_alternatives close"
    )
    rbs = parse_rbs(text)
    assert rbs.modal == "MUST NOT" and rbs.accept_alternatives == (Call(name="close"),)


@pytest.mark.parametrize(
    "bad",
    [
        BASE.replace("type B", "type E"),
        BASE.replace("variants", "variant"),
        BASE + "; rm -rf /",
        BASE.replace("within 2000ms", "within soon"),
    ],
)
def test_syntax_errors(bad: str) -> None:
    with pytest.raises(RbsSyntaxError):
        parse_rbs(bad)


def test_vocabulary_check(manifest: AdapterManifest) -> None:
    vocab = to_vocabulary(manifest)
    assert check(parse_rbs(BASE), vocab) == []
    errors = check(parse_rbs(BASE.replace("record_overflow", "made_up_alert").replace("connected", "dancing")), vocab)
    assert any("made_up_alert" in e for e in errors) and any("dancing" in e for e in errors)
    # expect chứa send_alert thì phải là loại B
    assert any("loại B" in e for e in check(parse_rbs(BASE.replace("type B", "type A")), vocab))


def test_boundary_must_be_on_the_trigger_side(manifest: AdapterManifest) -> None:
    errors = check(
        parse_rbs(BASE.replace("boundary(record.length, 16641)", "boundary(record.length, 16640)")),
        to_vocabulary(manifest),
    )
    assert any("phía kích hoạt" in e for e in errors)


def test_compile_rejects_out_of_vocabulary(manifest: AdapterManifest) -> None:
    with pytest.raises(OracleCompileError):
        compile_oracle(parse_rbs(BASE.replace("record.length > 16640", "record.weight > 1")), to_vocabulary(manifest))


def test_compiled_variants(oracle: CompiledOracle) -> None:
    names = {v.name: v for v in oracle.variants}
    assert names["at_limit:record.length=16640"].variant_class == "control"
    assert names["max:record.length=65535"].value == 65535
    rnd = names["random:record.length"]
    assert (rnd.lo, rnd.hi, rnd.k) == (16641, 65535, 6) and rnd.strategy == "stratified"
    assert oracle.required_variant_names == {
        "at_limit:record.length=16640",
        "boundary:record.length=16641",
        "max:record.length=65535",
    }
    assert oracle.random_k == rnd.expected_count and oracle.valid_random_k > 0


def test_not_equal_has_control_and_never_samples_the_valid_value(manifest: AdapterManifest) -> None:
    """`where f != v`: v là giá trị hợp lệ duy nhất, nên là ca đối chứng và không bao giờ được lấy mẫu phía kích hoạt."""
    text = BASE.replace("record.length > 16640", "record.length != 8").replace(
        "boundary(record.length, 16641), max(record.length), random(record.length, k=3)",
        "boundary(record.length, 9), random(record.length, k=40, stratified)",
    )
    oracle = compile_oracle(parse_rbs(text), to_vocabulary(manifest))
    control = next(v for v in oracle.variants if v.variant_class == "control")
    assert control.value == 8 and oracle.side_of("record.length", 8) == "valid"
    rnd = next(v for v in oracle.variants if v.variant_class == "random")
    assert 8 not in rnd.special
    assert all(8 not in instantiate_random(rnd, seed) for seed in range(50))


def test_equal_samples_only_the_trigger_value(manifest: AdapterManifest) -> None:
    text = BASE.replace("record.length > 16640", "record.length == 0").replace(
        "boundary(record.length, 16641), max(record.length), random(record.length, k=3)", "random(record.length, k=2)"
    )
    oracle = compile_oracle(parse_rbs(text), to_vocabulary(manifest))
    rnd = next(v for v in oracle.variants if v.variant_class == "random")
    assert (rnd.lo, rnd.hi) == (0, 0)
    assert not any(v.variant_class == "control" for v in oracle.variants)


def test_oracle_hash_is_stable(manifest: AdapterManifest, oracle: CompiledOracle) -> None:
    text = (ADAPTER_DIR / "examples" / "TLS13-0042.rbs").read_text(encoding="utf-8")
    again = compile_oracle(parse_rbs(text), to_vocabulary(manifest))
    assert again.oracle_hash == oracle.oracle_hash


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([ev("send_alert", "record_overflow"), ev("close", t=20)], Outcome.PASS),
        ([ev("send_alert", "decode_error"), ev("close")], Outcome.FAIL),  # cảnh báo sai (ví dụ K3)
        ([ev("send_alert", "record_overflow")], Outcome.FAIL),  # không đóng kết nối
        ([ev("close"), ev("send_alert", "record_overflow")], Outcome.FAIL),  # sai thứ tự
        ([ev("send_alert", "record_overflow", t=2500), ev("close", t=2600)], Outcome.FAIL),  # quá thời hạn
        ([ev("send", "application_data"), ev("send_alert", "record_overflow"), ev("close")], Outcome.FAIL),
        ([], Outcome.FAIL),
    ],
)
def test_oracle_evaluate(oracle: CompiledOracle, events: list[ObservedEvent], expected: Outcome) -> None:
    assert oracle.evaluate(events) is expected


def test_control_variant_expects_acceptance(oracle: CompiledOracle) -> None:
    assert oracle.evaluate_control([]) is Outcome.PASS
    assert oracle.evaluate_control([ev("send_alert", "record_overflow")]) is Outcome.FAIL


@given(st.integers(min_value=0, max_value=2**32))
def test_random_variants_in_domain_and_reproducible(oracle: CompiledOracle, seed: int) -> None:
    rnd = next(v for v in oracle.variants if v.variant_class == "random")
    values = instantiate_random(rnd, seed)
    assert values == instantiate_random(rnd, seed)
    assert len(values) == rnd.k and all(16641 <= v <= 65535 for v in values)


def test_reconcile_two_streams() -> None:
    a = parse_rbs(BASE)
    b = parse_rbs(
        BASE.replace("TLS13-0042", "TLS13-9999").replace(
            "boundary(record.length, 16641), max(record.length), random(record.length, k=3)",
            "random(record.length, k=3), max(record.length), boundary(record.length, 16641)",
        )
    )
    assert reconcile(a, b).agree
    c = parse_rbs(BASE.replace("record_overflow", "decode_error"))
    result = reconcile(a, c)
    assert not result.agree and result.diffs == ("expect",)


# ---------------------------------------------------------------- biến thể phân tầng và phía hợp lệ

STRONG = BASE.replace(
    "variants boundary(record.length, 16641), max(record.length), random(record.length, k=3)",
    "variants boundary(record.length, 16641), max(record.length), "
    "random(record.length, k=6, stratified), valid_random(record.length, k=6), probe(record.length, budget=24)",
)


def strong_oracle(manifest: AdapterManifest) -> CompiledOracle:
    return compile_oracle(parse_rbs(STRONG), to_vocabulary(manifest))


def test_new_variant_syntax_parses_and_old_syntax_is_unchanged() -> None:
    rbs = parse_rbs(STRONG)
    kinds = [(v.kind, v.stratified, v.k, v.budget) for v in rbs.variants]
    assert ("random", True, 6, None) in kinds and ("valid_random", True, 6, None) in kinds
    assert ("probe", False, None, 24) in kinds
    old = parse_rbs(BASE)
    assert [(v.kind, v.stratified) for v in old.variants][-1] == ("random", False)


def test_valid_random_and_probe_need_a_where_clause_to_know_the_valid_side(manifest: AdapterManifest) -> None:
    no_where = STRONG.replace(" where record.length > 16640", "")
    with pytest.raises(OracleCompileError, match="where"):
        compile_oracle(parse_rbs(no_where), to_vocabulary(manifest))
    with pytest.raises(OracleCompileError, match="k >= 1"):
        compile_oracle(parse_rbs(STRONG.replace("k=6, stratified", "k=0, stratified")), to_vocabulary(manifest))


def test_stratified_oracle_has_both_sides_and_excludes_canonical_values(manifest: AdapterManifest) -> None:
    o = strong_oracle(manifest)
    by_class = {v.variant_class: v for v in o.variants if v.variant_class in ("random", "valid_random", "probe")}
    trig, valid = by_class["random"], by_class["valid_random"]
    assert (trig.lo, trig.hi, trig.side) == (16641, 65535, "trigger")
    assert (valid.lo, valid.hi, valid.side) == (0, 16640, "valid")
    for v in (trig, valid):
        assert set(v.exclude) >= {16640, 16641, 65535}  # đối chứng, biên, max/canonical
        assert not set(v.special) & set(v.exclude)
        assert v.special == tuple(sorted(v.special))
    assert 0 in valid.special and 1 in valid.special  # đầu mút phía hợp lệ luôn được thử
    assert 32767 in trig.special or 32768 in trig.special  # biên nhị phân phía vi phạm
    assert o.random_k == trig.expected_count and o.valid_random_k == valid.expected_count
    assert o.valid_random_k > 6  # tầng cộng giá trị đặc biệt


def test_side_of_follows_the_where_clause(manifest: AdapterManifest) -> None:
    o = strong_oracle(manifest)
    assert o.side_of("record.length", 16640) == "valid"
    assert o.side_of("record.length", 16641) == "trigger"
    assert o.side_of("record.length", 0) == "valid"
    assert o.side_of("other.field", 5) == "trigger"


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=2**32))
def test_stratified_samples_cover_the_range_and_are_reproducible(seed: int) -> None:
    from rfcv.domains.rfc_protocol.spec.oracle_compiler import ConcreteVariant, instantiate_samples

    v = ConcreteVariant(
        name="random:f",
        variant_class="random",
        field="f",
        k=8,
        lo=100,
        hi=60000,
        strategy="stratified",
        special=(100, 255, 256, 60000),
        exclude=(16641, 65535, 300),
    )
    samples = instantiate_samples(v, seed)
    assert samples == instantiate_samples(v, seed)  # tái lập
    strata = [val for suffix, val in samples if suffix.startswith("#")]
    assert len(strata) == 8
    assert all(100 <= val <= 60000 and val not in v.exclude for val in strata)
    span = 60000 - 100 + 1
    for i, val in enumerate(strata):  # mỗi tầng có đúng một mẫu nằm trong tầng của nó
        assert 100 + i * span // 8 <= val <= 100 + (i + 1) * span // 8 - 1
    assert [val for suffix, val in samples if suffix.startswith("@")] == [100, 255, 256, 60000]


def test_different_seeds_give_different_samples_and_names_are_unique(manifest: AdapterManifest) -> None:
    from rfcv.domains.rfc_protocol.spec.oracle_compiler import instantiate_samples

    trig = next(v for v in strong_oracle(manifest).variants if v.variant_class == "random")
    a, b = instantiate_samples(trig, 1), instantiate_samples(trig, 2)
    assert [x for _, x in a] != [x for _, x in b]
    assert len({suffix for suffix, _ in a}) == len(a)


def test_hash_prng_is_stable_across_versions() -> None:
    """Giá trị vàng: nếu đổi thì replay cũ không tái lập được nữa, phải được phát hiện."""
    from rfcv.common.prng import hash_randint

    assert [hash_randint(0, 65535, "stratum", 7, "random:record.length", i) for i in range(3)] == [
        hash_randint(0, 65535, "stratum", 7, "random:record.length", i) for i in range(3)
    ]
    assert hash_randint(0, 65535, "golden", 1) == 53583
