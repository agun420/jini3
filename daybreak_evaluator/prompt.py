from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.input_models import DaybreakInput
from daybreak_contracts.serialization import canonical_json_bytes

_RESOURCE_NAME = "resources/Project_Daybreak_v6.3_Final.md"
EXPECTED_SPEC_SHA256 = (
    "0872a5c3e168d4698819b2a4470d02566173a61caeecd4bacaa401e5f6a0fbf2"  # pragma: allowlist secret
)


class PromptBundle:
    def __init__(self, *, directive: str, payload_text: str, spec_hash: str) -> None:
        self.directive = directive
        self.payload_text = payload_text
        self.spec_hash = spec_hash

    @property
    def prompt_hash(self) -> str:
        return canonical_sha256(
            {
                "directive": self.directive,
                "payload_text": self.payload_text,
                "spec_hash": self.spec_hash,
            }
        )


def load_spec_text(spec_path: str | Path) -> tuple[str, str, str]:
    """Load an explicit spec path or the immutable wheel-bundled fallback."""
    path = Path(spec_path)
    if path.is_file():
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != EXPECTED_SPEC_SHA256:
            raise ValueError("evaluator specification hash does not match pinned v6.3")
        return raw.decode("utf-8"), digest, str(path)
    resource = files("daybreak_evaluator").joinpath(_RESOURCE_NAME)
    raw = resource.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SPEC_SHA256:
        raise ValueError("bundled evaluator specification failed integrity verification")
    return raw.decode("utf-8"), digest, f"package:{_RESOURCE_NAME}"


def spec_is_available(spec_path: str | Path) -> bool:
    try:
        load_spec_text(spec_path)
        return True
    except (FileNotFoundError, ModuleNotFoundError, UnicodeDecodeError, ValueError):
        return False


def spec_sha256(spec_path: str | Path) -> str:
    return load_spec_text(spec_path)[1]


def build_prompt(spec_path: str | Path, payload: DaybreakInput) -> PromptBundle:
    directive, digest, _source = load_spec_text(spec_path)
    payload_text = canonical_json_bytes(payload).decode("utf-8")
    return PromptBundle(
        directive=directive,
        payload_text=payload_text,
        spec_hash=digest,
    )
