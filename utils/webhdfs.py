"""
Real WebHDFS client for EarthScape Climate System.

Connects to a real Hadoop HDFS cluster via the WebHDFS REST API.
Falls back to local filesystem simulation when HDFS is unavailable.

Set environment variables:
  HDFS_USE_REAL=true  - Enable real HDFS connection
  HDFS_NAMENODE=http://namenode:9870  - NameNode WebHDFS URL
  HDFS_USER=climateservice  - HDFS user name
"""

import os
import json
import requests
from urllib.parse import urlencode
from datetime import datetime
from config import Config

_use_real = Config.HDFS_USE_REAL
_namenode = Config.HDFS_NAMENODE
_user = Config.HDFS_USER


# ── Real WebHDFS operations ─────────────────────────────────────────────────

class WebHDFSClient:
    """Real WebHDFS REST API client."""

    def __init__(self, namenode_url=None, user=None):
        self.namenode = (namenode_url or _namenode).rstrip('/')
        self.user = user or _user
        self.session = requests.Session()

    def _url(self, path, op, **params):
        params['op'] = op
        params['user.name'] = self.user
        return f"{self.namenode}/webhdfs/v1{path}?{urlencode(params)}"

    def is_available(self):
        """Check if HDFS NameNode is reachable."""
        try:
            r = self.session.get(
                self._url('/', 'GETFILESTATUS'),
                timeout=3
            )
            return r.status_code in (200, 403)
        except Exception:
            return False

    def mkdirs(self, path):
        """Create directory and parents."""
        r = self.session.put(
            self._url(path, 'MKDIRS'),
            timeout=10
        )
        return r.status_code == 200 and r.json().get('boolean', False)

    def create_file(self, path, data, overwrite=True):
        """Upload file content to HDFS."""
        r = self.session.put(
            self._url(path, 'CREATE', overwrite=str(overwrite).lower()),
            data=data,
            headers={'Content-Type': 'application/octet-stream'},
            allow_redirects=True,
            timeout=30
        )
        return r.status_code in (200, 201)

    def append_file(self, path, data):
        """Append data to existing file."""
        r = self.session.post(
            self._url(path, 'APPEND'),
            data=data,
            headers={'Content-Type': 'application/octet-stream'},
            allow_redirects=True,
            timeout=30
        )
        return r.status_code == 200

    def open_file(self, path, offset=0, length=None):
        """Read file content from HDFS."""
        params = {}
        if offset:
            params['offset'] = offset
        if length:
            params['length'] = length
        r = self.session.get(
            self._url(path, 'OPEN', **params),
            allow_redirects=True,
            timeout=30
        )
        if r.status_code == 200:
            return r.content
        return None

    def delete(self, path, recursive=False):
        """Delete file or directory."""
        r = self.session.delete(
            self._url(path, 'DELETE', recursive=str(recursive).lower()),
            timeout=10
        )
        return r.status_code == 200 and r.json().get('boolean', False)

    def rename(self, src, dst):
        """Rename/move file."""
        r = self.session.put(
            self._url(src, 'RENAME', destination=dst),
            timeout=10
        )
        return r.status_code == 200 and r.json().get('boolean', False)

    def get_file_status(self, path):
        """Get file/directory status."""
        r = self.session.get(
            self._url(path, 'GETFILESTATUS'),
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('FileStatus', {})
        return None

    def list_status(self, path):
        """List directory contents."""
        r = self.session.get(
            self._url(path, 'LISTSTATUS'),
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('FileStatuses', {}).get('FileStatus', [])
        return []

    def get_content_summary(self, path):
        """Get directory content summary (size, file count, etc.)."""
        r = self.session.get(
            self._url(path, 'GETCONTENTSUMMARY'),
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('ContentSummary', {})
        return {}

    def set_replication(self, path, replication=3):
        """Set file replication factor."""
        r = self.session.put(
            self._url(path, 'SETREPLICATION', replication=str(replication)),
            timeout=10
        )
        return r.status_code == 200

    def get_home_directory(self):
        """Get user's home directory."""
        r = self.session.get(
            self._url('/', 'GETHOMEDIRECTORY'),
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('Path', '/')
        return '/'

    def upload_file(self, local_path, hdfs_path, overwrite=True):
        """Upload a local file to HDFS."""
        with open(local_path, 'rb') as f:
            data = f.read()
        return self.create_file(hdfs_path, data, overwrite=overwrite)

    def download_file(self, hdfs_path, local_path):
        """Download file from HDFS to local filesystem."""
        data = self.open_file(hdfs_path)
        if data is not None:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(data)
            return True
        return False


# ── HDFS Manager with real WebHDFS + local fallback ─────────────────────────

class RealHDFSManager:
    """
    HDFS Manager that uses real WebHDFS when available,
    falls back to local filesystem simulation otherwise.
    """

    def __init__(self):
        self.webhdfs = WebHDFSClient()
        self._use_real = None  # Lazy detect

    def _check_real(self):
        if self._use_real is not None:
            return self._use_real
        if not _use_real:
            self._use_real = False
            return False
        try:
            self._use_real = self.webhdfs.is_available()
        except Exception:
            self._use_real = False
        return self._use_real

    def using_real_hdfs(self):
        """Return whether this process is connected to a real NameNode."""
        return self._check_real()

    def status(self):
        """Return HDFS connection status."""
        if self._check_real():
            try:
                summary = self.webhdfs.get_content_summary(Config.HDFS_BASE_PATH)
                return {
                    'status': 'connected',
                    'backend': 'Real HDFS (WebHDFS)',
                    'namenode': _namenode,
                    'base_path': Config.HDFS_BASE_PATH,
                    'total_size': summary.get('length', 0),
                    'file_count': summary.get('fileCount', 0),
                    'directory_count': summary.get('directoryCount', 0),
                }
            except Exception as e:
                return {'status': 'error', 'backend': 'Real HDFS', 'error': str(e)}
        return {
            'status': 'connected',
            'backend': 'Local filesystem (HDFS simulation)',
            'message': 'Set HDFS_USE_REAL=true for real Hadoop HDFS.',
        }

    def mkdir(self, path):
        if self._check_real():
            return self.webhdfs.mkdirs(path)
        # Fallback: local
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        os.makedirs(local_path, exist_ok=True)
        return True

    def store_file(self, path, data, replication=3):
        """Store file in HDFS."""
        if self._check_real():
            self.webhdfs.mkdirs(os.path.dirname(path))
            if isinstance(data, str):
                data = data.encode('utf-8')
            result = self.webhdfs.create_file(path, data, overwrite=True)
            if result and replication > 1:
                self.webhdfs.set_replication(path, replication)
            return result
        # Fallback: local
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        mode = 'wb' if isinstance(data, bytes) else 'w'
        with open(local_path, mode) as f:
            f.write(data)
        return True

    def read_file(self, path):
        """Read file from HDFS."""
        if self._check_real():
            data = self.webhdfs.open_file(path)
            if data:
                return data.decode('utf-8', errors='replace')
            return None
        # Fallback: local
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if os.path.exists(local_path):
            with open(local_path, 'r', errors='replace') as f:
                return f.read()
        return None

    def list_directory(self, path):
        """List directory contents."""
        if self._check_real():
            statuses = self.webhdfs.list_status(path)
            return [
                {
                    'name': s.get('pathSuffix', ''),
                    'type': 'DIRECTORY' if s.get('type') == 'DIRECTORY' else 'FILE',
                    'length': s.get('length', 0),
                    'replication': s.get('replication', 0),
                    'modification_time': s.get('modificationTime', 0),
                    'permission': s.get('permission', ''),
                    'owner': s.get('owner', ''),
                }
                for s in statuses
            ]
        # Fallback: local
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if not os.path.exists(local_path):
            return []
        results = []
        for name in os.listdir(local_path):
            full = os.path.join(local_path, name)
            results.append({
                'name': name,
                'type': 'DIRECTORY' if os.path.isdir(full) else 'FILE',
                'length': os.path.getsize(full) if os.path.isfile(full) else 0,
                'replication': 0,
                'modification_time': int(os.path.getmtime(full) * 1000),
                'permission': '755',
                'owner': _user,
            })
        return results

    # Compatibility methods used by the Admin and Analyst HDFS browsers.
    def ls(self, path='/'):
        entries = self.list_directory(path)
        return [{
            'name': item['name'],
            'path': (path.rstrip('/') + '/' + item['name']) if path != '/' else '/' + item['name'],
            'is_dir': item['type'] == 'DIRECTORY',
            'size': item.get('length', 0),
            'modified': datetime.utcfromtimestamp(item.get('modification_time', 0) / 1000).isoformat()
                if item.get('modification_time') else '',
            'owner': item.get('owner', self.webhdfs.user),
        } for item in entries]

    def upload(self, hdfs_path, file_storage):
        """Store a Flask upload in real HDFS or the local fallback."""
        if self._check_real():
            data = file_storage.read()
            self.webhdfs.mkdirs(os.path.dirname(hdfs_path))
            return self.webhdfs.create_file(hdfs_path, data, overwrite=True)
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', hdfs_path.lstrip('/'))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        file_storage.save(local_path)
        return True

    def read_file(self, path):
        if self._check_real():
            data = self.webhdfs.open_file(path)
            return data.decode('utf-8', errors='replace') if data is not None else None
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if os.path.exists(local_path):
            with open(local_path, 'r', errors='replace') as f:
                return f.read()
        return None

    def download(self, path):
        from flask import Response
        if self._check_real():
            data = self.webhdfs.open_file(path)
            return Response(data or b'', mimetype='application/octet-stream') if data is not None else None
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if os.path.exists(local_path):
            with open(local_path, 'rb') as f:
                return Response(f.read(), mimetype='application/octet-stream')
        return None

    def delete_file(self, path):
        return self.delete(path)

    def rm(self, path, recursive=False):
        return self.delete(path, recursive=recursive)

    def df(self):
        summary = self.get_content_summary(Config.HDFS_BASE_PATH) if self._check_real() else {}
        total = summary.get('spaceConsumed', summary.get('length', 0))
        return {'total': total, 'used': summary.get('length', 0), 'remaining': 0,
                'usage_percent': 100 if total else 0, 'capacity': total, 'available': 0}

    def count_files(self, path='/'):
        return sum(1 for item in self.list_directory(path) if item['type'] == 'FILE')

    def get_tier_stats(self):
        return {'hot': {'count': 0, 'size': 0}, 'warm': {'count': 0, 'size': 0}, 'cold': {'count': 0, 'size': 0}}

    def get_file_info(self, path):
        status = self.get_file_status(path)
        return status or None

    def delete(self, path, recursive=False):
        """Delete file or directory."""
        if self._check_real():
            return self.webhdfs.delete(path, recursive=recursive)
        # Fallback: local
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if os.path.isdir(local_path) and recursive:
            import shutil
            shutil.rmtree(local_path, ignore_errors=True)
            return True
        elif os.path.isfile(local_path):
            os.remove(local_path)
            return True
        return False

    def upload_from_file(self, local_path, hdfs_path, replication=3):
        """Upload local file to HDFS."""
        if self._check_real():
            self.webhdfs.mkdirs(os.path.dirname(hdfs_path))
            result = self.webhdfs.upload_file(local_path, hdfs_path)
            if result and replication > 1:
                self.webhdfs.set_replication(hdfs_path, replication)
            return result
        # Fallback: local
        dest = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', hdfs_path.lstrip('/'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        import shutil
        shutil.copy2(local_path, dest)
        return True

    def download_to_file(self, hdfs_path, local_path):
        """Download file from HDFS to local."""
        if self._check_real():
            return self.webhdfs.download_file(hdfs_path, local_path)
        # Fallback: local
        src = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', hdfs_path.lstrip('/'))
        if os.path.exists(src):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            import shutil
            shutil.copy2(src, local_path)
            return True
        return False

    def exists(self, path):
        """Check if path exists in HDFS."""
        if self._check_real():
            status = self.webhdfs.get_file_status(path)
            return status is not None
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        return os.path.exists(local_path)

    def get_file_status(self, path):
        """Get file/directory status."""
        if self._check_real():
            s = self.webhdfs.get_file_status(path)
            if s:
                return {
                    'name': s.get('pathSuffix', ''),
                    'type': s.get('type', 'FILE'),
                    'length': s.get('length', 0),
                    'replication': s.get('replication', 0),
                    'permission': s.get('permission', ''),
                    'owner': s.get('owner', ''),
                    'modification_time': s.get('modificationTime', 0),
                }
            return None
        local_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', path.lstrip('/'))
        if not os.path.exists(local_path):
            return None
        return {
            'name': os.path.basename(local_path),
            'type': 'DIRECTORY' if os.path.isdir(local_path) else 'FILE',
            'length': os.path.getsize(local_path) if os.path.isfile(local_path) else 0,
            'replication': 0,
            'permission': '755',
            'owner': _user,
            'modification_time': int(os.path.getmtime(local_path) * 1000),
        }


# Global instance
real_hdfs = RealHDFSManager()
