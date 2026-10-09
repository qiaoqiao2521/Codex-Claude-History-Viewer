"""Explicit local source access; no Web, background thread or model startup."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .reader import HistoryReader
from .providers import SOURCES, canonical_source


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "activity":
        from .activity import main as activity_main
        try:
            return activity_main(argv[1:])
        except Exception as exc:
            print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=canonical_source, choices=SOURCES, required=True)
    parser.add_argument("--source-path", type=Path, required=True, help="Explicit sessions directory or native SQLite file")
    parser.add_argument("--data-dir", type=Path, help="Required separate cache directory for JSONL sources")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh")
    commands.add_parser("health")
    query = commands.add_parser("search")
    query.add_argument("--query", default=None)
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    query.add_argument("--project", default=None)
    query.add_argument("--index-revision", default=None, help="Previous page revision; required for offset > 0 in a new process")
    query.add_argument("--brief", action="store_true", help="Return compact candidates and public excerpts for message-index sources")
    message = commands.add_parser("message", help="Expand a public search message using its index revision")
    message.add_argument("session_id")
    message.add_argument("message_index", type=int)
    message.add_argument("--index-revision", required=True, help="Exact revision returned by search")
    message.add_argument("--text-offset", type=int, default=0, help="Indexed-text character offset for bounded body pages")
    markers = commands.add_parser("markers", help="Query recorded skill/output-style metadata without body reads or effect claims")
    markers.add_argument("--name", default=None)
    markers.add_argument("--kind", choices=("skill", "output_style"), default=None)
    markers.add_argument("--session", default=None, dest="session_id")
    markers.add_argument("--project", default=None, help="Exact recorded working directory")
    markers.add_argument("--limit", type=int, default=20)
    markers.add_argument("--offset", type=int, default=0)
    markers.add_argument("--index-revision", default=None, help="Exact previous marker-page revision; required for offset > 0")
    transfer = commands.add_parser("handoff")
    transfer.add_argument("session_id")
    transfer.add_argument("--include-plans", action="store_true", help="Explicitly include bounded project-file candidates; not verified decisions")
    native = commands.add_parser("native-reference", help="Read a content-bound reference for explicit native continuation")
    native.add_argument("session_id")
    native.add_argument("--device-id", required=True, help="Stable local device identity from the coordinator configuration")
    args = parser.parse_args(argv)
    reader = None
    try:
        source = args.source_path.resolve(strict=True)
        if args.command == "native-reference":
            if args.source not in ("opencode", "claude", "codex"):
                raise ValueError("native_reference_provider_unsupported")
            from .native import native_reference
            from .claude_native import claude_native_reference
            from .codex_native import codex_native_reference
            reference = {"opencode": native_reference, "claude": claude_native_reference, "codex": codex_native_reference}[args.source]
            result = {"schema_version": "history.native_candidate.v2", "authorization": "context_only",
                      "observed_at": datetime.now(timezone.utc).isoformat(),
                      "reference": reference(args.source_path, args.device_id, args.session_id)}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        reader = HistoryReader(args.source, source, args.data_dir)
        if args.command == "refresh":
            result = reader.refresh()
        elif args.command == "search":
            result = reader.search(query=args.query, limit=args.limit, offset=args.offset, cwd=args.project, index_revision=args.index_revision, brief=args.brief)
        elif args.command == "handoff":
            result = reader.handoff(args.session_id, include_plans=args.include_plans)
        elif args.command == "message":
            result = reader.message(args.session_id, args.message_index,
                                    index_revision=args.index_revision, text_offset=args.text_offset)
        elif args.command == "markers":
            result = reader.markers(name=args.name, kind=args.kind, session_id=args.session_id,
                                    project=args.project,
                                    limit=args.limit, offset=args.offset, index_revision=args.index_revision)
        else:
            result = reader.health()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if reader is not None:
            reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
