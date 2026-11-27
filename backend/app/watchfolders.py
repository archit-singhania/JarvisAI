"""Bounded document indexing inside operator-approved roots only."""
import fnmatch
import hashlib
from app.extract_pdf import PDFExtractionTimedOut, PDFIsolationUnavailable, extract_document
import stat
import json
import os
from pathlib import Path
from uuid import uuid4
from app.workspace import timestamp


def open_watch_file(path, flags):
    """Open without following links in any component on dirfd-capable hosts."""
    if os.open not in os.supports_dir_fd or not getattr(os, 'O_NOFOLLOW', 0):
        return os.open(path, flags)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(path.anchor, directory_flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, flags, dir_fd=parent)
    finally:
        os.close(parent)


class WatchFolders:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS watched_folders(id TEXT PRIMARY KEY,owner TEXT NOT NULL,root TEXT NOT NULL,exclusions TEXT NOT NULL,status TEXT NOT NULL,error TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS watched_files(folder TEXT NOT NULL,path TEXT NOT NULL,hash TEXT NOT NULL,record TEXT NOT NULL,error TEXT,PRIMARY KEY(folder,path));''')

    def list(self, owner):
        with self.store.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM watched_folders WHERE owner=?',(owner,))]
            for row in rows:
                row['files']=[dict(r) for r in db.execute('SELECT path,hash,error FROM watched_files WHERE folder=?',(row['id'],))]
            return rows

    def add(self, owner, root, exclusions):
        if os.environ.get('WEDNESDAY_WATCH_OWNER') != owner:
            raise ValueError('Host owner must explicitly authorize this workspace with WEDNESDAY_WATCH_OWNER')
        path=Path(root)
        approved=[Path(p).resolve() for p in os.environ.get('WEDNESDAY_WATCH_ROOTS','').split(os.pathsep) if p]
        if not path.is_absolute() or not path.is_dir() or path.is_symlink() or not any(path.resolve()==p for p in approved):
            raise ValueError('Select an exact directory explicitly listed in WEDNESDAY_WATCH_ROOTS on this host')
        if any(p.is_symlink() for p in path.parents): raise ValueError('Symlink roots are not supported')
        path=path.resolve()
        with self.store.db() as db:
            existing=db.execute('SELECT id FROM watched_folders WHERE owner=? AND root=?',(owner,str(path))).fetchone()
            if existing: return {'id':existing['id']}
            identity=uuid4().hex
            db.execute('INSERT INTO watched_folders VALUES(?,?,?,?,?,?,?)',(identity,owner,str(path),json.dumps(exclusions),'queued',None,timestamp()))
        return {'id':identity}

    def remove(self, owner, identity):
        with self.store.db() as db:
            if not db.execute('SELECT 1 FROM watched_folders WHERE owner=? AND id=?',(owner,identity)).fetchone(): raise KeyError(identity)
            db.execute('DELETE FROM records WHERE owner=? AND id IN (SELECT record FROM watched_files WHERE folder=?)',(owner,identity))
            db.execute('DELETE FROM watched_files WHERE folder=?',(identity,))
            db.execute('DELETE FROM watched_folders WHERE owner=? AND id=?',(owner,identity))

    def scan(self, folder):
        root=Path(folder['root'])
        approved=[Path(p).resolve() for p in os.environ.get('WEDNESDAY_WATCH_ROOTS','').split(os.pathsep) if p]
        if os.environ.get('WEDNESDAY_WATCH_OWNER') != folder['owner'] or root.is_symlink() or any(p.is_symlink() for p in root.parents) or not root.is_dir() or root.resolve() not in approved:
            raise ValueError('Approved root is unavailable; previous content was withheld')
        excludes=json.loads(folder['exclusions'])+['.git/*','node_modules/*','.env','**/.env']
        discovered={}
        visited=0
        extracted=0
        bytes_read=0
        for parent, dirs, files in os.walk(root, followlinks=False):
            dirs[:]=[d for d in dirs if not Path(parent,d).is_symlink() and not any(fnmatch.fnmatch(Path(parent,d).relative_to(root).as_posix()+'/',p) for p in excludes)]
            for name in files:
                visited+=1
                if visited>2000: raise ValueError('Folder exceeds the 2000-file scan budget; narrow the approved root')
                path=Path(parent,name); rel=path.relative_to(root).as_posix()
                if path.suffix.lower() not in ('.txt','.md','.pdf') or any(fnmatch.fnmatch(rel,p) for p in excludes): continue
                with self.store.db() as db:
                    if not db.execute('SELECT 1 FROM watched_folders WHERE id=? AND owner=?',
                                      (folder['id'], folder['owner'])).fetchone():
                        return
                if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.resolve().is_relative_to(root): continue
                error=None; content=''; digest=''
                try:
                    before = path.stat(follow_symlinks=False)
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError('Only regular files can be indexed')
                    if before.st_size > 4*1024*1024:
                        raise ValueError('File exceeds 4 MiB')
                    flags = os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0) | getattr(os,'O_BINARY',0)
                    with os.fdopen(open_watch_file(path,flags),'rb') as source:
                        opened = os.fstat(source.fileno())
                        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before,opened):
                            raise ValueError('File changed before opening')
                        data = source.read(4*1024*1024+1)
                        after = os.fstat(source.fileno())
                    if (after.st_size,after.st_mtime_ns) != (opened.st_size,opened.st_mtime_ns):
                        raise ValueError('File changed while being read')
                    if (not os.path.samestat(after,path.stat(follow_symlinks=False))
                            or path.is_symlink() or not path.resolve().is_relative_to(root)):
                        raise ValueError('File moved or changed during scan')
                    bytes_read+=len(data)
                    if bytes_read>32*1024*1024: raise OverflowError('Folder exceeds scan byte budget')
                    if len(data)>4*1024*1024: raise ValueError('File grew past budget')
                    digest=hashlib.sha256(data).hexdigest()
                    with self.store.db() as db:
                        prior=db.execute('SELECT * FROM watched_files WHERE folder=? AND path=?',(folder['id'],rel)).fetchone()
                    if prior and prior['hash']==digest and not prior['error']:
                        discovered[rel]=(digest,None,None,prior['record']); continue
                    if path.suffix.lower()=='.pdf':
                        content = extract_document(data)
                    else: content=data.decode('utf-8')
                    if len(content)>200000: raise ValueError('Extracted text exceeds 200000 characters')
                except OverflowError:
                    raise
                except PDFExtractionTimedOut as exc:
                    error = str(exc)
                    content = ''
                except TimeoutError:
                    error = 'PDF workers are busy; extraction will retry on the next scan'
                    content = ''
                except PDFIsolationUnavailable as exc:
                    error = str(exc)
                    content = ''
                except Exception as exc:
                    error=type(exc).__name__+': extraction unavailable'; content=''
                identity=hashlib.sha256((folder['id']+'/'+rel).encode()).hexdigest()
                discovered[rel]=(digest,content,error,identity)
                if bytes_read>32*1024*1024: raise ValueError('Folder exceeds the 32 MiB scan budget')
                extracted+=len(content)
                if extracted>10000000: raise ValueError('Folder exceeds the extracted text budget')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM watched_folders WHERE id=?',(folder['id'],)).fetchone(): return
            for old in db.execute('SELECT * FROM watched_files WHERE folder=?',(folder['id'],)).fetchall():
                if old['path'] not in discovered:
                    db.execute('DELETE FROM records WHERE id=? AND owner=?',(old['record'],folder['owner']))
                    db.execute('DELETE FROM watched_files WHERE folder=? AND path=?',(folder['id'],old['path']))
            for rel,(digest,content,error,identity) in discovered.items():
                if content is None: continue
                db.execute('INSERT INTO watched_files VALUES(?,?,?,?,?) ON CONFLICT(folder,path) DO UPDATE SET hash=excluded.hash,error=excluded.error',(folder['id'],rel,digest,identity,error))
                db.execute('DELETE FROM records WHERE id=? AND owner=?',(identity,folder['owner']))
                if not error:
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',(identity,folder['owner'],'document',rel,content,json.dumps({'bytes':len(content.encode()),'watch_folder':folder['id'],'sha256':digest}),timestamp()))
            db.execute("UPDATE watched_folders SET status='ready',error=NULL,updated_at=? WHERE id=?",(timestamp(),folder['id']))

    def tick(self):
        with self.store.db() as db: folders=[dict(r) for r in db.execute('SELECT * FROM watched_folders')]
        for folder in folders:
            try: self.scan(folder)
            except Exception:
                with self.store.db() as db:
                    db.execute('DELETE FROM records WHERE owner=? AND id IN (SELECT record FROM watched_files WHERE folder=?)',(folder['owner'],folder['id']))
                    db.execute('DELETE FROM watched_files WHERE folder=?',(folder['id'],))
                    db.execute("UPDATE watched_folders SET status='failed',error='Root unavailable or scan budget exceeded; indexed content withheld',updated_at=? WHERE id=?",(timestamp(),folder['id']))
