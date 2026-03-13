from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path


def _load_scraper_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "cola_registry_scraper.py"
    spec = importlib.util.spec_from_file_location("cola_registry_scraper", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_out_dir_is_repo_root_data_cola_raw_with_datestamp():
    module = _load_scraper_module()
    fixed_day = date(2026, 3, 13)
    expected = Path(module.__file__).resolve().parents[1] / "data" / "cola_raw" / "20260313_run"
    assert module._default_out_dir(today=fixed_day) == expected


def test_arg_parser_default_out_dir_uses_default_helper():
    module = _load_scraper_module()
    parser = module.build_arg_parser()
    defaults = parser.parse_args([])
    assert Path(defaults.out_dir) == module._default_out_dir()
