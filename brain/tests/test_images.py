"""The container image: non-root, no secret inside, and the Brain runs a scenario in it with no network. Skipped without Docker or the image."""

import json
import shutil
import subprocess

import pytest

IMAGE = "city-brain/brain:dev"


def docker(*args, timeout=240):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


pytestmark = pytest.mark.skipif(shutil.which("docker") is None or docker("image", "inspect", IMAGE).returncode != 0,
                                reason="needs Docker and the image (docker build -t city-brain/brain:dev .)")


def test_the_brain_image_runs_as_a_non_root_user():
    user = docker("image", "inspect", IMAGE, "--format", "{{.Config.User}}").stdout.strip()
    uid = docker("run", "--rm", "--network", "none", "--entrypoint", "id", IMAGE, "-u").stdout.strip()

    assert user == "brain" and uid == "10001"


def test_the_brain_image_holds_no_env_secret():
    env = json.loads(docker("image", "inspect", IMAGE, "--format", "{{json .Config.Env}}").stdout)

    # GPG_KEY is the public fingerprint of the key that signs Python releases, set by the base image: not a secret
    assert not [e for e in env if e.split("=")[0] != "GPG_KEY" and any(k in e.split("=")[0] for k in ("SECRET", "KEY", "TOKEN", "PASSWORD"))]
    history = docker("history", "--no-trunc", IMAGE).stdout
    assert "GROQ_API_KEY" not in history and ".env" not in history.replace(".envrc", "")


def test_t14_passes_inside_the_image_with_no_network():
    result = docker("run", "--rm", "--network", "none", IMAGE, "scenario", "t14", "--inproc", "--speed", "0", "--quiet")

    assert result.returncode == 0 and "PASSED" in result.stdout, result.stdout[-400:] + result.stderr[-400:]


def test_the_image_starts_with_the_embedding_model_already_in_it():
    result = docker("run", "--rm", "--network", "none", "--entrypoint", "python", IMAGE, "-c",
                    "from brain.knowledge.embedding import make_embedder; from brain.config import ModelsConfig; e,n=make_embedder(ModelsConfig().embeddings); print(e.name)")

    assert "fastembed" in result.stdout, result.stdout + result.stderr[-300:]
