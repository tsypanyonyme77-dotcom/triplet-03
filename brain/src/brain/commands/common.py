"""Shared by the commands: the model config with its flags applied, the log folder, the serve config, and the seed list."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from brain import config
from brain.config import ModelsConfig, PartnersConfig


def _models(args: argparse.Namespace) -> ModelsConfig:
    """config/models.yaml, with the command-line overrides applied."""
    models = config.load(ModelsConfig, "models")
    if getattr(args, "llm", False):
        models.team.llm = True
    if getattr(args, "departments", None) is not None:  # scenario, serve and run: the department agents are on unless --no-departments
        models.team.departments = "on" if args.departments else "off"
    if getattr(args, "model", None):
        models.roles = {role: args.model for role in models.roles}
        models.team.llm = True
    if getattr(args, "budget", None):
        models.team.budget_s = args.budget
    if getattr(args, "cassette", None):
        models.team.cassette, models.team.cassette_path = args.cassette_mode, args.cassette
        if args.cassette_mode == "replay":
            models.team.llm = True  # a replay plays the recorded team: no model, no key
    if models.team.llm and models.team.cassette != "replay":
        _check_llm(models)
    return models


def _check_llm(models: ModelsConfig) -> None:
    """Stop before anything starts if a role's model cannot be built: a missing package or API key."""
    try:
        from langchain.chat_models import init_chat_model
    except ImportError:
        sys.exit("error: the LLM team needs the optional packages; run `uv sync --extra llm`")
    for role, spec in models.roles.items():
        try:
            init_chat_model(spec, **models.options_for(role))
        except Exception as error:  # noqa: BLE001 - any model failure is reported as one clear message
            sys.exit(f"error: cannot use {spec} for the '{role}' role ({type(error).__name__}: {error})")


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _log_dir(partners: PartnersConfig) -> Path:
    path = Path(os.environ.get("LOG_DIR", partners.brain.log_dir))
    return path if path.is_absolute() else config.home() / path


def serve_partners(args: argparse.Namespace) -> PartnersConfig:
    """The partners config for `serve`, with the folders from the command line laid over it."""
    partners = config.load(PartnersConfig, "partners", args.config)
    if args.graph:
        partners.graph.backend = args.graph
    if args.episodes:
        partners.brain.episodes_dir = args.episodes
    if args.learned:
        partners.brain.learned_dir = args.learned
    if getattr(args, "approvals", False):
        partners.approval.mode = "human"
    return partners


def _seeds(spec: str, count: int) -> list[int]:
    from brain.variants import HELD_OUT_SEEDS, TRAIN_SEEDS

    if spec == "held-out":
        return list(HELD_OUT_SEEDS)[:count]
    if spec == "train":
        return list(TRAIN_SEEDS)[:count]
    first, _, last = spec.partition("-")
    return list(range(int(first), int(last or first) + 1))
