"""Public machine capabilities; legacy Web adapters stay private to this facade.

This is an application API boundary, not a sandbox against hostile Python code.
Only explicitly selected sources and a disjoint derived cache are used.
"""
import hashlib
import os
from pathlib import Path

from . import service
from .providers import SOURCES, NATIVE_SOURCES, canonical_source, parser_for, parser_version, include_file, file_suffixes, native_indexer
from .sources import (Indexer, OpenCodeIndexer, HermesStateIndexer,
                      parse_codex_session_file, parse_claude_session_file,
                      parse_openclaw_session_file)


class HistoryReader:
    """Explicit refresh and reads, with no forwarded legacy mutation methods."""

    def __init__(self, source, source_path, data_dir=None, *, validate_tree=True):
        source = canonical_source(source)
        if source not in SOURCES:
            raise ValueError('unsupported_source')
        self.__source = source
        self.__root = Path(source_path).resolve(strict=True)
        self.__native = source in NATIVE_SOURCES
        self.__indexer = None
        self.__cache = None
        self.__page_revision = None
        if validate_tree:
            self.__validate_source()
        else:
            self.__check_root()
        if self.__native:
            self.__indexer = native_indexer(source, self.__root)
        else:
            if data_dir is None:
                raise ValueError('sessions_directory_and_data_dir_required')
            data = Path(data_dir).resolve()
            if data == self.__root or data in self.__root.parents or self.__root in data.parents:
                raise ValueError('source_and_cache_must_be_disjoint')
            # A source-bound subdirectory cannot accidentally reuse another
            # source's cached file paths or the Web's mutable/pinned index.
            key = hashlib.sha256(str(self.__root).encode('utf-8')).hexdigest()
            self.__cache = data / ('machine-%s-%s' % (source, key))
            self.__validate_cache()
            self.__cache.mkdir(parents=True, exist_ok=True)
            self.__indexer = Indexer(self.__root, self.__cache, source,
                parse_file_fn=parser_for(source), file_filter_fn=self.__include,
                parser_version=parser_version(source))

    def __include(self, path):
        return include_file(self.__source, path)

    def __validate_cache(self):
        if self.__cache is None:
            return
        # SQLite may write journal/WAL sidecars: reject linked artifacts too.
        if self.__cache.is_symlink():
            raise ValueError('cache_symlink_not_allowed')
        if self.__cache.exists():
            for p in self.__cache.rglob('*'):
                if p.is_symlink():
                    raise ValueError('cache_symlink_not_allowed')

    def __validate_source(self):
        if self.__root.is_symlink():
            raise ValueError('source_symlink_not_allowed')
        self.__root.stat()
        if self.__native:
            if not self.__root.is_file():
                raise ValueError('native_database_file_required')
            with self.__root.open('rb'):
                pass
            return
        if not self.__root.is_dir():
            raise ValueError('sessions_directory_required')
        def fail(error):
            raise error
        for directory, dirs, files in os.walk(self.__root, followlinks=False, onerror=fail):
            for name in dirs + files:
                p = Path(directory) / name
                if p.is_symlink():
                    raise ValueError('source_symlink_not_allowed')
            for name in files:
                p = Path(directory) / name
                if p.suffix in file_suffixes(self.__source) and self.__include(p):
                    with p.open('rb'):
                        pass

    def __ready(self):
        if self.__indexer is None:
            raise ValueError('reader_closed')
        self.__validate_source()
        self.__validate_cache()

    def refresh(self):
        self.__ready()
        self.__indexer.maybe_update_index(max_age_seconds=0)
        return {'source': self.__source, 'status': 'refreshed', 'native_source_read_only': True}

    def __check_root(self):
        if self.__root.is_symlink():
            raise ValueError('source_symlink_not_allowed')
        if not (self.__root.is_file() if self.__native else self.__root.is_dir()):
            raise ValueError('native_database_file_required' if self.__native else 'sessions_directory_required')

    def health(self):
        if self.__indexer is None:
            raise ValueError('reader_closed')
        self.__check_root()
        if self.__native:
            if not self.__root.is_file():
                raise ValueError('native_database_file_required')
        else:
            if not self.__root.is_dir():
                raise ValueError('sessions_directory_required')
        self.__validate_cache()
        self.__indexer.conn.execute('SELECT 1').fetchone()
        return {'source': self.__source, 'status': 'readable', 'freshness': 'unknown',
                'background_refresh': False, 'refresh_policy': 'explicit'}

    def __revision(self):
        if callable(getattr(self.__indexer, 'source_revision', None)):
            revision = self.__indexer.source_revision()
            if getattr(self.__indexer, '_revision', revision) != revision:
                raise ValueError('source_changed_since_index: refresh required')
        elif self.__native:
            parts = []
            for path in (self.__root, Path(str(self.__root) + '-wal')):
                try:
                    st = path.stat()
                    parts.append((st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino))
                except FileNotFoundError:
                    parts.append(None)
            revision = repr(parts)
        else:
            with self.__indexer.lock:
                revision = self.__indexer.conn.execute("SELECT value FROM reader_state WHERE key = 'revision'").fetchone()[0]
        return hashlib.sha256((self.__source + str(self.__root) + revision).encode()).hexdigest()

    def search(self, *, query=None, limit=20, offset=0, cwd=None, index_revision=None):
        if self.__indexer is None:
            raise ValueError('reader_closed')
        self.__check_root()
        self.__validate_cache()
        before = self.__revision()
        expected = index_revision or (self.__page_revision if offset else None)
        if offset and not expected:
            raise ValueError('index_revision_required: restart from offset 0')
        if expected is not None and expected != before:
            raise ValueError('index_revision_changed: restart from offset 0')
        res = service.search(self.__indexer, query=query, limit=limit, offset=offset, cwd=cwd, stable_order=True)
        if self.__revision() != before:
            raise ValueError('index_revision_changed: restart from offset 0')
        self.__page_revision = before
        res.update(freshness='unknown', index_revision=before, pagination_consistency='revision_bound')
        return res

    def handoff(self, session_id, *, include_plans=False):
        if self.__source == 'mcode':
            raise ValueError('mcode_handoff_unsupported_use_activity')
        if self.__indexer is None:
            raise ValueError('reader_closed')
        self.__check_root()
        self.__validate_cache()
        if not self.__native:
            # Persisted file paths are data, never authority to read elsewhere.
            row = self.__indexer.conn.execute('SELECT file_path FROM sessions WHERE id = ?',
                                             (str(session_id),)).fetchone()
            if row:
                path = Path(row['file_path'])
                if self.__root not in path.parents or not self.__include(path):
                    raise ValueError('cached_source_path_outside_selection')
                curr = path
                while curr != self.__root:
                    if curr.is_symlink():
                        raise ValueError('source_symlink_not_allowed')
                    curr = curr.parent
                if self.__root not in path.resolve(strict=True).parents:
                    raise ValueError('cached_source_path_outside_selection')
                with path.open('rb'):
                    pass
        return service.handoff(self.__indexer, session_id, include_plans=include_plans)

    def activity(self, *, date, timezone, refresh=False, limit=100, offset=0,
                 index_revision=None, session_id=None, evidence_limit=6, message_offset=0, message_index=None, text_offset=0):
        """Message-time evidence from the selected store; never an outcome score."""
        from .activity import read_store
        self.__check_root()
        self.__validate_cache()
        return read_store(self.__indexer, self.__source, self.__root,
                          date=date, timezone=timezone, refresh=refresh,
                          limit=limit, offset=offset, index_revision=index_revision,
                          session_id=session_id, evidence_limit=evidence_limit, message_offset=message_offset, message_index=message_index, text_offset=text_offset)

    def close(self):
        if self.__indexer is not None:
            self.__indexer.conn.close()
            self.__indexer = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
