"""Canonical dashboard reads and reversible, ID-based organization metadata."""
from __future__ import annotations

import hashlib
import json
import re

from .utils import atomic_write, file_lock
from .vault import ENTRY_RE, SESSION_RE, SESSION_ID_RE

METADATA_PATH = '/dashboard-metadata.md'


def metadata(manager):
    path = manager.vault.resolve(METADATA_PATH)
    if not path.exists():
        return {}
    content = path.read_text(encoding='utf-8')
    match = re.search(r'```json\n(.*?)\n```', content, re.S)
    if not match:
        raise ValueError('Dashboard metadata is malformed; no changes were made.')
    data = json.loads(match.group(1))
    if not isinstance(data, dict) or any(
        not isinstance(value, dict)
        or any(not isinstance(value.get(key, []), list)
               or any(not isinstance(item, str) for item in value.get(key, []))
               for key in ('tags', 'links')) for value in data.values()
    ):
        raise ValueError('Dashboard metadata has an invalid record.')
    return data


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def detail(manager, memory_id):
    row = manager.index.by_id(memory_id)
    if not row:
        raise KeyError('Memory no longer exists. Refresh the library.')
    content = manager.vault.read(row['path'])
    source = None
    if row['kind'] == 'session':
        for block in SESSION_RE.finditer(content):
            marker = SESSION_ID_RE.search(block.group())
            if marker and marker.group('id') == memory_id:
                source = block.group().strip()
                break
    else:
        for line in content.splitlines():
            match = ENTRY_RE.match(line)
            if match and match.group('id') == memory_id:
                source = line
                row['text'] = match.group('text')
                break
    if source is None:
        raise ValueError('This indexed memory is missing from its source file. Reindex the vault.')
    data = metadata(manager)
    own = data.get(memory_id, {})
    title = re.search(r'^\*\*Session title:\*\*\s*(.+)', source, re.M)
    row.update(source=source, title=title.group(1) if title else row['subject'].replace('-', ' '),
               display=source if row['kind'] == 'session' else row['text'],
               tags=own.get('tags', []), links=own.get('links', []),
               metadata_revision=revision(own),
               source_tags=sorted(set(re.findall(r'(?<!\w)#([\w-]+)', source))),
               source_links=re.findall(r'\[\[([^\]]+)\]\]', source),
               backlinks=[key for key, value in data.items() if memory_id in value.get('links', [])])
    return row


def save_metadata(manager, memory_id, body):
    if not manager.index.by_id(memory_id):
        raise KeyError('Memory no longer exists.')
    tags, links = body.get('tags'), body.get('links')
    if not isinstance(tags, list) or not isinstance(links, list) or len(tags) > 50 or len(links) > 100:
        raise ValueError('Provide up to 50 tags and 100 links.')
    if any(not isinstance(tag, str) or not re.fullmatch(r'[\w-]{1,64}', tag) for tag in tags):
        raise ValueError('Tags use letters, numbers, underscores or hyphens (up to 64 characters).')
    if any(not isinstance(link, str) or link == memory_id or not manager.index.by_id(link) for link in links):
        raise ValueError('Choose existing memories other than this memory.')
    path = manager.vault.resolve(METADATA_PATH)
    with file_lock(path):
        data = metadata(manager)
        if body.get('revision') != revision(data.get(memory_id, {})):
            return {'status': 'conflict', 'error': 'Tags or links changed elsewhere. Reload before saving.'}
        data[memory_id] = {'tags': sorted(set(tags)), 'links': list(dict.fromkeys(links))}
        atomic_write(path, '# Dashboard organization\n\nUser-added tags and directed memory-ID links. '
                     'Source memory content is unchanged.\n\n```json\n'
                     + json.dumps(data, ensure_ascii=False, indent=2) + '\n```\n')
    return {'status': 'updated', 'memory': detail(manager, memory_id)}
