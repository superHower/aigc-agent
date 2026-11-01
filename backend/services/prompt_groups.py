from fastapi import HTTPException


def group_view(db, group_id, user):
    row = db.execute("SELECT * FROM prompt_groups WHERE id=? AND owner_id=?", (group_id, user['id'])).fetchone()
    if row is None:
        raise HTTPException(404, '提示词组不存在，请刷新后重试')
    members = db.execute("SELECT template_id FROM prompt_group_members WHERE group_id=? ORDER BY position", (group_id,)).fetchall()
    return {**dict(row), 'template_ids': [member['template_id'] for member in members]}


def resolve_group(db, group_id, user):
    group = group_view(db, group_id, user)
    rows = db.execute('''SELECT t.* FROM prompt_group_members m JOIN prompt_templates t ON t.id=m.template_id
        WHERE m.group_id=? ORDER BY m.position''', (group_id,)).fetchall()
    if not rows:
        raise HTTPException(422, '提示词组为空，请先在提示词管理中添加模板')
    if len(rows) > 50:
        raise HTTPException(422, '每组最多支持 50 条提示词')
    if any(user['role'] != 'admin' and row['owner_id'] != user['id'] and row['visibility'] != 'public' for row in rows):
        raise HTTPException(422, '组内包含已不可访问的模板，请重新编辑提示词组')
    return group, [{'id': row['id'], 'name': row['name'], 'content': row['content']} for row in rows]
