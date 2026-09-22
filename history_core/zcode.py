"""Read ZCode's OpenCode-family store without altering its schema or data."""
from .sources import OpenCodeIndexer


class ZCodeIndexer(OpenCodeIndexer):
    def __init__(self, db_path):
        super().__init__(db_path)
        self.source = 'zcode'
        try:
            # A connection-local projection supplies OpenCode's session-level
            # metrics from ZCode's message envelopes. Main DB stays mode=ro.
            self.conn.execute('PRAGMA temp_store=MEMORY')
            columns = {row[1] for row in self.conn.execute('PRAGMA main.table_info(session)')}
            fields = ['s.*']
            numeric = {'cost': '$.cost', 'tokens_input': '$.tokens.input', 'tokens_output': '$.tokens.output',
                       'tokens_reasoning': '$.tokens.reasoning', 'tokens_cache_read': '$.tokens.cache.read',
                       'tokens_cache_write': '$.tokens.cache.write'}
            for name, path in numeric.items():
                if name not in columns:
                    fields.append("(SELECT COALESCE(SUM(json_extract(m.data, '%s')),0) FROM main.message m "
                                  "WHERE m.session_id=s.id AND json_valid(m.data) AND json_extract(m.data,'$.role')='assistant') AS %s" % (path, name))
            for name, expression in {
                'agent': "json_extract(m.data,'$.agent')",
                'model': "json_object('id',COALESCE(json_extract(m.data,'$.modelID'),json_extract(m.data,'$.modelId'),json_extract(m.data,'$.model.id')))"
            }.items():
                if name not in columns:
                    fields.append("(SELECT %s FROM main.message m WHERE m.session_id=s.id AND json_valid(m.data) "
                                  "AND json_extract(m.data,'$.role')='assistant' ORDER BY m.sequence DESC LIMIT 1) AS %s" % (expression, name))
            self.conn.execute('CREATE TEMP VIEW session AS SELECT ' + ', '.join(fields) + ' FROM main.session s')
        except Exception:
            self.conn.close()
            raise

    def _part_order_sql(self):
        return 'COALESCE(m.sequence,m.time_created) ASC, m.id ASC, COALESCE(p.sequence,p.time_created) ASC, p.id ASC'

    @staticmethod
    def _flatten_part(message_role, part_type, part_data, part_time_ms):
        # ZCode stores terminal failures in state.error; the shared renderer
        # reads metadata.error. Normalize in memory so display and audit expose
        # the same failure without changing the source part or its flat index.
        if part_type == 'tool':
            state = part_data.get('state')
            if isinstance(state, dict) and state.get('error'):
                metadata = state.get('metadata')
                metadata = dict(metadata) if isinstance(metadata, dict) else {}
                metadata.setdefault('error', state['error'])
                part_data = {**part_data, 'state': {**state, 'metadata': metadata}}
        return OpenCodeIndexer._flatten_part(message_role, part_type, part_data, part_time_ms)
