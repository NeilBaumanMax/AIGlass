"""Local display history, independent of the model's conversation context."""
import sqlite3
import threading
from pathlib import Path


class Journal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT, text TEXT, time REAL)')
        self.db.execute('UPDATE events SET text=replace(text,?,?)', ('\u5c0f\u955c', 'Edith'))
        self.db.execute('UPDATE events SET text=replace(text,?,?)', ('\u0045lis', 'Edith'))
        self.db.commit()

    def read(self):
        with self.lock:
            return [dict(zip(('id', 'kind', 'text', 'time'), row)) for row in
                    self.db.execute('SELECT id,kind,text,time FROM events ORDER BY time')]

    def append(self, event):
        with self.lock, self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?)', tuple(event[k] for k in ('id','kind','text','time')))
            self.db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY time DESC LIMIT 500)')

    def clear_dialog(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM events WHERE kind='dialog'")
