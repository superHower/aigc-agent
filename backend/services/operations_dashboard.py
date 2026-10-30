from datetime import datetime, time, timedelta, timezone

from backend.services import credits


def window(period, selected, offset):
    zone = timezone(timedelta(minutes=-offset))
    first = selected if period == 'day' else selected-timedelta(days=selected.weekday()) if period == 'week' else selected.replace(day=1)
    last = first+timedelta(days=1 if period == 'day' else 7) if period != 'month' else (first.replace(day=28)+timedelta(days=4)).replace(day=1)
    return datetime.combine(first, time(), zone), datetime.combine(last, time(), zone)


def metrics(store, period, selected, offset, owner=None):
    start, end = window(period, selected, offset)
    zone = start.tzinfo
    step = timedelta(hours=1) if period == 'day' else timedelta(days=1)
    count = int((end-start)/step)
    trend = [{'label': (start+i*step).strftime('%H:00' if period == 'day' else '%m-%d'), 'verified_cents': 0, 'consumed': 0, 'granted': 0} for i in range(count)]
    summary = dict(verified_cents=0, credited_orders=0, granted=0, paid_granted=0, trial_granted=0, adjustment_granted=0, consumed=0, frozen_events=0, released=0, expired=0, adjusted=0, attempts=0, dispatched=0, dispatch_unknown=0, failed_attempts=0, retry_attempts=0, unknown_cost_attempts=0, estimated_cost_cents=0, unpriced_attempts=0, verified_cost_cents=0)
    def bucket(timestamp):
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(zone)
        return int((value-start)/step) if start <= value < end else None
    with store.transaction() as db:
        credits.begin(db)
        # Current balances are a snapshot, independent of selected event period.
        for row in db.execute('SELECT user_id FROM credit_accounts').fetchall():
            if owner is None or row['user_id'] == owner:
                credits.expire(db, row['user_id'])
        ownership = ' AND e.user_id=?' if owner else ''
        rows = db.execute('''SELECT e.event,e.available_delta,e.frozen_delta,e.created_at,l.source
            FROM credit_entries e LEFT JOIN credit_lots l ON l.id=e.lot_id
            WHERE julianday(e.created_at)>=julianday(?) AND julianday(e.created_at)<julianday(?)'''+ownership,
            (start.isoformat(), end.isoformat(), *((owner,) if owner else ())))
        for row in rows:
            i = bucket(row['created_at'])
            event, amount = row['event'], row['available_delta']
            if event == 'grant':
                summary['granted'] += amount; trend[i]['granted'] += amount
                key = {'paid': 'paid_granted', 'trial': 'trial_granted', 'adjustment': 'adjustment_granted'}.get(row['source'])
                if key: summary[key] += amount
            elif event == 'settle':
                value = -row['frozen_delta']; summary['consumed'] += value; trend[i]['consumed'] += value
            elif event == 'freeze': summary['frozen_events'] += row['frozen_delta']
            elif event == 'release': summary['released'] += -row['frozen_delta']
            elif event == 'expire': summary['expired'] += -amount
            elif event == 'adjust': summary['adjusted'] += amount
        totals = db.execute('SELECT COALESCE(SUM(available),0) AS available,COALESCE(SUM(frozen),0) AS frozen FROM credit_accounts'+(' WHERE user_id=?' if owner else ''), (owner,) if owner else ()).fetchone()
        summary.update(current_available=totals['available'], current_frozen=totals['frozen'])
        sales = {}
        if owner is None:
            for row in db.execute("SELECT id,package_id,package_name,price_cents,credited_at FROM orders WHERE status='credited' AND julianday(credited_at)>=julianday(?) AND julianday(credited_at)<julianday(?)", (start.isoformat(), end.isoformat())):
                i = bucket(row['credited_at'])
                summary['verified_cents'] += row['price_cents']; summary['credited_orders'] += 1
                trend[i]['verified_cents'] += row['price_cents']
                key = (row['package_id'], row['package_name'])
                item = sales.setdefault(key, {'package_id': key[0], 'name': key[1], 'orders': 0, 'verified_cents': 0})
                item['orders'] += 1; item['verified_cents'] += row['price_cents']
            for row in db.execute('SELECT * FROM generation_attempts WHERE julianday(started_at)>=julianday(?) AND julianday(started_at)<julianday(?)', (start.isoformat(), end.isoformat())):
                summary['attempts'] += 1
                summary['dispatched'] += row['dispatched'] == 1
                summary['dispatch_unknown'] += row['dispatched'] is None
                summary['failed_attempts'] += row['status'] == 'failed'
                summary['retry_attempts'] += row['retry_round'] > 0
                if row['cost_source'] == 'verified' and row['cost_value'] is not None:
                    summary['verified_cost_cents'] += row['cost_value']
                else: summary['unknown_cost_attempts'] += 1
                if row['dispatched'] == 1 and row['estimated_cost_cents'] is not None:
                    summary['estimated_cost_cents'] += row['estimated_cost_cents']
                elif row['dispatched'] != 0: summary['unpriced_attempts'] += 1
            summary['pending_reviews'] = db.execute("SELECT COUNT(*) FROM orders WHERE status='review'").fetchone()[0]
            summary['disabled_users'] = db.execute('SELECT COUNT(*) FROM users WHERE disabled=1').fetchone()[0]
    result = {'summary': summary, 'trend': trend, 'sales': list(sales.values()), 'start': start.isoformat(), 'end': end.isoformat(), 'updated_at': datetime.now(timezone.utc).isoformat()}
    if owner:
        allowed = ('granted', 'consumed', 'frozen_events', 'released', 'expired', 'adjusted', 'current_available', 'current_frozen')
        result['summary'] = {k: summary[k] for k in allowed}
        for point in trend: point.pop('verified_cents')
    return result
