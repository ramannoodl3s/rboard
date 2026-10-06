import json
import os
import zipfile
from unittest.mock import patch

import pytest

from beeref.rboard import plugins


@pytest.fixture
def plugin_dir(tmp_path):
    base = tmp_path / 'plugins'
    with patch('beeref.rboard.plugins.user_dir', return_value=str(base)), \
            patch('beeref.rboard.plugins.source_dir', return_value=None):
        yield base
    for plugin_id in ('demo', 'broken'):
        plugins._loaded.pop(plugin_id, None)
    plugins.actions[:] = [a for a in plugins.actions
                          if a[0].id not in ('demo', 'broken')]
    plugins.services.pop('demo', None)


def make_zip(tmp_path, plugin_id='demo', api=plugins.API_VERSION,
             folder='', code=None, module=None):
    module = module or f'rboard_test_{plugin_id}'
    manifest = {'id': plugin_id, 'name': plugin_id.title(),
                'version': '1.0', 'api': api, 'module': module}
    code = code or ('def register(api):\n'
                    '    api.provide("demo", 42)\n'
                    '    api.add_action("say hi", lambda view: None)\n')
    path = tmp_path / f'{plugin_id}.zip'
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(folder + 'plugin.json', json.dumps(manifest))
        zf.writestr(folder + f'{module}.py', code)
    return str(path)


def test_install_load_and_remove(plugin_dir, tmp_path):
    plugin, restart = plugins.install_zip(make_zip(tmp_path))
    assert not restart
    assert (plugin_dir / 'demo' / 'plugin.json').exists()
    plugin = plugins.load(plugin)
    assert plugin.loaded and plugin.error is None
    assert plugins.services['demo'] == 42
    assert any(label == 'say hi' for p, label, cb in plugins.actions)
    # A running plugin goes at the next start
    assert plugins.remove('demo') is True
    assert 'demo' not in plugins.discover()
    plugins._loaded.pop('demo')
    plugins.apply_pending()
    assert not (plugin_dir / 'demo').exists()


def test_install_from_zip_with_a_top_folder(plugin_dir, tmp_path):
    plugin, _ = plugins.install_zip(make_zip(tmp_path, folder='demo-1.0/'))
    assert (plugin_dir / 'demo' / 'plugin.json').exists()


def test_update_of_running_plugin_waits_for_restart(plugin_dir, tmp_path):
    plugins.load(plugins.install_zip(make_zip(tmp_path))[0])
    plugin, restart = plugins.install_zip(make_zip(tmp_path))
    assert restart
    assert (plugin_dir / 'demo.new').exists()
    plugins._loaded.pop('demo')
    plugins.apply_pending()
    assert not (plugin_dir / 'demo.new').exists()
    assert (plugin_dir / 'demo' / 'plugin.json').exists()


def test_refuses_other_api_version(plugin_dir, tmp_path):
    with pytest.raises(plugins.PluginError):
        plugins.install_zip(make_zip(tmp_path, api=plugins.API_VERSION + 1))
    assert not os.path.exists(plugin_dir / 'demo')


def test_refuses_zip_without_manifest(plugin_dir, tmp_path):
    path = tmp_path / 'x.zip'
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('readme.txt', 'hi')
    with pytest.raises(plugins.PluginError):
        plugins.install_zip(str(path))


def test_broken_plugin_keeps_error(plugin_dir, tmp_path):
    plugin, _ = plugins.install_zip(make_zip(
        tmp_path, 'broken', code='def register(api):\n    1 / 0\n'))
    plugin = plugins.load(plugin)
    assert not plugin.loaded
    assert 'failed to load' in plugin.error
