"""Keep current release instructions and the advertised MCP surface consistent."""
import ast
import json
from pathlib import Path
import re
import tomllib

from contitext import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_current_release_references_and_readme_tools_match():
    package = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    registry = json.loads((ROOT / 'server.json').read_text())
    assert package['version'] == registry['version'] == registry['packages'][0]['version'] == __version__
    paths = [ROOT / 'README.md', ROOT / 'SECURITY.md', *sorted((ROOT / 'docs').glob('*.md'))]
    for path in paths:
        if path.name == 'roadmap.md':
            continue  # Roadmap headings intentionally describe historical releases.
        versions = re.findall(r'(?:contitext==|--branch v|Contitext |the v)(\d+\.\d+\.\d+)', path.read_text())
        assert all(v == __version__ for v in versions), path
    tree = ast.parse((ROOT / 'src/contitext/mcp_server.py').read_text())
    tools = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'tool':
                    tools.update(k.value.value for k in decorator.keywords if k.arg == 'name')
    advertised = set(re.findall(r'^\| `((?:project|context)_[a-z_]+)` \|', (ROOT / 'README.md').read_text(), re.M))
    assert advertised == tools and len(tools) == 8


def test_onboarding_links_resolve_and_reader_is_opt_in():
    import yaml
    for path in [ROOT / 'README.md', *sorted((ROOT / 'docs').glob('*.md'))]:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('https:', 'http:', '#', 'mailto:')):
                continue
            assert (path.parent / target.split('#')[0]).is_file(), (path, target)
    compose = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    assert compose['services']['reader']['profiles'] == ['reader']
    assert 'ports' not in compose['services']['reader']
    assert compose['services']['reader']['restart'] == 'unless-stopped'
    assert 'reader-vault' in (ROOT / '.gitignore').read_text()
    assert 'reader-vault' in (ROOT / '.dockerignore').read_text()
