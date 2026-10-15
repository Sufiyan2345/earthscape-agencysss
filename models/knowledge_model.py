from utils.database import get_collection, next_id
from datetime import datetime


class KnowledgeBase:
    @staticmethod
    def create(title, content, category='general', tags='', created_by=None):
        col = get_collection('knowledge_base')
        kb_id = next_id('knowledge_base')
        now = datetime.utcnow().isoformat()
        col.insert_one({
            'id': kb_id,
            'title': title,
            'content': content,
            'category': category,
            'tags': tags,
            'is_published': 1,
            'view_count': 0,
            'created_by': created_by,
            'created_at': now,
            'updated_at': now,
        })
        return kb_id

    @staticmethod
    def get_all(category=None, search=None, published_only=False, limit=100):
        col_kb = get_collection('knowledge_base')
        col_users = get_collection('users')
        query = {}
        if published_only:
            query['is_published'] = 1
        if category:
            query['category'] = category
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'content': {'$regex': search, '$options': 'i'}},
                {'tags': {'$regex': search, '$options': 'i'}},
            ]

        docs = list(col_kb.find(query).sort('updated_at', -1).limit(limit))

        # Enrich with author name
        user_cache = {}
        for d in docs:
            uid = d.get('created_by')
            if uid and uid not in user_cache:
                u = col_users.find_one({'id': uid}, {'full_name': 1})
                user_cache[uid] = u
            u = user_cache.get(uid)
            d['author_name'] = u.get('full_name', '') if u else ''
        return docs

    @staticmethod
    def get_by_id(kb_id):
        col_kb = get_collection('knowledge_base')
        col_users = get_collection('users')
        doc = col_kb.find_one({'id': int(kb_id)})
        if doc:
            # Increment view count
            col_kb.update_one({'id': int(kb_id)}, {'$inc': {'view_count': 1}})
            uid = doc.get('created_by')
            if uid:
                u = col_users.find_one({'id': uid}, {'full_name': 1})
                doc['author_name'] = u.get('full_name', '') if u else ''
            else:
                doc['author_name'] = ''
        return doc

    @staticmethod
    def update(kb_id, title=None, content=None, category=None, tags=None, is_published=None):
        updates = {}
        if title is not None:
            updates['title'] = title
        if content is not None:
            updates['content'] = content
        if category is not None:
            updates['category'] = category
        if tags is not None:
            updates['tags'] = tags
        if is_published is not None:
            updates['is_published'] = is_published
        if updates:
            updates['updated_at'] = datetime.utcnow().isoformat()
            get_collection('knowledge_base').update_one(
                {'id': int(kb_id)}, {'$set': updates}
            )

    @staticmethod
    def delete(kb_id):
        get_collection('knowledge_base').delete_one({'id': int(kb_id)})

    @staticmethod
    def get_categories():
        pipeline = [
            {'$match': {'is_published': 1}},
            {'$group': {'_id': '$category', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}},
        ]
        return [{'category': d['_id'], 'count': d['count']}
                for d in get_collection('knowledge_base').aggregate(pipeline)
                if d['_id']]
