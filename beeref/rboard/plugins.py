# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Plugins: folders in the settings folder's `plugins`, outside the app,
so they survive app updates.

A plugin is a folder with a `plugin.json`:

    {"id": "ai", "name": "AI features", "version": "0.3.0", "api": 1,
     "module": "rboard_ai", "python": "cp311"}

`module` is imported with the plugin folder (and its `lib` folder, for
bundled libraries) on the path, and its `register(api)` is called with a
PluginAPI. `python` is only needed when `lib` holds compiled code.
"""

import json
import logging
import os
import re
import shutil
import sys
import urllib.request
import zipfile

from beeref import constants


logger = logging.getLogger(__name__)

API_VERSION = 1
PYTHON_TAG = f'cp{sys.version_info.major}{sys.version_info.minor}'
MANIFEST = 'plugin.json'
REMOVE_MARK = '.remove'
NEW_SUFFIX = '.new'
AI_ID = 'ai'
AI_URL = ('https://github.com/ramannoodl3s/rboard/releases/download/'
          'v{version}/R-Board-AI-{version}.zip')

services = {}      # name -> object a plugin provides (e.g. 'ai')
actions = []       # (plugin, label, callback(view)) for the plugins menu
_loaded = {}       # id -> Plugin
_tried = set()     # ids ensure() already looked for


class PluginError(Exception):
    pass


class Plugin:

    def __init__(self, path, manifest, builtin=False):
        self.path = path
        self.manifest = manifest
        self.id = manifest['id']
        self.name = manifest.get('name', self.id)
        self.version = manifest.get('version', '')
        self.description = manifest.get('description', '')
        self.builtin = builtin   # from the source checkout; not removable
        self.error = None
        self.module = None

    @property
    def loaded(self):
        return self.module is not None

    def problem(self):
        """Why this plugin can't run here, or None."""
        if self.manifest.get('api') != API_VERSION:
            return ('made for a different version of R Board; '
                    'install the matching version')
        python = self.manifest.get('python')
        if python and python != PYTHON_TAG:
            return f'needs Python {python}, R Board runs {PYTHON_TAG}'
        if not self.manifest.get('module'):
            return 'plugin.json names no module'


class PluginAPI:
    """What a plugin's register() gets."""

    def __init__(self, plugin, window=None):
        self.plugin = plugin
        self.window = window
        self.app_version = constants.VERSION

    @property
    def view(self):
        return self.window.view if self.window else None

    def add_action(self, label, callback):
        """A menu entry (in plugins, and the add menu) calling
        callback(view)."""
        actions.append((self.plugin, label, callback))

    def provide(self, name, obj):
        services[name] = obj

    def data_dir(self):
        """A folder for the plugin's own files that outlives updates."""
        path = os.path.join(user_dir(), f'{self.plugin.id}-data')
        os.makedirs(path, exist_ok=True)
        return path


# ---------- finding ----------

def user_dir():
    from beeref.config import BeeSettings
    return os.path.join(os.path.dirname(BeeSettings().fileName()),
                        'plugins')


def source_dir():
    """The checkout's own plugins (only when running from source)."""
    if getattr(sys, 'frozen', False):
        return None
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'plugins')
    return path if os.path.isdir(path) else None


def read_manifest(folder):
    with open(os.path.join(folder, MANIFEST), encoding='utf-8') as f:
        manifest = json.load(f)
    check_id(manifest.get('id'))
    return manifest


def check_id(plugin_id):
    if not isinstance(plugin_id, str) or \
            not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,40}', plugin_id):
        raise PluginError(f'bad plugin id: {plugin_id!r}')


def discover():
    """id -> Plugin; installed plugins win over the checkout's."""
    found = {}
    for base, builtin in ((source_dir(), True), (user_dir(), False)):
        if not base or not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if name.endswith(NEW_SUFFIX) or \
                    not os.path.isfile(os.path.join(folder, MANIFEST)) or \
                    os.path.exists(os.path.join(folder, REMOVE_MARK)):
                continue
            try:
                plugin = Plugin(folder, read_manifest(folder), builtin)
            except Exception as e:
                logger.warning(f'Skipping plugin {folder}: {e}')
                continue
            found[plugin.id] = plugin
    return found


def get(plugin_id):
    return _loaded.get(plugin_id) or discover().get(plugin_id)


def all_plugins():
    found = discover()
    found.update(_loaded)
    return sorted(found.values(), key=lambda p: p.name.lower())


# ---------- loading ----------

