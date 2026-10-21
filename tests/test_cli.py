"""Help and dispatch must not start a browser or contact a database."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from measure_tiktok import cli


@pytest.mark.parametrize("command", [None, *cli.COMMANDS])
def test_help_exits_before_configuration_or_imports(monkeypatch, command, capsys):
    load = Mock(side_effect=AssertionError("Help must not read credentials"))
    import_module = Mock(side_effect=AssertionError("Help must not load measurements"))
    monkeypatch.setattr(cli, "load_config", load)
    monkeypatch.setattr(cli.importlib, "import_module", import_module)
    args = [command, "--help"] if command else ["--help"]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out
    load.assert_not_called()
    import_module.assert_not_called()


@pytest.mark.parametrize("command", cli.COMMANDS)
def test_dispatch_loads_only_selected_workflow(monkeypatch, command):
    load = Mock()
    validate = Mock()
    run = Mock()
    import_module = Mock(return_value=SimpleNamespace(main=run))
    monkeypatch.setattr(cli, "load_config", load)
    monkeypatch.setattr(cli, "validate_configuration", validate)
    monkeypatch.setattr(cli.importlib, "import_module", import_module)
    assert cli.main(["--config", "experiment.env", command]) == 0
    load.assert_called_once_with("experiment.env")
    validate.assert_called_once_with(command)
    import_module.assert_called_once_with(cli.COMMANDS[command][0])
    run.assert_called_once_with()


def test_missing_configuration_fails_before_workflow_import(monkeypatch, capsys):
    import_module = Mock(side_effect=AssertionError("Should fail before dispatch"))
    monkeypatch.setattr(cli.importlib, "import_module", import_module)
    with pytest.raises(SystemExit) as exc:
        cli.main(["collect-live"])
    assert exc.value.code == 2
    assert "DB_NAME" in capsys.readouterr().err
    import_module.assert_not_called()


def test_missing_cookies_fail_before_workflow_import(monkeypatch, capsys):
    for key in ("DB_NAME", "DB_USER", "DB_HOST"):
        monkeypatch.setenv(key, "test")
    import_module = Mock(side_effect=AssertionError("Should fail before dispatch"))
    monkeypatch.setattr(cli.importlib, "import_module", import_module)
    with pytest.raises(SystemExit) as exc:
        cli.main(["collect-live"])
    assert exc.value.code == 2
    assert "Cookie file is missing" in capsys.readouterr().err
    import_module.assert_not_called()
