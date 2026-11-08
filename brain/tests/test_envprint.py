"""`brain env`: the facts that decide whether two runs are comparable, in one place and with no secret in it."""

import json
import os

from brain.cli import build_parser
from brain.envprint import fingerprint_env


def test_the_fingerprint_names_every_pinned_thing():
    env = fingerprint_env()

    for key in ("brain", "commit", "lock_sha256", "python", "platform", "packages", "embedder", "models", "overlay", "clock", "pythonhashseed"):
        assert key in env, key
    assert {"langgraph", "langchain", "mcp", "numpy", "neo4j", "networkx"} <= set(env["packages"])
    assert len(env["lock_sha256"]) == 64


def test_the_fingerprint_is_stable_in_one_checkout():
    assert fingerprint_env() == fingerprint_env()


def test_a_changed_lock_file_changes_the_fingerprint(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("a")
    first = fingerprint_env(lock=lock)["lock_sha256"]
    lock.write_text("b")

    assert fingerprint_env(lock=lock)["lock_sha256"] != first


def test_the_fingerprint_contains_no_secret():
    os.environ["BRAIN_HMAC_SECRET"] = "very-secret-value-123"
    os.environ["GROQ_API_KEY"] = "gsk_not-for-output"

    text = json.dumps(fingerprint_env())

    assert "very-secret-value-123" not in text and "gsk_not-for-output" not in text


def test_the_env_command_exists():
    assert build_parser().parse_args(["env"]).command == "env"
