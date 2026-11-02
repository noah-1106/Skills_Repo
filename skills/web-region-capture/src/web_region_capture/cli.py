import argparse
import json
import sys
from pathlib import Path
from .product import ProductError, doctor, project_path, read_json, run, write_json
from .capture import CaptureError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='web-region-capture', description='Client-independent web region capture; all relative paths resolve from project root.')
    parser.add_argument('--root', default=None, help='Project root (default: current directory)')
    sub = parser.add_subparsers(dest='command', required=True)
    run_parser = sub.add_parser('run', help='Run or explicitly resume a manifest-tracked job')
    run_parser.add_argument('--config', required=True)
    run_parser.add_argument('--run-id')
    run_parser.add_argument('--resume', action='store_true')
    delivery = run_parser.add_mutually_exclusive_group()
    delivery.add_argument('--dry-run', dest='dry_run', action='store_true', default=True, help='Capture evidence but write no folder/Excel/Base target (default)')
    delivery.add_argument('--execute-local', dest='dry_run', action='store_false', help='Write new folder/Excel targets; Base still requires separate authorization')
    run_parser.add_argument('--authorize-lark-write', action='store_true', help='Second gate for real Base writes; task must also set allow_live_write=true')
    doctor_parser = sub.add_parser('doctor', help='Check dependencies and managed Chromium; emits JSON')
    doctor_parser.add_argument('--local-config', default='config/local.json')
    doctor_parser.add_argument('--no-browser', action='store_true')
    doctor_parser.add_argument('--artifact', default=None, help='Run-relative JSON output; default data/runs/doctor-<UTC>/env-report.json')
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd().resolve()
    try:
        if args.command == 'doctor':
            report = doctor(root, args.local_config, check_browser=not args.no_browser)
            if args.artifact:
                artifact = project_path(root, args.artifact)
            else:
                from datetime import datetime, timezone
                artifact = project_path(root, 'data/runs/doctor-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '/env-report.json')
            write_json(artifact, report)
            report['artifact'] = str(artifact)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['ok'] else 1
        result = run(root, args.config, run_id=args.run_id, resume=args.resume, dry_run=args.dry_run, authorize_lark_write=args.authorize_lark_write)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProductError, CaptureError) as error:
        print(json.dumps({'ok': False, 'code': error.code, 'message': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({'ok': False, 'code': type(error).__name__, 'message': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 3

if __name__ == '__main__':
    raise SystemExit(main())
