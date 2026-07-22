from __future__ import annotations

import numpy as np
import pandas as pd

from satn.tags import tag_values


def test_tag_values_canonicalises_collection_round_trips_and_missing_scalars() -> None:
    assert tag_values(np.array(["primary", "secondary"])) == ["primary", "secondary"]
    assert tag_values(("A4", "A36")) == ["A4", "A36"]
    assert tag_values({"A36", "A4"}) == ["A36", "A4"]
    assert tag_values("['ncn', 'lcn']") == ["ncn", "lcn"]
    assert tag_values(pd.NA) == []
    assert tag_values(float("nan")) == []
