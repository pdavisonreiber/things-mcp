"""Build a small synthetic Things 3 database for integration tests.

The schema covers the tables and columns things.py queries (it is not a full
copy of Things' schema). Dates use Things' encodings: start/deadline dates are
packed integers (year << 16 | month << 12 | day << 7); creation/stop dates are
Unix timestamps.
"""
import plistlib
import sqlite3
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE Meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE TMSettings (uuid TEXT PRIMARY KEY, uriSchemeAuthenticationToken TEXT);
CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT, visible INTEGER, "index" INTEGER);
CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT, shortcut TEXT, usedDate REAL,
                    parent TEXT, "index" INTEGER);
CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT);
CREATE TABLE TMAreaTag (areas TEXT, tags TEXT);
CREATE TABLE TMChecklistItem (uuid TEXT PRIMARY KEY, title TEXT, status INTEGER, stopDate REAL,
                              task TEXT, "index" INTEGER, creationDate REAL,
                              userModificationDate REAL);
CREATE TABLE TMTask (
    uuid TEXT PRIMARY KEY, type INTEGER, title TEXT, notes TEXT, status INTEGER,
    start INTEGER, startDate INTEGER, startBucket INTEGER, deadline INTEGER,
    deadlineSuppressionDate INTEGER, reminderTime INTEGER, stopDate REAL,
    creationDate REAL, userModificationDate REAL, "index" INTEGER, todayIndex INTEGER,
    area TEXT, project TEXT, heading TEXT, trashed INTEGER DEFAULT 0,
    rt1_recurrenceRule BLOB, rt1_instanceCreationPaused INTEGER, rt1_nextInstanceStartDate INTEGER,
    checklistItemsCount INTEGER DEFAULT 0, openChecklistItemsCount INTEGER DEFAULT 0
);
"""

TODO, PROJECT, HEADING = 0, 1, 2
INCOMPLETE, CANCELED, COMPLETED = 0, 2, 3
INBOX, ANYTIME, SOMEDAY = 0, 1, 2


def things_date(d: date) -> int:
    return (d.year << 16) | (d.month << 12) | (d.day << 7)


def build(path, token='test-token') -> dict:
    """Create the database at ``path``; return a dict of notable dates."""
    today = date.today()
    now = datetime.now()
    ts = lambda dt: dt.timestamp()  # noqa: E731
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    # Things stores the schema version as an XML plist; things.py requires > 21.
    db.execute("INSERT INTO Meta VALUES ('databaseVersion', ?)",
               (plistlib.dumps(26, fmt=plistlib.FMT_XML).decode(),))
    # things.py reads the URL-scheme token from this fixed settings row.
    db.execute("INSERT INTO TMSettings VALUES ('RhAzEf6qDxCD5PmnZVtBZR', ?)", (token,))
    db.executemany('INSERT INTO TMArea VALUES (?, ?, 1, ?)', [
        ('AREA-WORK', 'Work', 1), ('AREA-HOME', 'Home', 2)])
    db.executemany('INSERT INTO TMTag (uuid, title, "index") VALUES (?, ?, ?)', [
        ('TAG-ERRAND', 'errand', 1), ('TAG-UNUSED', 'unused', 2)])

    def task(uuid, title, *, type=TODO, status=INCOMPLETE, start=ANYTIME, start_date=None,
             deadline=None, area=None, project=None, heading=None, stopped=None,
             created=None, index=0, today_index=None, trashed=0, evening=False):
        db.execute(
            """INSERT INTO TMTask (uuid, type, title, notes, status, start, startDate, deadline,
               stopDate, creationDate, userModificationDate, "index", todayIndex, area, project,
               heading, trashed) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid, type, title, status, start,
             things_date(start_date) if start_date else None,
             things_date(deadline) if deadline else None,
             ts(stopped) if stopped else None,
             ts(created or now - timedelta(days=30)), ts(now - timedelta(days=1)),
             index, today_index, area, project, heading, trashed))
        if evening:  # This Evening lives in startBucket, which things.py doesn't read
            db.execute('UPDATE TMTask SET startBucket = 1 WHERE uuid = ?', (uuid,))

    task('PROJ-LAUNCH', 'Launch', type=PROJECT, area='AREA-WORK')
    task('PROJ-DREAM', 'Dream project', type=PROJECT, start=SOMEDAY)
    task('HEAD-PREP', 'Prep', type=HEADING, project='PROJ-LAUNCH')
    task('TODO-INBOX', 'Inbox idea', start=INBOX, created=now - timedelta(hours=2))
    task('TODO-TODAY', 'Write brief', project='PROJ-LAUNCH', start_date=today,
         deadline=today + timedelta(days=2), today_index=1, index=1)
    task('TODO-HEAD', 'Book venue', heading='HEAD-PREP', start_date=today, today_index=2, index=2)
    task('TODO-MILK', 'Buy milk', area='AREA-HOME', start_date=today, today_index=3)
    task('TODO-EVE', 'Call mum', start_date=today, today_index=4, evening=True)
    # Future-dated to-dos sit in start=Someday with a startDate (that's Upcoming).
    task('TODO-LATER', 'Renew passport', start=SOMEDAY, start_date=today + timedelta(days=10))
    task('TODO-DREAM', 'Learn Japanese', project='PROJ-DREAM')
    task('TODO-SOME', 'Someday thing', start=SOMEDAY)
    task('TODO-DONE', 'Filed taxes', status=COMPLETED, stopped=now - timedelta(days=2),
         created=now - timedelta(days=90))
    task('TODO-OLD', 'Ancient chore', status=COMPLETED, stopped=now - timedelta(days=40))
    task('TODO-TRASH', 'Binned', trashed=1)

    # Repeating to-dos are templates: things.py skips them; the next occurrence
    # only exists as rt1_nextInstanceStartDate until Things creates it.
    task('TODO-BINS', 'Put the bins out', start=ANYTIME)
    task('TODO-PAUSED', 'Paused repeat', start=ANYTIME)
    db.executemany(
        'UPDATE TMTask SET rt1_recurrenceRule = ?, rt1_instanceCreationPaused = ?, '
        'rt1_nextInstanceStartDate = ? WHERE uuid = ?',
        [(b'rule', 0, things_date(today + timedelta(days=1)), 'TODO-BINS'),
         (b'rule', 1, things_date(today + timedelta(days=1)), 'TODO-PAUSED')])

    db.execute("INSERT INTO TMTaskTag VALUES ('TODO-MILK', 'TAG-ERRAND')")
    db.executemany(
        'INSERT INTO TMChecklistItem (uuid, title, status, task, "index") VALUES (?, ?, ?, ?, ?)',
        [('CL-1', 'Outline', COMPLETED, 'TODO-TODAY', 1), ('CL-2', 'Draft', INCOMPLETE, 'TODO-TODAY', 2)])
    db.commit()
    db.close()
    return {'today': today}
