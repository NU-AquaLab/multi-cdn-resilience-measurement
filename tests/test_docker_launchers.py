"""Exercise launchers with a fake Docker executable; never start measurements."""

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = {
    "bash_video.sh": "collect-vod",
    "bash_live_streaming.sh": "collect-live",
    "bash_live_streaming_fallbacks.sh": "fallback-live",
    "bash_vod_fallbacks.sh": "fallback-vod",
    "bash_vod_fallbacks_iterative.sh": "fallback-iterative",
}


@pytest.fixture
def launcher_env(tmp_path, monkeypatch):
    # Paths with spaces catch accidental shell splitting.
    experiment = tmp_path / "experiment with spaces"
    experiment.mkdir()
    cookie = experiment / "session cookies.pkl"
    cookie.write_bytes(b"test placeholder, not a real cookie pickle")
    config = experiment / ".env"
    config.write_text(
        "DB_NAME=test\nDB_USER=test\nDB_PASSWORD=example-password\n"
        "DB_HOST=database.example\nHEADLESS=0\n"
        "TIKTOK_COOKIE_FILE=session cookies.pkl\nOUTPUT_DIR=measurement results\n"
    )
    vpn_config = experiment / ".env.vpn"
    vpn_config.write_text(
        "VPN_SERVICE_PROVIDER=surfshark\nWIREGUARD_PRIVATE_KEY=example-key\n"
    )
    countries = experiment / "countries.txt"
    countries.write_text("# Test countries\n\nUnited States\nUnited Kingdom\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    logfile = tmp_path / "docker.jsonl"
    fake_docker = bindir / "docker"
    fake_docker.write_text("""#!/usr/bin/env python3
import json
import os
import sys
import time

args = sys.argv[1:]
with open(os.environ["DOCKER_TEST_LOG"], "a") as output:
    output.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    sys.exit(int(os.getenv("DOCKER_TEST_IMAGE_MISSING", "0")))
if args[:2] == ["container", "inspect"]:
    sys.exit(1)
if args and args[0] == "inspect":
    print(os.getenv("DOCKER_TEST_HEALTH", "running healthy"))
if args and args[0] == "run" and "--device" in args:
    print("example-vpn-container-id")
elif args and args[0] == "run":
    time.sleep(float(os.getenv("DOCKER_TEST_RUN_SLEEP", "0")))
    sys.exit(int(os.getenv("DOCKER_TEST_RUN_STATUS", "0")))
""")
    fake_docker.chmod(0o755)
    env = dict(os.environ)
    for key in (
        "DOCKER_IMAGE",
        "VPN_CONTAINER",
        "CONTAINER_NAME",
        "VPN_IMAGE",
        "VPN_READY_TIMEOUT",
        "LOG_LEVEL",
        "XAUTHORITY",
        "TIKTOK_COOKIE_FILE",
        "OUTPUT_DIR",
        "LIVE_CATEGORIES_FILE",
        "HEADLESS",
        "VPN_PROVIDER",
    ):
        env.pop(key, None)
    env.update(
        ENV_FILE=str(config),
        VPN_ENV_FILE=str(vpn_config),
        PATH=f"{bindir}:{os.environ['PATH']}",
        DOCKER_TEST_LOG=str(logfile),
    )
    return env, experiment, countries, logfile


def run_script(name, env, *args):
    return subprocess.run(
        ["bash", str(ROOT / name), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def docker_calls(logfile):
    return (
        [json.loads(line) for line in logfile.read_text().splitlines()]
        if logfile.exists()
        else []
    )


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_wrapper_help_requires_no_credentials(wrapper, launcher_env):
    env, _, _, logfile = launcher_env
    env["ENV_FILE"] = "/missing/config"
    result = run_script(wrapper, env, "--help")
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert not logfile.exists()


@pytest.mark.parametrize("wrapper,workflow", WRAPPERS.items())
def test_dry_run_has_correct_workflow_mounts_and_capabilities(
    wrapper, workflow, launcher_env
):
    env, experiment, _, logfile = launcher_env
    result = run_script(wrapper, env, "--dry-run")
    assert result.returncode == 0, result.stderr
    args = shlex.split(result.stdout.strip())
    assert args[:2] == ["docker", "run"]
    assert args[-1] == workflow
    assert "CHROME_BINARY=/usr/bin/chromium" in args
    assert (
        f"type=bind,source={experiment}/measurement results,target=/work/results"
        in args
    )
    assert ("--cap-add=NET_ADMIN" in args) == workflow.startswith("fallback-")
    if workflow.startswith("fallback-"):
        assert "MEASUREMENT_OS=linux" in args
    if workflow != "fallback-live":
        cookie_mount = next(
            arg for arg in args if "source=" in arg and "session cookies.pkl" in arg
        )
        assert cookie_mount.endswith(",readonly") == (workflow != "collect-vod")
    assert "example-password" not in result.stdout
    assert not (experiment / "measurement results").exists()
    assert not logfile.exists()


def test_custom_categories_and_exported_paths(launcher_env):
    env, experiment, _, _ = launcher_env
    categories = experiment / "custom categories.json"
    categories.write_text('["https://www.tiktok.com/live/gaming"]')
    env.update(
        LIVE_CATEGORIES_FILE=categories.name,
        OUTPUT_DIR="other results",
        DB_PASSWORD="not-in-command",
    )
    result = run_script("bash_live_streaming_fallbacks.sh", env, "--dry-run")
    assert result.returncode == 0, result.stderr
    args = shlex.split(result.stdout.strip())
    assert (
        f"type=bind,source={categories},target=/work/categories.json,readonly" in args
    )
    assert f"type=bind,source={experiment}/other results,target=/work/results" in args
    assert "DB_PASSWORD" in args
    assert "not-in-command" not in result.stdout


def test_missing_cookies_fail_before_docker(launcher_env):
    env, experiment, _, logfile = launcher_env
    (experiment / "session cookies.pkl").unlink()
    result = run_script("bash_live_streaming.sh", env)
    assert result.returncode != 0
    assert "Cookie file not found" in result.stderr
    assert not logfile.exists()


def test_env_file_is_not_executed_as_shell(launcher_env):
    env, experiment, _, _ = launcher_env
    marker = experiment / "unexpected-command"
    with Path(env["ENV_FILE"]).open("a") as config:
        config.write(f"OUTPUT_DIR=$(touch {marker})\n")
    result = run_script("bash_live_streaming_fallbacks.sh", env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_existing_vpn_container_is_reused_but_not_managed(launcher_env):
    env, _, _, logfile = launcher_env
    env["VPN_CONTAINER"] = "my-vpn"
    result = run_script("bash_vod_fallbacks.sh", env)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(logfile)
    run = next(args for args in calls if args[0] == "run")
    assert run[run.index("--network") + 1] == "container:my-vpn"
    assert "--add-host" not in run
    assert not any(args[0] == "rm" for args in calls)


def test_missing_image_is_built_from_repo_root(launcher_env):
    env, _, _, logfile = launcher_env
    env["DOCKER_TEST_IMAGE_MISSING"] = "1"
    result = run_script("bash_live_streaming.sh", env)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(logfile)
    build = next(args for args in calls if args[0] == "build")
    assert build[-1] == str(ROOT)
    assert build[build.index("-f") + 1] == str(ROOT / "docker/Dockerfile")


def test_measurement_exit_status_is_preserved(launcher_env):
    env, _, _, _ = launcher_env
    env["DOCKER_TEST_RUN_STATUS"] = "17"
    assert run_script("bash_live_streaming.sh", env).returncode == 17


def test_vpn_batch_waits_for_health_and_cleans_up_each_country(launcher_env):
    env, _, countries, logfile = launcher_env
    result = run_script(
        "scripts/run_vpn_measurements.sh", env, "fallback-live", str(countries)
    )
    assert result.returncode == 0, result.stderr
    calls = docker_calls(logfile)
    vpn_runs = [args for args in calls if args[0] == "run" and "--device" in args]
    measurements = [
        args for args in calls if args[0] == "run" and "--device" not in args
    ]
    assert len(vpn_runs) == len(measurements) == 2
    for vpn, measurement, country in zip(
        vpn_runs, measurements, ["United States", "United Kingdom"], strict=True
    ):
        name = vpn[vpn.index("--name") + 1]
        assert f"SERVER_COUNTRIES={country}" in vpn
        assert f"container:{name}" in measurement
        assert any(
            args[0] == "inspect" and args[-1] == name
            for args in calls[: calls.index(measurement)]
        )
        assert ["rm", "-f", name] in calls
    assert "example-key" not in result.stdout


def test_unhealthy_vpn_never_starts_measurement_and_is_cleaned_up(launcher_env):
    env, _, countries, logfile = launcher_env
    env["DOCKER_TEST_HEALTH"] = "running unhealthy"
    result = run_script(
        "scripts/run_vpn_measurements.sh", env, "fallback-live", str(countries)
    )
    assert result.returncode != 0
    calls = docker_calls(logfile)
    assert not any(args[0] == "run" and "--device" not in args for args in calls)
    vpn = next(args for args in calls if args[0] == "run")
    assert ["rm", "-f", vpn[vpn.index("--name") + 1]] in calls


def test_vpn_batch_failure_stops_batch_and_cleans_up_both_containers(launcher_env):
    env, _, countries, logfile = launcher_env
    env["DOCKER_TEST_RUN_STATUS"] = "19"
    result = run_script(
        "scripts/run_vpn_measurements.sh", env, "fallback-vod", str(countries)
    )
    assert result.returncode == 19, result.stderr
    calls = docker_calls(logfile)
    runs = [args for args in calls if args[0] == "run"]
    assert len(runs) == 2  # Only the first country's VPN and measurement.
    for args in runs:
        assert ["rm", "-f", args[args.index("--name") + 1]] in calls


def test_vpn_dry_run_does_not_call_docker(launcher_env):
    env, _, countries, logfile = launcher_env
    result = run_script(
        "scripts/run_vpn_measurements.sh",
        env,
        "collect-live",
        str(countries),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "SERVER_COUNTRIES=United" in result.stdout
    assert "example-key" not in result.stdout
    assert not logfile.exists()


def test_vpn_timeout_cleans_up_without_starting_measurements(launcher_env):
    env, _, countries, logfile = launcher_env
    env.update(DOCKER_TEST_HEALTH="running starting", VPN_READY_TIMEOUT="1")
    result = run_script(
        "scripts/run_vpn_measurements.sh", env, "fallback-live", str(countries)
    )
    assert result.returncode != 0
    assert "did not become healthy" in result.stderr
    calls = docker_calls(logfile)
    assert not any(args[0] == "run" and "--device" not in args for args in calls)
    assert any(args[0] == "rm" for args in calls)


def test_vpn_termination_cleans_up_active_containers(launcher_env):
    env, _, countries, logfile = launcher_env
    env["DOCKER_TEST_RUN_SLEEP"] = "30"
    process = subprocess.Popen(
        [
            "bash",
            str(ROOT / "scripts/run_vpn_measurements.sh"),
            "fallback-live",
            str(countries),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            calls = docker_calls(logfile)
            if any(args[0] == "run" and "--device" not in args for args in calls):
                break
            time.sleep(0.02)
        else:
            pytest.fail("Mock measurement did not start")
        process.terminate()
        _, error = process.communicate(timeout=5)
        assert process.returncode == 143, error
        calls = docker_calls(logfile)
        for args in [args for args in calls if args[0] == "run"]:
            assert ["rm", "-f", args[args.index("--name") + 1]] in calls
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
