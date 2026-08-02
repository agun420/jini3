from pathlib import Path

from daybreak.core.hashing import canonical_json_bytes, canonical_sha256, file_sha256


def test_canonical_json_is_order_independent() -> None:
    left = {"b": 2, "a": "✅"}
    right = {"a": "✅", "b": 2}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_bytes(b"daybreak")
    assert file_sha256(path) == "d64d7197dff235323da087b13e122219b17852a175d3a796e297e04f2e8b62cf"
