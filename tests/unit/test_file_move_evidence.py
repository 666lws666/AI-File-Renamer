"""Pure strict evidence graphs and explicit history codecs; no file admission."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from src.core import rename_plan as values
from src.models.rename_record import RenameRecord


def contracts():
    for name in ("NativeFileIdentity", "FileMoveEvidence", "validate_native_identity",
                 "validate_move_evidence", "encode_move_evidence", "decode_move_evidence"):
        assert hasattr(values, name), f"{name} contract missing"
    return values.NativeFileIdentity, values.FileMoveEvidence


def graph():
    identity, evidence = contracts()
    return evidence(1, identity(7, 2**63 + 11, 133000000000000000),
                    values.SourceFingerprint(13, 99), ("C:/synthetic",))


def test_evidence_round_trip_and_legacy_default(tmp_path):
    identity, evidence = contracts()
    proof = evidence(1, identity(7, 2**63 + 11, 133000000000000000),
                     values.SourceFingerprint(13, 99), (str(tmp_path),))
    rec = RenameRecord(task_id="synthetic", batch_id="b", old_path=tmp_path/"old.txt",
                       new_path=tmp_path/"new.txt", move_evidence=proof)
    loaded = RenameRecord.from_json_line(rec.to_json_line())
    assert loaded.move_evidence == proof
    assert loaded.task_id == "synthetic" and loaded.batch_id == "b"
    legacy = RenameRecord(old_path=tmp_path/"legacy.txt", new_path=tmp_path/"legacy-new.txt")
    encoded = json.loads(legacy.to_json_line())
    assert encoded.pop("move_evidence") is None
    assert RenameRecord.from_json_line(json.dumps(encoded)).move_evidence is None
    assert RenameRecord.from_json_line(legacy.to_json_line()).move_evidence is None


def test_frozen_graph_and_exact_json_keys():
    proof = graph()
    for obj, field, value in [(proof, "version", 2), (proof.identity, "file_index", 3),
                              (proof.fingerprint, "size_bytes", 4),
                              (proof, "allowed_roots", ("D:/wider",))]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
    assert type(proof.allowed_roots) is tuple
    encoded = values.encode_move_evidence(proof)
    assert encoded == {"version": 1, "identity": {"volume_serial": 7,
        "file_index": 2**63 + 11, "creation_ticks": 133000000000000000},
        "fingerprint": {"size_bytes": 13, "mtime_ns": 99}, "allowed_roots": ["C:/synthetic"]}
    encoded["allowed_roots"].append("D:/untrusted")
    assert proof.allowed_roots == ("C:/synthetic",)


@pytest.mark.parametrize("field,bad", [(field, bad) for field, bits in
    [("volume_serial", 32), ("file_index", 64), ("creation_ticks", 64)]
    for bad in (True, False, -1, 2**bits, 1.0, "1", None)])
def test_identity_exact_integer_ranges(field, bad):
    identity, _ = contracts()
    fields = dict(volume_serial=7, file_index=8, creation_ticks=9)
    fields[field] = bad
    with pytest.raises(ValueError):
        identity(**fields)


def test_identity_range_edges_and_large_json_round_trip():
    identity, evidence = contracts()
    for args in ((0, 0, 0), (2**32-1, 2**64-1, 2**64-1)):
        proof = evidence(1, identity(*args), values.SourceFingerprint(0, 0), ("C:/synthetic",))
        assert values.decode_move_evidence(json.loads(json.dumps(values.encode_move_evidence(proof)))) == proof


@pytest.mark.parametrize("bad", [True, False, 0, 2, -1, 1.0, "1", None])
def test_evidence_version_exact_one(bad):
    identity, evidence = contracts()
    with pytest.raises(ValueError):
        evidence(bad, identity(0, 0, 0), values.SourceFingerprint(0, 0), ("C:/synthetic",))


@pytest.mark.parametrize("bad", [(), [], ("",), ("  ",), ("a\x00b",), ("a"*4097,),
    (1,), ("C:/ROOT", "c:\\root"), tuple(f"C:/r{i}" for i in range(2001))])
def test_roots_graph_rejected(bad):
    identity, evidence = contracts()
    with pytest.raises(ValueError):
        evidence(1, identity(0, 0, 0), values.SourceFingerprint(0, 0), bad)


def test_roots_boundaries_and_subclasses_rejected():
    identity, evidence = contracts()
    class Text(str):
        pass
    class Roots(tuple):
        pass
    class Identity(identity):
        pass
    class Evidence(evidence):
        pass
    class Fingerprint(values.SourceFingerprint):
        pass
    for roots in (("a"*4096,), tuple(f"C:/r{i}" for i in range(2000))):
        assert evidence(1, identity(0, 0, 0), values.SourceFingerprint(0, 0), roots).allowed_roots == roots
    with pytest.raises(ValueError):
        Identity(0, 0, 0)
    with pytest.raises(ValueError):
        Evidence(1, identity(0, 0, 0), values.SourceFingerprint(0, 0), ("C:/synthetic",))
    for fp, roots in [(Fingerprint(0, 0), ("C:/synthetic",)),
                      (values.SourceFingerprint(0, 0), (Text("C:/synthetic"),)),
                      (values.SourceFingerprint(0, 0), Roots(("C:/synthetic",)))]:
        with pytest.raises(ValueError):
            evidence(1, identity(0, 0, 0), fp, roots)


@pytest.mark.parametrize("field,bad", [(field, bad) for field in ("size_bytes", "mtime_ns")
                                     for bad in (True, False, -1, 1.0, "1", None)])
def test_invalid_fingerprint_inside_evidence(field, bad):
    identity, evidence = contracts()
    fields = dict(size_bytes=0, mtime_ns=0)
    fields[field] = bad
    with pytest.raises(ValueError):
        evidence(1, identity(0, 0, 0), values.SourceFingerprint(**fields), ("C:/synthetic",))


@pytest.mark.parametrize("mutation", ["top-extra", "top-missing", "identity-extra", "identity-missing",
    "fingerprint-extra", "fingerprint-missing", "identity-list", "fingerprint-list", "roots-tuple",
    "future", "bool-version", "float-version", "text-index", "bool-fingerprint", "list-top", "null-top"])
def test_decode_strict_malformed_or_coerced_data(mutation):
    data = values.encode_move_evidence(graph())
    if mutation == "top-extra": data["extra"] = 1
    elif mutation == "top-missing": del data["identity"]
    elif mutation == "identity-extra": data["identity"]["extra"] = 1
    elif mutation == "identity-missing": del data["identity"]["creation_ticks"]
    elif mutation == "fingerprint-extra": data["fingerprint"]["extra"] = 1
    elif mutation == "fingerprint-missing": del data["fingerprint"]["mtime_ns"]
    elif mutation == "identity-list": data["identity"] = []
    elif mutation == "fingerprint-list": data["fingerprint"] = []
    elif mutation == "roots-tuple": data["allowed_roots"] = ("C:/synthetic",)
    elif mutation == "future": data["version"] = 2
    elif mutation == "bool-version": data["version"] = True
    elif mutation == "float-version": data["version"] = 1.0
    elif mutation == "text-index": data["identity"]["file_index"] = "1"
    elif mutation == "bool-fingerprint": data["fingerprint"]["size_bytes"] = True
    elif mutation == "list-top": data = []
    elif mutation == "null-top": data = None
    with pytest.raises(ValueError):
        values.decode_move_evidence(data)
    record = RenameRecord(old_path=Path("C:/synthetic/old"), new_path=Path("C:/synthetic/new"))
    line = json.loads(record.to_json_line())
    line["move_evidence"] = data
    if data is not None and mutation != "roots-tuple":
        # JSON represents tuples as arrays; only the direct codec can reject that
        # Python container distinction. Explicit None is a supported no-proof state.
        with pytest.raises(ValueError):
            RenameRecord.from_json_line(json.dumps(line))


@pytest.mark.parametrize("target,field,bad", [("identity", "file_index", True),
    ("identity", "creation_ticks", -1), ("fingerprint", "size_bytes", "13"),
    ("evidence", "version", True), ("evidence", "allowed_roots", ["C:/synthetic"])])
def test_tampered_frozen_graph_revalidated_at_boundaries(target, field, bad):
    proof = graph()
    record = RenameRecord(old_path=Path("C:/synthetic/old"), new_path=Path("C:/synthetic/new"),
                          move_evidence=proof)
    object.__setattr__(proof if target == "evidence" else getattr(proof, target), field, bad)
    for action in (lambda: values.validate_move_evidence(proof),
                   lambda: values.encode_move_evidence(proof), record.to_json_line,
                   lambda: RenameRecord(old_path="old", new_path="new", move_evidence=proof)):
        with pytest.raises(ValueError):
            action()


def test_history_before_validator_rejects_untrusted_dict_without_coercion():
    data = values.encode_move_evidence(graph())
    for bad in (data, True, "proof", [], object()):
        with pytest.raises(ValueError):
            RenameRecord(old_path="old", new_path="new", move_evidence=bad)


def test_pure_construction_codecs_and_legacy_do_not_touch_io(monkeypatch):
    contracts()
    import builtins
    import os
    import socket
    from src.core import safe_file_move as move
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Pure evidence must not invoke I/O")
    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "open", forbidden)
        scoped.setattr(os, "stat", forbidden)
        scoped.setattr(Path, "stat", forbidden)
        scoped.setattr(move, "_open", forbidden)
        scoped.setattr(move, "_nt_create", forbidden)
        scoped.setattr(socket, "create_connection", forbidden)
        proof = graph()
        assert values.decode_move_evidence(values.encode_move_evidence(proof)) == proof
        record = RenameRecord(old_path="C:/synthetic/old", new_path="C:/synthetic/new", move_evidence=proof)
        assert RenameRecord.from_json_line(record.to_json_line()).move_evidence == proof
        legacy = RenameRecord(old_path="C:/synthetic/old", new_path="C:/synthetic/new")
        assert RenameRecord.from_json_line(legacy.to_json_line()).move_evidence is None
    assert calls == []


@pytest.mark.parametrize("target,field", [
    ("identity", "volume_serial"), ("identity", "file_index"), ("identity", "creation_ticks"),
    ("fingerprint", "size_bytes"), ("fingerprint", "mtime_ns"),
    ("evidence", "version"), ("evidence", "identity"), ("evidence", "fingerprint"),
    ("evidence", "allowed_roots"),
    ("identity", None), ("fingerprint", None), ("evidence", None),
])
def test_incomplete_exact_graphs_reject_with_value_error(target, field):
    """Deleted required fields and exact uninitialized graphs cannot bypass trust."""
    proof = graph()
    record = RenameRecord(old_path="old", new_path="new", move_evidence=proof)
    value = proof if target == "evidence" else getattr(proof, target)
    if field is None:
        value = object.__new__(type(value))
        if target == "evidence":
            proof = value
            # Exercise explicit serialization even if field validation was bypassed.
            record = RenameRecord.model_construct(old_path=Path("old"), new_path=Path("new"), move_evidence=proof)
        else:
            object.__setattr__(proof, target, value)
    else:
        object.__delattr__(value, field)
    if target == "identity":
        with pytest.raises(ValueError, match="^invalid_native_file_identity$"):
            values.validate_native_identity(value)
    for action in (lambda: values.validate_move_evidence(proof),
                   lambda: values.encode_move_evidence(proof), record.to_json_line,
                   lambda: RenameRecord(old_path="old", new_path="new", move_evidence=proof)):
        with pytest.raises(ValueError):
            action()
