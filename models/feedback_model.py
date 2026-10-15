from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import os


class Feedback:
    @staticmethod
    def create(subject, message, category, priority, user_id, attachment_path=None,
               full_name='', email=''):
        col = get_collection('feedback')
        fb_id = next_id('feedback')
        col.insert_one({
            'id': fb_id,
            'subject': subject,
            'message': message,
            'category': category,
            'priority': priority,
            'status': 'open',
            'user_id': user_id,
            # Guest senders (public contact form) carry their own name/email
            'full_name': full_name or '',
            'email': email or '',
            'response': None,
            'responded_by': None,
            'responded_at': None,
            'messages': [{
                'sender_role': 'analyst',
                'sender_id': user_id,
                'message': message,
                'created_at': datetime.utcnow().isoformat(),
            }],
            'assigned_to': None,
            'attachment_path': attachment_path or '',
            'created_at': datetime.utcnow().isoformat(),
        })
        return fb_id

    @staticmethod
    def get_all(status=None, category=None, priority=None, search=None, limit=100):
        col_fb = get_collection('feedback')
        col_users = get_collection('users')
        query = {}
        if status:
            query['status'] = status
        if category:
            query['category'] = category
        if priority:
            query['priority'] = priority
        if search:
            query['$or'] = [
                {'subject': {'$regex': search, '$options': 'i'}},
                {'message': {'$regex': search, '$options': 'i'}},
            ]

        docs = list(col_fb.find(query).sort('created_at', -1).limit(limit))

        # Enrich with user info (simulating LEFT JOIN)
        user_cache = {}
        for d in docs:
            uid = d.get('user_id')
            if uid and uid not in user_cache:
                u = col_users.find_one({'id': uid}, {'full_name': 1, 'email': 1, 'username': 1})
                user_cache[uid] = u
            u = user_cache.get(uid)
            if u:
                d['full_name'] = u.get('full_name', '')
                d['email'] = u.get('email', '')
                d['username'] = u.get('username', '')
            else:
                d.setdefault('full_name', '')
                d.setdefault('email', '')
                d.setdefault('username', '')
        return docs

    @staticmethod
    def get_by_id(feedback_id):
        col_fb = get_collection('feedback')
        col_users = get_collection('users')
        doc = col_fb.find_one({'id': int(feedback_id)})
        if doc and doc.get('user_id'):
            u = col_users.find_one({'id': doc['user_id']},
                                   {'full_name': 1, 'email': 1, 'username': 1})
            if u:
                doc['full_name'] = u.get('full_name', '')
                doc['email'] = u.get('email', '')
                doc['username'] = u.get('username', '')
        return doc

    @staticmethod
    def respond(feedback_id, response, responded_by):
        now = datetime.utcnow().isoformat()
        doc = get_collection('feedback').find_one({'id': int(feedback_id)}) or {}
        messages = list(doc.get('messages') or [])
        messages.append({'sender_role': 'admin', 'sender_id': responded_by,
                         'message': response, 'created_at': now})
        get_collection('feedback').update_one(
            {'id': int(feedback_id)},
            {'$set': {
                'response': response,
                'responded_by': responded_by,
                'responded_at': now,
                'status': 'resolved',
                'messages': messages,
            }}
        )

    @staticmethod
    def analyst_reply(feedback_id, response, responded_by):
        """Append an analyst reply and reopen the conversation for Admin."""
        now = datetime.utcnow().isoformat()
        col = get_collection('feedback')
        doc = col.find_one({'id': int(feedback_id)}) or {}
        messages = list(doc.get('messages') or [])
        if not messages:
            messages.append({'sender_role': 'analyst', 'sender_id': doc.get('user_id'),
                             'message': doc.get('message', ''),
                             'created_at': doc.get('created_at', now)})
        messages.append({'sender_role': 'analyst', 'sender_id': responded_by,
                         'message': response, 'created_at': now})
        col.update_one({'id': int(feedback_id)}, {'$set': {
            'status': 'in_progress',
            'messages': messages,
            'last_message_at': now,
        }})

    @staticmethod
    def update_status(feedback_id, status, assigned_to=None):
        updates = {'status': status}
        if assigned_to is not None:
            updates['assigned_to'] = assigned_to
        get_collection('feedback').update_one(
            {'id': int(feedback_id)}, {'$set': updates}
        )

    @staticmethod
    def assign(feedback_id, assigned_to):
        col = get_collection('feedback')
        doc = col.find_one({'id': int(feedback_id)})
        updates = {'assigned_to': assigned_to}
        if doc and doc.get('status') == 'open':
            updates['status'] = 'in_progress'
        col.update_one({'id': int(feedback_id)}, {'$set': updates})

    @staticmethod
    def delete(feedback_id):
        col = get_collection('feedback')
        doc = col.find_one({'id': int(feedback_id)})
        if doc and doc.get('attachment_path'):
            try:
                path = doc['attachment_path']
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        col.delete_one({'id': int(feedback_id)})

    @staticmethod
    def get_count():
        return get_cached_value('feedback:count', lambda: get_collection('feedback').count_documents({}), ttl_seconds=60)

    @staticmethod
    def get_open_count():
        return get_cached_value('feedback:open_count', lambda: get_collection('feedback').count_documents({'status': 'open'}), ttl_seconds=30)

    @staticmethod
    def get_by_user(user_id, limit=50):
        return list(
            get_collection('feedback').find({'user_id': user_id})
            .sort('created_at', -1).limit(limit)
        )

    @staticmethod
    def get_stats():
        col = get_collection('feedback')
        total = col.count_documents({})

        by_status = {d['_id']: d['count'] for d in col.aggregate([
            {'$group': {'_id': '$status', 'count': {'$sum': 1}}}
        ]) if d['_id']}

        by_category = {d['_id']: d['count'] for d in col.aggregate([
            {'$group': {'_id': '$category', 'count': {'$sum': 1}}}
        ]) if d['_id']}

        by_priority = {d['_id']: d['count'] for d in col.aggregate([
            {'$group': {'_id': '$priority', 'count': {'$sum': 1}}}
        ]) if d['_id']}

        # Average response time for resolved feedback
        resolved = list(col.find({
            'responded_at': {'$ne': None},
            'created_at': {'$ne': None},
        }))
        avg_hours = None
        if resolved:
            total_hours = 0
            count = 0
            for r in resolved:
                try:
                    created = datetime.fromisoformat(r['created_at'])
                    responded = datetime.fromisoformat(r['responded_at'])
                    delta = (responded - created).total_seconds() / 3600
                    total_hours += delta
                    count += 1
                except Exception:
                    pass
            if count > 0:
                avg_hours = round(total_hours / count, 1)

        return {
            'total': total,
            'by_status': by_status,
            'by_category': by_category,
            'by_priority': by_priority,
            'avg_response_hours': avg_hours,
        }
