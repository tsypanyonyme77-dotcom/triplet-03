"""The student model: an XGBoost scorer trained on an LLM teacher's choices (data/student.json).

It scores each candidate place on its own (probability the teacher would pick it); the decider
normalises the scores over the candidates and samples.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from twin.engine.decision.schema import feature_names, features

MODEL_PATH = Path(__file__).parent / "data" / "student.json"


class Student:
    def __init__(self, booster) -> None:
        import xgboost as xgb  # noqa: PLC0415  (optional: `uv sync --group decision`)

        self._xgb = xgb
        self._booster = booster
        self.model_features: list[str] = list(booster.feature_names or [])

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "Student":
        import xgboost as xgb  # noqa: PLC0415

        booster = xgb.Booster()
        booster.load_model(str(path))
        student = cls(booster)
        if student.model_features != feature_names():
            raise ValueError("student model was trained on different features than schema.py describes")
        return student

    def scores(self, situation: dict) -> np.ndarray:
        """Probability per candidate, in the situation's candidate order."""
        matrix = self._xgb.DMatrix(features(situation), feature_names=feature_names())
        return self._booster.predict(matrix)
