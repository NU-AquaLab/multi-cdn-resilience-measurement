"""Exercise the installed package from an unrelated working directory."""

import os
import subprocess
import sys


def test_module_help_outside_checkout(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "measure_tiktok", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "fallback-iterative" in result.stdout


def test_imports_have_no_measurement_side_effects(tmp_path):
    code = """
import importlib
import pkgutil
import socket
from unittest.mock import patch
import measure_tiktok

def fail(*args, **kwargs):
    raise AssertionError("Import attempted an external operation")

with patch("socket.socket.connect", fail), patch("requests.get", fail), \\
     patch("psycopg2.connect", fail), patch("selenium.webdriver.Chrome", fail), \\
     patch("subprocess.run", fail):
    for module in pkgutil.walk_packages(measure_tiktok.__path__, "measure_tiktok."):
        importlib.import_module(module.name)
"""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True)
