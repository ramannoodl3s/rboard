# This file is part of R Board (a fork of BeeRef), GPL-3.0-or-later.

"""MCP server (stdio) giving Claude tools for the board open in R Board.

Standard library only, and it imports nothing from R Board, so it starts
instantly and runs with any Python 3.8+. Run it by path:

    python claude_mcp.py [--bridge PATH_TO_claude-bridge.json]

Each tool call is forwarded to the running R Board (see claude_bridge.py)
over 127.0.0.1; this process holds no board data itself.
"""

import json
import os
import socket
import sys

VERSION = '1'
TIMEOUT = 60

_IDS = {'type': 'array', 'items': {'type': 'integer'},
        'description': 'image numbers, e.g. [12, 40]'}
_PAGE = {'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}

TOOLS = [
    {'name': 'board',
     'description': 'Overview of the open R Board: image count, most '
                    'common labels and tags, sub boards, selection.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'find',
     'description': 'Search images by words in their tags, labels '
                    '(colour, kind, mood, style, subject), recognised '
                    'text, notes, filenames and links, plus images that '
                    'look like the words. -word excludes. Empty query '
                    'lists all. One line per image; default limit 20.',
     'inputSchema': {'type': 'object', 'properties': {
         'query': {'type': 'string'}, **_PAGE}}},
    {'name': 'similar',
     'description': 'Images that look like image #id, most similar first.',
     'inputSchema': {'type': 'object', 'properties': {
         'id': {'type': 'integer'}, **_PAGE}, 'required': ['id']}},
    {'name': 'details',
     'description': 'Everything known about images: file, source link, '
                    'size, all labels, tags, full text, note, links.',
     'inputSchema': {'type': 'object', 'properties': {'ids': _IDS},
                     'required': ['ids']}},
    {'name': 'look',
     'description': 'See images: one gives a 256px thumbnail, several '
                    '(up to 16) a numbered contact sheet. Costs image '
                    'tokens; use find/details first.',
     'inputSchema': {'type': 'object', 'properties': {'ids': _IDS},
                     'required': ['ids']}},
    {'name': 'act',
     'description': 'Change the board (undoable): show = select and zoom '
                    'to; tag/untag (text = tag); note (text = note, '
                    'empty clears); subboard (text = title).',
     'inputSchema': {'type': 'object', 'properties': {
         'action': {'type': 'string',
                    'enum': ['show', 'tag', 'untag', 'note', 'subboard']},
         'ids': _IDS, 'text': {'type': 'string'}},
         'required': ['action', 'ids']}},
]


def default_bridge_path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~/.config')
    return os.path.join(base, 'R Board', 'claude-bridge.json')


def call_app(bridge_path, tool, args):
    try:
        with open(bridge_path, encoding='utf-8') as f:
            info = json.load(f)
    except (OSError, ValueError):
        return {'error': 'R Board is not open (or "let Claude use the '
                         'board" is off in its settings menu)'}
    request = json.dumps({'token': info.get('token'), 'tool': tool,
                          'args': args}).encode('utf-8') + b'\n'
    try:
        with socket.create_connection(('127.0.0.1', int(info['port'])),
                                      timeout=TIMEOUT) as sock:
            sock.sendall(request)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if chunk.endswith(b'\n'):
                    break
    except (OSError, KeyError, ValueError):
        return {'error': 'R Board is not open (could not reach it)'}
    try:
        return json.loads(b''.join(chunks))
    except ValueError:
        return {'error': 'R Board closed the connection'}


def tool_result(reply):
    if 'error' in reply:
        return {'content': [{'type': 'text', 'text': reply['error']}],
                'isError': True}
    content = [{'type': 'text', 'text': reply.get('text', '')}]
    if reply.get('image'):
        content.append({'type': 'image', 'data': reply['image'],
                        'mimeType': 'image/jpeg'})
    return {'content': content}


def respond(msg, bridge_path):
    method = msg.get('method')
    params = msg.get('params') or {}
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion',
                                              '2025-06-18'),
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'rboard', 'version': VERSION}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        return tool_result(call_app(bridge_path, params.get('name'),
                                    params.get('arguments') or {}))
    raise LookupError(method)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    bridge_path = default_bridge_path()
    if len(argv) >= 2 and argv[0] == '--bridge':
        bridge_path = argv[1]
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if 'id' not in msg:
            continue   # notifications need no reply
        try:
            reply = {'jsonrpc': '2.0', 'id': msg['id'],
                     'result': respond(msg, bridge_path)}
        except LookupError:
            reply = {'jsonrpc': '2.0', 'id': msg['id'],
                     'error': {'code': -32601,
                               'message': f'no method {msg.get("method")}'}}
        out.write(json.dumps(reply).encode('utf-8') + b'\n')
        out.flush()


if __name__ == '__main__':
    main()
