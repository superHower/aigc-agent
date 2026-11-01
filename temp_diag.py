import sqlite3
c=sqlite3.connect('/app/backend/data/tasks.db'); c.row_factory=sqlite3.Row
for table in ('channels','tasks','jobs'):
 print(table,[dict(r) for r in c.execute('select * from '+table+' order by rowid desc limit 10')])
