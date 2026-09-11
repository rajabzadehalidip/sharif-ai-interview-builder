"""SQLite leases, verified snapshots and non-destructive archive recovery."""
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import closing

def snapshot(db_path):
    folder = Path(db_path).resolve().parent / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:8] + '.sqlite')
    with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity verification failed')
    return {'name': target.name, 'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}

def backup_path(db_path, name):
    if Path(name).name != name or not name.endswith('.sqlite'):
        raise ValueError('Invalid backup name')
    target = Path(db_path).resolve().parent / 'backups' / name
    if not target.is_file():
        raise ValueError('Backup not found')
    return target

def restore_missing(db_path, name, apply=False):
    target = backup_path(db_path, name)
    with closing(sqlite3.connect(f'{target.as_uri()}?mode=ro', uri=True)) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Invalid backup')
        rows = source.execute('SELECT id,payload,updated_at FROM sessions').fetchall()
    for sid, payload, _ in rows:
        if json.loads(payload).get('id') != sid:
            raise ValueError('Invalid session record')
    if apply:
        snapshot(db_path)
    with closing(sqlite3.connect(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        existing = {r[0] for r in db.execute('SELECT id FROM sessions')}
        missing = [row for row in rows if row[0] not in existing]
        if apply:
            db.executemany('INSERT INTO sessions(id,payload,updated_at) VALUES (?,?,?)', missing)
            db.commit()
    return {'missing_interviews': len(missing), 'existing_preserved': len(rows)-len(missing), 'applied': apply}

def review_flags(session):
    flags = []
    seen = {}
    for message in session.messages:
        if message.get('role') != 'assistant':
            continue
        text = message.get('content', '').strip()
        if text and text in seen:
            flags.append({'category':'repeated_question', 'turn_id':message.get('turn_id'), 'message_id':message.get('message_id'), 'note':'متن تکراری؛ بررسی کنید آیا بازگویی به درخواست پاسخ‌دهنده بوده است.', 'source':'heuristic', 'status':'unreviewed'})
        seen[text] = True
    if session.completion_reason in {'technical_failure', 'participant_requested_end', 'participant_end_button'}:
        flags.append({'category':'early_ending', 'turn_id': session.messages[-1].get('turn_id') if session.messages else None, 'note':'پایان پیش از تکمیل؛ ممکن است انتخاب معتبر پاسخ‌دهنده باشد.', 'source':'heuristic', 'status':'unreviewed'})
    return flags
