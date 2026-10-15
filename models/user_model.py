from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from utils.database import get_collection, next_id, log_activity
from utils.helper import get_cached_value, invalidate_cache
from datetime import datetime


class User(UserMixin):
    def __init__(self, id, username, email, password_hash, full_name, role,
                 department='', phone='', avatar='default.png', banner='',
                 is_active=1, is_verified=0, last_login=None, created_at=None,
                 updated_at=None, **_kwargs):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.full_name = full_name
        self.role = role
        self.department = department
        self.phone = phone
        self.avatar = avatar
        self.banner = banner
        self.is_active_flag = is_active
        self.is_verified = is_verified
        self.last_login = last_login
        self.created_at = created_at
        self.updated_at = updated_at

    @property
    def is_active(self):
        return bool(self.is_active_flag)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'department': self.department,
            'phone': self.phone,
            'avatar': self.avatar,
            'banner': self.banner,
            'is_active': self.is_active_flag,
            'is_verified': self.is_verified,
            'last_login': self.last_login,
            'created_at': self.created_at,
        }

    @staticmethod
    def _doc_to_user(doc):
        if doc is None:
            return None
        return User(**doc)

    @staticmethod
    def get_by_id(user_id):
        doc = get_collection('users').find_one({'id': int(user_id)})
        return User._doc_to_user(doc)

    @staticmethod
    def get_by_username(username):
        doc = get_collection('users').find_one({'username': username})
        return User._doc_to_user(doc)

    @staticmethod
    def get_by_email(email):
        doc = get_collection('users').find_one({'email': email})
        return User._doc_to_user(doc)

    @staticmethod
    def get_all(role=None):
        col = get_collection('users')
        if role:
            docs = col.find({'role': role}).sort('created_at', -1)
        else:
            docs = col.find().sort('created_at', -1)
        return [User._doc_to_user(d) for d in docs]

    @staticmethod
    def create(username, email, password, full_name, role='analyst',
               department='Climate Science', phone=''):
        col = get_collection('users')
        password_hash = generate_password_hash(password)
        now = datetime.utcnow().isoformat()
        user_id = next_id('users')
        col.insert_one({
            'id': user_id,
            'username': username,
            'email': email,
            'password_hash': password_hash,
            'full_name': full_name,
            'role': role,
            'department': department,
            'phone': phone,
            'avatar': 'default.png',
            'banner': '',
            'is_active': 1,
            'is_verified': 0,
            'last_login': None,
            'created_at': now,
            'updated_at': now,
        })
        invalidate_cache('users:')
        return user_id

    def update_profile(self, **kwargs):
        allowed = ['full_name', 'email', 'phone', 'department', 'avatar', 'banner']
        updates = {}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                updates[key] = value
        if updates:
            updates['updated_at'] = datetime.utcnow().isoformat()
            get_collection('users').update_one(
                {'id': self.id}, {'$set': updates}
            )
            invalidate_cache('users:')
            # Reflect changes on the instance
            for k, v in updates.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    def update_password(self, new_password):
        self.password_hash = generate_password_hash(new_password)
        get_collection('users').update_one(
            {'id': self.id},
            {'$set': {
                'password_hash': self.password_hash,
                'updated_at': datetime.utcnow().isoformat(),
            }}
        )
        invalidate_cache('users:')

    @staticmethod
    def toggle_active(user_id):
        col = get_collection('users')
        doc = col.find_one({'id': user_id})
        if doc:
            new_val = 0 if doc.get('is_active', 1) == 1 else 1
            col.update_one({'id': user_id}, {'$set': {'is_active': new_val}})
            invalidate_cache('users:')

    @staticmethod
    def change_role(user_id, new_role):
        col = get_collection('users')
        col.update_one({'id': user_id}, {'$set': {'role': new_role, 'updated_at': datetime.utcnow().isoformat()}})
        invalidate_cache('users:')

    @staticmethod
    def delete_user(user_id):
        get_collection('users').delete_one({'id': user_id})
        invalidate_cache('users:')

    @staticmethod
    def count_by_role():
        return get_cached_value('users:count_by_role', lambda: (
            {doc['_id']: doc['count'] for doc in get_collection('users').aggregate([
                {'$group': {'_id': '$role', 'count': {'$sum': 1}}},
            ]) if doc['_id']}
        ), ttl_seconds=60)

    def record_login(self):
        now = datetime.utcnow().isoformat()
        get_collection('users').update_one(
            {'id': self.id},
            {'$set': {'last_login': now},
             '$push': {'login_history': {'timestamp': now, 'source': 'web'}}}
        )
        log_activity(self.id, 'login', f'User {self.username} logged in')

    @staticmethod
    def get_count():
        return get_cached_value('users:count', lambda: get_collection('users').count_documents({}), ttl_seconds=60)
