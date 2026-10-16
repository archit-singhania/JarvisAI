"""Owned job progress snapshots; reconnects replay current state, never operation results."""
class Progress:
    def __init__(self,store):self.store=store;self.seen={}
    def changes(self,owner):
        rows=[]
        with self.store.db() as db:
            for table,kind in [('routine_runs','routine_progress'),('meetings','meeting_progress')]:
                columns='id,status,updated_at'+(',cursor' if table=='routine_runs' else '')
                for row in db.execute(f'SELECT {columns} FROM {table} WHERE owner=? ORDER BY updated_at DESC LIMIT 100',(owner,)):
                    item=dict(row);key=(kind,item['id']);stamp=(item['status'],item['updated_at'],item.get('cursor'))
                    rows.append((key,stamp,item))
        current={key:stamp for key,stamp,_ in rows};changed=[{'type':key[0],**item} for key,stamp,item in rows if self.seen.get(key)!=stamp];self.seen=current
        return changed
