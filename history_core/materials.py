"""Local, revision-bound accomplishment notes. No publisher or model calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from history_core.evidence import redact_text, selection_bundle

FIELDS = {'title': 120, 'result': 2000, 'problem': 2000, 'steps': 3000, 'lesson': 2000}


def _clean(value):
    value = redact_text(value)
    # Remove common home-directory identities, including WSL and Windows forms.
    return re.sub(r'(?:/home/[^/\s]+|/Users/[^/\s]+|/root|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)(?=[/\\\s]|$)', '[HOME]', value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _block(value):
    fence = '`' * max(3, max((len(run) + 1 for run in re.findall(r'`+', value)), default=0))
    return fence + 'text\n' + value + '\n' + fence


def preview_material(indexers, selections, fields):
    if not isinstance(fields, dict):
        raise ValueError('material_fields_required')
    clean = {}
    for key, limit in FIELDS.items():
        value = fields.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('material_field_limit')
        clean[key] = _clean(value.strip())
    if not clean['title'] or not clean['result']:
        raise ValueError('material_title_result_required')
    bundle = selection_bundle(indexers, selections)
    items = []
    identities = set()
    for item in bundle['items']:
        identity = {key: item.get(key) for key in ('system', 'source', 'store_id', 'session_id', 'message_index', 'evidence_id')}
        identity_key = _digest(identity)
        if identity_key in identities:
            continue
        identities.add(identity_key)
        items.append({**identity, **{key: item.get(key) for key in ('content_revision', 'context_revision', 'binding', 'representation')}, 'text': _clean(item['text'])})
    items.sort(key=_digest)
    material_id = _digest(sorted(identities))[:24]
    revision = _digest({'fields': clean, 'items': items})
    sections = ['# 成果素材（待核实）', f'素材 ID：{material_id}', f'修订：{revision}',
                '> 历史记录仅供参考，完成声明不等于独立验证。发布前请人工核对事实、隐私与引用。']
    for key, label in [('title', '标题'), ('result', '完成了什么'), ('problem', '原来的问题'), ('steps', '关键过程'), ('lesson', '可复用的经验')]:
        if clean[key]:
            sections.extend(['## ' + label, _block(clean[key])])
    sections.append('## 来源证据')
    for number, item in enumerate(items, 1):
        metadata = {key: value for key, value in item.items() if key != 'text'}
        sections.extend([f'### 片段 {number}', _block(json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + '\n\n' + item['text'])])
    return {'schema_version': 'history.material.v1', 'material_id': material_id, 'revision': revision,
            'filename': f'{material_id}-{revision[:24]}.md', 'markdown': '\n\n'.join(sections) + '\n',
            'status': 'needs_review', 'historical_verification': 'unknown',
            'redaction_notice': '已过滤常见密钥和用户主目录标识；不保证识别所有隐私，请人工检查预览。'}


def export_material(root, material, expected_revision):
    if not root:
        raise ValueError('material_export_not_configured')
    if expected_revision != material['revision']:
        raise ValueError('material_preview_changed')
    root = Path(root).expanduser().absolute()
    # The configured destination is trusted, but do not follow replaced symlinks.
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError('material_directory_symlink')
    root.mkdir(parents=True, exist_ok=True)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        filename = material['filename']
        payload = material['markdown'].encode('utf-8')
        # Fully write before publishing; link is atomic and never replaces a file.
        temporary = '.material-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
            status = 'created'
        except FileExistsError:
            try:
                fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(len(payload) + 1) != payload:
                        raise ValueError('material_existing_file_changed')
            except OSError as exc:
                raise ValueError('material_existing_file_changed') from exc
            status = 'already_exists'
        return {'status': status, 'filename': filename, 'destination': str(root), 'material_id': material['material_id']}
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)
