"""Schema export helpers."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .models import FeatureContext, FeatureSnapshot


def write_feature_schemas(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    models: dict[str, type[BaseModel]] = {
        "feature_context.schema.json": FeatureContext,
        "feature_snapshot.schema.json": FeatureSnapshot,
    }
    for name, model in models.items():
        (destination / name).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
