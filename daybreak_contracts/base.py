from pydantic import BaseModel, ConfigDict


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        use_enum_values=True,
        allow_inf_nan=False,
    )
