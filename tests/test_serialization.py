from __future__ import annotations

import json

from daybreak_contracts import DaybreakInput
from daybreak_contracts.serialization import canonical_json_bytes, sha256_hex


def test_canonical_hash_is_key_order_independent(approved_input):
    model = DaybreakInput.model_validate_json(json.dumps(approved_input))
    reversed_mapping = dict(reversed(list(model.model_dump(mode="json").items())))
    assert canonical_json_bytes(model) == canonical_json_bytes(reversed_mapping)
    assert sha256_hex(model) == sha256_hex(reversed_mapping)