def load(plugin, window=None):
    """Import and register a plugin; errors are kept on the plugin."""
    import importlib
    if plugin.id in _loaded:
        return _loaded[plugin.id]
    plugin.error = plugin.problem()
    if plugin.error:
        logger.warning(f'Plugin {plugin.id}: {plugin.error}')
        return plugin
    for path in (os.path.join(plugin.path, 'lib'), plugin.path):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    try:
        module = importlib.import_module(plugin.manifest['module'])
        module.register(PluginAPI(plugin, window))
    except Exception as e:
        logger.exception(f'Plugin {plugin.id} failed to load')
        plugin.error = f'failed to load: {e}'
        return plugin
    plugin.module = module
    _loaded[plugin.id] = plugin
    logger.info(f'Loaded plugin {plugin.id} {plugin.version}')
    return plugin


def load_all(window=None):
    _tried.clear()
    apply_pending()
    for plugin in discover().values():
        load(plugin, window)


def ensure(plugin_id, window=None):
    """The loaded plugin, loading it if it's there; else None."""
    plugin = _loaded.get(plugin_id)
    if plugin is None and plugin_id not in _tried:
        _tried.add(plugin_id)
        found = discover().get(plugin_id)
        plugin = found and load(found, window)
    return plugin if plugin and plugin.loaded else None


# ---------- installing ----------

def _zip_root(zf):
    """The folder inside the zip that holds plugin.json ('' or 'x/')."""
    names = zf.namelist()
    if MANIFEST in names:
        return ''
    roots = [n[:-len(MANIFEST)] for n in names
             if n.endswith('/' + MANIFEST) and n.count('/') == 1]
    if len(roots) != 1:
        raise PluginError("that zip isn't an R Board plugin "
                          '(no plugin.json)')
    return roots[0]


def install_zip(path):
    """Install (or update) a plugin from a zip. Returns (plugin,
    needs_restart): a plugin that's already running is swapped in at the
    next start, since its files are in use."""
    with zipfile.ZipFile(path) as zf:
        root = _zip_root(zf)
        manifest = json.loads(zf.read(root + MANIFEST).decode('utf-8'))
        check_id(manifest.get('id'))
        base = user_dir()
        target = os.path.join(base, manifest['id'])
        staging = target + NEW_SUFFIX
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        for info in zf.infolist():
            if not info.filename.startswith(root) or info.is_dir():
                continue
            rel = info.filename[len(root):]
            dest = os.path.normpath(os.path.join(staging, rel))
            if not dest.startswith(os.path.normpath(staging) + os.sep):
                raise PluginError(f'unsafe path in zip: {info.filename}')
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out)
    plugin = Plugin(target, manifest)
    problem = plugin.problem()
    if problem:
        shutil.rmtree(staging, ignore_errors=True)
        raise PluginError(problem)
    if manifest['id'] in _loaded:
        return plugin, True
    try:
        _replace(staging, target)
    except OSError:
        return plugin, True
    _tried.discard(plugin.id)
    return plugin, False


def _replace(staging, target):
    if os.path.exists(target):
        shutil.rmtree(target)
    os.replace(staging, target)


def remove(plugin_id):
    """Remove a plugin. Returns True if it goes at the next start."""
    target = os.path.join(user_dir(), plugin_id)
    if plugin_id not in _loaded:
        try:
            shutil.rmtree(target)
            return False
        except OSError:
            pass
    if os.path.isdir(target):
        open(os.path.join(target, REMOVE_MARK), 'w').close()
    return True


def apply_pending():
    """Finish removals and updates that had to wait for a restart."""
    base = user_dir()
    if not os.path.isdir(base):
        return
    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            if name.endswith(NEW_SUFFIX):
                _replace(path, path[:-len(NEW_SUFFIX)])
            elif os.path.exists(os.path.join(path, REMOVE_MARK)):
                shutil.rmtree(path)
        except OSError as e:
            logger.warning(f'Could not finish plugin change {path}: {e}')


def download(url, target, on_progress=None, is_canceled=lambda: False):
    """Fetch a file to `target`; raises on failure or cancel."""
    request = urllib.request.Request(url, headers={'User-Agent': 'R Board'})
    tmp = target + '.part'
    with urllib.request.urlopen(request, timeout=60) as response, \
            open(tmp, 'wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        done = 0
        while True:
            if is_canceled():
                out.close()
                os.remove(tmp)
                raise PluginError('Download canceled')
            chunk = response.read(1 << 18)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    os.replace(tmp, target)


def ai_url():
    return AI_URL.format(version=constants.VERSION)
