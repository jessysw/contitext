"""Release metadata must not create unpinned or injectable Homebrew resources."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("update_homebrew", Path(__file__).parents[1] / "scripts/update_homebrew.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def artifact(**changes):
    return {"urls": [{"packagetype": "sdist", "url": "https://files.pythonhosted.org/packages/ab/pkg-1.0.tar.gz", "digests": {"sha256": "a" * 64}, **changes}]}


@pytest.mark.parametrize("version", ["0.8.4rc1", "v0.8.4", "0.8", "1.0.0;echo bad", "1.0.0\n"])
def test_only_stable_version_can_generate_release_formula(version):
    with pytest.raises(ValueError):
        module.stable_version(version)


def test_pypi_source_must_be_unique_checksummed_and_trusted():
    assert module.source(artifact())[1] == "a" * 64
    for changes in ({"url": "http://files.pythonhosted.org/a"}, {"url": "https://evil.example/a"},
                    {"url": 'https://files.pythonhosted.org/packages/#{bad}.tar.gz'},
                    {"digests": {"sha256": "bad"}}, {"yanked": True}):
        with pytest.raises(ValueError):
            module.source(artifact(**changes))
    duplicate = artifact(); duplicate["urls"] *= 2
    with pytest.raises(ValueError):
        module.source(duplicate)


def test_runtime_requirements_use_system_driver_and_exclude_dev_extras():
    info = {"info": {"requires_dist": ["psycopg[binary]>=3.2.10,<4", "mcp>=1.30,<2", 'pytest>=8; extra == "test"']}}
    requirements = module.requirements(info)
    assert requirements == ["psycopg[c]<4,>=3.2.10", "mcp<2,>=1.30"]


def test_resolver_output_must_have_exact_consistent_pins():
    assert module.pins("# generated\npsycopg[c]==3.3.4\n") == {"psycopg": "3.3.4"}
    for text in ("thing>=1", "thing==1.*", "thing @ https://example.com/a", "thing==1\nthing==2"):
        with pytest.raises(ValueError):
            module.pins(text)


def test_formula_has_no_implicit_service_database_or_agent_configuration():
    text = module.render(artifact(), {})
    assert '@URL@' not in text and '@RESOURCES@' not in text
    assert 'virtualenv_install_with_resources' in text
    assert 'psycopg[c]' in text
    for forbidden in ('service do', 'def post_install', 'admin seed', 'hooks install', 'migrate'):
        assert forbidden not in text
