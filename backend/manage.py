"""Run with python -m backend.manage. Passwords are read only from the terminal."""
import argparse
import getpass
import json
from pathlib import Path

from backend.config import Settings
from backend.db.operations import backup, bootstrap_admin, import_sqlite, restore, validate
from backend.db.task_store import TaskStore


def main():
    parser = argparse.ArgumentParser(description='v4 离线数据库维护（先停止后端）')
    parser.add_argument('--database', help='SQLite 路径或 PostgreSQL URL；默认读取环境配置')
    parser.add_argument('--media', type=Path, help='媒体目录')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate')
    admin = commands.add_parser('init-admin')
    admin.add_argument('--username', required=True)
    commands.add_parser('validate')
    save = commands.add_parser('backup')
    save.add_argument('destination', type=Path)
    load = commands.add_parser('restore')
    load.add_argument('source', type=Path)
    transfer = commands.add_parser('import-sqlite')
    transfer.add_argument('source', type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    url = args.database or settings.database_url or str(settings.database_path)
    media = args.media or settings.data_dir
    try:
        if args.command in ('backup', 'restore'):
            if url.startswith(('postgresql://', 'postgres://')):
                raise ValueError('PostgreSQL 请使用 pg_dump/pg_restore；此命令用于 SQLite 和媒体')
            if args.command == 'backup':
                backup(Path(url), media, args.destination)
            else:
                restore(args.source, Path(url), media)
        else:
            store = TaskStore(url)
            if args.command == 'init-admin':
                password = getpass.getpass('超管密码：')
                if password != getpass.getpass('确认密码：'):
                    raise ValueError('两次密码不一致')
                bootstrap_admin(store, args.username, password)
            elif args.command == 'import-sqlite':
                from backend.services.channels import ChannelStore
                ChannelStore(store)
                import_sqlite(args.source, store)
            elif args.command == 'validate':
                report = validate(store, media)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0 if report['ok'] else 1
        print('完成')
        return 0
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
