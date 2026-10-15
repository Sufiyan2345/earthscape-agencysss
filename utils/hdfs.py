import os
import json
import gzip
import shutil
import hashlib
import zlib
import uuid
from datetime import datetime
from config import Config
from utils.database import get_collection, next_id


# ── DataNode Manager ─────────────────────────────────────────────────────────

class DataNodeManager:
    """Manages simulated HDFS DataNodes with health monitoring."""

    @staticmethod
    def get_all():
        col = get_collection('hdfs_datanodes')
        return list(col.find().sort('node_name', 1))

    @staticmethod
    def get_alive():
        col = get_collection('hdfs_datanodes')
        return list(col.find({'status': 'alive'}).sort('remaining', -1))

    @staticmethod
    def get_by_id(node_id):
        col = get_collection('hdfs_datanodes')
        return col.find_one({'id': node_id})

    @staticmethod
    def heartbeat(node_id):
        col = get_collection('hdfs_datanodes')
        col.update_one(
            {'id': node_id},
            {'$set': {'last_heartbeat': datetime.utcnow().isoformat(), 'status': 'alive'}},
        )

    @staticmethod
    def toggle_status(node_id):
        col = get_collection('hdfs_datanodes')
        node = col.find_one({'id': node_id})
        if node:
            new_status = 'dead' if node.get('status') == 'alive' else 'alive'
            col.update_one({'id': node_id}, {'$set': {'status': new_status}})

    @staticmethod
    def update_usage(node_id, used_delta, block_delta=0):
        col = get_collection('hdfs_datanodes')
        node = col.find_one({'id': node_id})
        if node:
            new_used = max(0, (node.get('used') or 0) + used_delta)
            new_remaining = max(0, (node.get('remaining') or 0) - used_delta)
            new_blocks = max(0, (node.get('block_count') or 0) + block_delta)
            col.update_one(
                {'id': node_id},
                {'$set': {
                    'used': new_used, 'remaining': new_remaining,
                    'block_count': new_blocks,
                    'last_heartbeat': datetime.utcnow().isoformat(),
                }},
            )

    @staticmethod
    def get_health_summary():
        col = get_collection('hdfs_datanodes')
        total = col.count_documents({})
        alive = col.count_documents({'status': 'alive'})
        pipeline = list(col.aggregate([
            {'$group': {
                '_id': None,
                'total_cap': {'$sum': {'$ifNull': ['$capacity', 0]}},
                'total_used': {'$sum': {'$ifNull': ['$used', 0]}},
                'total_rem': {'$sum': {'$ifNull': ['$remaining', 0]}},
                'total_blocks': {'$sum': {'$ifNull': ['$block_count', 0]}},
            }},
        ]))
        stats = pipeline[0] if pipeline else {'total_cap': 0, 'total_used': 0, 'total_rem': 0, 'total_blocks': 0}
        return {
            'total_nodes': total, 'alive_nodes': alive, 'dead_nodes': total - alive,
            'total_capacity': stats['total_cap'], 'total_used': stats['total_used'],
            'total_remaining': stats['total_rem'], 'total_blocks': stats['total_blocks'],
            'health_pct': round((alive / total * 100), 1) if total > 0 else 0,
        }

    @staticmethod
    def select_node(prefer_min_used=True):
        """Select best DataNode for new block placement."""
        col = get_collection('hdfs_datanodes')
        if prefer_min_used:
            return col.find_one({'status': 'alive'}, sort=[('remaining', -1)])
        else:
            # Random selection: get all alive and pick one
            alive = list(col.find({'status': 'alive'}))
            import random
            return random.choice(alive) if alive else None


# ── Block Manager ────────────────────────────────────────────────────────────

class BlockManager:
    """Splits files into blocks and tracks block locations on DataNodes."""

    BLOCK_SIZE = 128 * 1024 * 1024  # 128 MB default

    @staticmethod
    def split_and_store(file_id, local_path, replication=3):
        """Split a file into blocks, store on DataNodes, record in DB."""
        col = get_collection('hdfs_blocks')
        file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        if file_size == 0:
            return 0

        block_size = BlockManager.BLOCK_SIZE
        num_blocks = max(1, (file_size + block_size - 1) // block_size)
        blocks_created = 0

        with open(local_path, 'rb') as f:
            for idx in range(num_blocks):
                block_data = f.read(block_size)
                if not block_data:
                    break
                block_id = str(uuid.uuid4()).replace('-', '')[:16]
                checksum = zlib.crc32(block_data)
                offset = idx * block_size
                length = len(block_data)

                # Store block data in node storage directories
                alive_nodes = DataNodeManager.get_alive()
                replicas_placed = 0
                for node in alive_nodes[:replication]:
                    node_dir = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', '.blocks', node['node_name'])
                    os.makedirs(node_dir, exist_ok=True)
                    block_file = os.path.join(node_dir, block_id)
                    with open(block_file, 'wb') as bf:
                        bf.write(block_data)

                    col.insert_one({
                        'id': next_id('hdfs_blocks'),
                        'file_id': file_id,
                        'block_id': block_id,
                        'block_index': idx,
                        'offset_bytes': offset,
                        'length_bytes': length,
                        'datanode_id': node['id'],
                        'replica_index': replicas_placed,
                        'checksum': str(checksum),
                    })
                    DataNodeManager.update_usage(node['id'], length, 1)
                    replicas_placed += 1

                blocks_created += 1

        return blocks_created

    @staticmethod
    def get_blocks(file_id):
        blocks_col = get_collection('hdfs_blocks')
        datanodes_col = get_collection('hdfs_datanodes')
        blocks = list(blocks_col.find({'file_id': file_id}).sort([('block_index', 1), ('replica_index', 1)]))
        # Resolve datanode info via two-query pattern
        node_ids = list(set(b.get('datanode_id') for b in blocks if b.get('datanode_id')))
        node_map = {}
        if node_ids:
            for n in datanodes_col.find({'id': {'$in': node_ids}}):
                node_map[n['id']] = n
        result = []
        for b in blocks:
            entry = dict(b)
            node = node_map.get(b.get('datanode_id'), {})
            entry['node_name'] = node.get('node_name', '')
            entry['host'] = node.get('host', '')
            entry['port'] = node.get('port', '')
            entry['node_status'] = node.get('status', '')
            entry['rack'] = node.get('rack', '')
            result.append(entry)
        return result

    @staticmethod
    def verify_integrity(file_id):
        """Verify checksums of all blocks for a file."""
        blocks = BlockManager.get_blocks(file_id)
        results = {'total': len(blocks), 'verified': 0, 'corrupted': 0, 'missing': 0, 'details': []}
        for b in blocks:
            node_dir = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', '.blocks', b.get('node_name', ''))
            block_file = os.path.join(node_dir, b['block_id'])
            if not os.path.exists(block_file):
                results['missing'] += 1
                results['details'].append({'block': b['block_id'], 'status': 'missing', 'node': b.get('node_name', '?')})
                continue
            with open(block_file, 'rb') as f:
                actual_crc = str(zlib.crc32(f.read()))
            if actual_crc == b['checksum']:
                results['verified'] += 1
                results['details'].append({'block': b['block_id'], 'status': 'ok', 'node': b.get('node_name', '?')})
            else:
                results['corrupted'] += 1
                results['details'].append({'block': b['block_id'], 'status': 'corrupted', 'node': b.get('node_name', '?')})
        return results


# ── Compression Manager ──────────────────────────────────────────────────────

class CompressionManager:
    """Handles gzip compression/decompression for HDFS storage."""

    @staticmethod
    def compress_file(src_path, dest_path=None):
        if dest_path is None:
            dest_path = src_path + '.gz'
        with open(src_path, 'rb') as f_in:
            with gzip.open(dest_path, 'wb', compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
        return dest_path

    @staticmethod
    def decompress_file(src_path, dest_path=None):
        if dest_path is None:
            dest_path = src_path.replace('.gz', '')
        with gzip.open(src_path, 'rb') as f_in:
            with open(dest_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return dest_path

    @staticmethod
    def get_ratio(original_size, compressed_size):
        if original_size == 0:
            return 0
        return round((1 - compressed_size / original_size) * 100, 1)


# ── Partition Manager ────────────────────────────────────────────────────────

class PartitionManager:
    """Manages data partitioning by date, region, and type."""

    @staticmethod
    def get_partition_path(data_type='weather', year=None, region=None):
        """Build partition path: /climate/{type}/{year}/{region}/"""
        parts = ['climate', data_type or 'general']
        if year:
            parts.append(str(year))
        if region:
            parts.append(region.lower().replace(' ', '_'))
        return '/' + '/'.join(parts)

    @staticmethod
    def get_or_create_partition(partition_key, partition_type, partition_value, hdfs_path, parent=''):
        col = get_collection('hdfs_partitions')
        row = col.find_one({'partition_key': partition_key})
        if row:
            return dict(row)
        pid = next_id('hdfs_partitions')
        col.insert_one({
            'id': pid,
            'partition_key': partition_key,
            'partition_type': partition_type,
            'partition_value': partition_value,
            'hdfs_path': hdfs_path,
            'parent_partition': parent,
            'status': 'active',
        })
        return {'id': pid, 'partition_key': partition_key, 'hdfs_path': hdfs_path}

    @staticmethod
    def update_partition_stats(partition_key, record_delta=0, size_delta=0):
        col = get_collection('hdfs_partitions')
        part = col.find_one({'partition_key': partition_key})
        if part:
            new_records = (part.get('record_count') or 0) + record_delta
            new_size = (part.get('total_size') or 0) + size_delta
            col.update_one(
                {'partition_key': partition_key},
                {'$set': {'record_count': new_records, 'total_size': new_size}},
            )

    @staticmethod
    def get_all(partition_type=None):
        col = get_collection('hdfs_partitions')
        if partition_type:
            return list(col.find({'partition_type': partition_type}).sort('hdfs_path', 1))
        else:
            return list(col.find().sort('hdfs_path', 1))

    @staticmethod
    def get_tree():
        """Build partition tree structure."""
        all_parts = PartitionManager.get_all()
        tree = {}
        for p in all_parts:
            tree[p['partition_key']] = {**p, 'children': []}
        for p in all_parts:
            parent = p.get('parent_partition', '')
            if parent and parent in tree:
                tree[parent]['children'].append(p)
        return {k: v for k, v in tree.items() if not v.get('parent_partition')}

    @staticmethod
    def delete_partition(partition_key):
        col = get_collection('hdfs_partitions')
        col.update_one(
            {'partition_key': partition_key},
            {'$set': {'status': 'deleted'}},
        )


# ── HDFS Manager (main interface) ───────────────────────────────────────────

class HDFSManager:
    """HDFS manager with block storage, replication, compression, partitioning."""

    def __init__(self):
        self.base_path = os.path.join(Config.UPLOAD_FOLDER, 'hdfs')
        os.makedirs(self.base_path, exist_ok=True)
        os.makedirs(os.path.join(self.base_path, '.blocks'), exist_ok=True)
        self._ensure_climate_dirs()

    def _ensure_climate_dirs(self):
        dirs = [
            '/climate', '/climate/satellite', '/climate/weather',
            '/climate/sensors', '/climate/archive',
        ]
        for d in dirs:
            self.mkdir(d)

    def _resolve_path(self, hdfs_path):
        clean = hdfs_path.lstrip('/')
        return os.path.join(self.base_path, clean)

    def _file_checksum(self, filepath):
        h = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    # ── Basic file operations ──

    def mkdir(self, hdfs_path):
        path = self._resolve_path(hdfs_path)
        os.makedirs(path, exist_ok=True)
        col = get_collection('hdfs_files')
        existing = col.find_one({'file_path': hdfs_path})
        if not existing:
            col.insert_one({
                'id': next_id('hdfs_files'),
                'file_path': hdfs_path,
                'file_name': os.path.basename(hdfs_path) or '/',
                'is_directory': 1,
                'owner': 'climate_user',
                'permissions': 'rwxr-xr-x',
            })
        return True

    def put(self, local_path, hdfs_path, compression='gzip', replication=3):
        """Store file in HDFS with block splitting, compression, and replication."""
        dest = self._resolve_path(hdfs_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        # Copy original file
        shutil.copy2(local_path, dest)
        file_size = os.path.getsize(dest)
        checksum = self._file_checksum(dest)

        # Compress if requested
        compressed_path = dest
        compression_used = 'none'
        if compression == 'gzip' and file_size > 0:
            try:
                compressed_path = CompressionManager.compress_file(dest, dest + '.gz')
                compression_used = 'gzip'
            except Exception:
                compressed_path = dest

        # Register in hdfs_files
        col = get_collection('hdfs_files')
        existing = col.find_one({'file_path': hdfs_path})
        if existing:
            col.update_one(
                {'id': existing['id']},
                {'$set': {
                    'file_name': os.path.basename(hdfs_path),
                    'file_size': file_size,
                    'replication_factor': replication,
                    'block_size': BlockManager.BLOCK_SIZE,
                    'owner': 'climate_user',
                    'permissions': 'rw-r--r--',
                    'is_directory': 0,
                    'checksum': checksum,
                    'compression': compression_used,
                }},
            )
            file_id = existing['id']
        else:
            file_id = next_id('hdfs_files')
            col.insert_one({
                'id': file_id,
                'file_path': hdfs_path,
                'file_name': os.path.basename(hdfs_path),
                'file_size': file_size,
                'replication_factor': replication,
                'block_size': BlockManager.BLOCK_SIZE,
                'owner': 'climate_user',
                'permissions': 'rw-r--r--',
                'is_directory': 0,
                'checksum': checksum,
                'compression': compression_used,
            })

        # Split into blocks and replicate across DataNodes
        blocks = BlockManager.split_and_store(file_id, local_path, replication)

        return file_id, blocks

    def get(self, hdfs_path, local_path):
        src = self._resolve_path(hdfs_path)
        # Check for compressed version
        if os.path.exists(src + '.gz'):
            CompressionManager.decompress_file(src + '.gz', local_path)
            return True
        if os.path.exists(src):
            shutil.copy2(src, local_path)
            return True
        # Try reconstructing from blocks
        return self._reconstruct_from_blocks(hdfs_path, local_path)

    def _reconstruct_from_blocks(self, hdfs_path, local_path):
        """Reconstruct file from blocks stored on DataNodes."""
        files_col = get_collection('hdfs_files')
        row = files_col.find_one({'file_path': hdfs_path})
        if not row:
            return False
        blocks = BlockManager.get_blocks(row['id'])
        if not blocks:
            return False

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        seen_indexes = set()
        with open(local_path, 'wb') as out:
            for b in blocks:
                if b['block_index'] in seen_indexes:
                    continue
                seen_indexes.add(b['block_index'])
                node_dir = os.path.join(Config.UPLOAD_FOLDER, 'hdfs', '.blocks', b.get('node_name', ''))
                block_file = os.path.join(node_dir, b['block_id'])
                if os.path.exists(block_file):
                    with open(block_file, 'rb') as bf:
                        out.write(bf.read())
        return os.path.exists(local_path) and os.path.getsize(local_path) > 0

    def ls(self, hdfs_path='/'):
        path = self._resolve_path(hdfs_path)
        if not os.path.exists(path):
            return []
        results = []
        for item in os.listdir(path):
            if item.startswith('.'):
                continue
            full = os.path.join(path, item)
            stat = os.stat(full)
            results.append({
                'name': item,
                'path': os.path.join(hdfs_path, item).replace('\\', '/'),
                'is_dir': os.path.isdir(full),
                'type': 'directory' if os.path.isdir(full) else 'file',
                'size': stat.st_size if not os.path.isdir(full) else 0,
                'replication': 3 if not os.path.isdir(full) else 0,
                'block_size': 134217728,
                'owner': 'climate_user',
                'permissions': 'rwxr-xr-x' if os.path.isdir(full) else 'rw-r--r--',
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return sorted(results, key=lambda x: (not x['is_dir'], x['name']))

    def cat(self, hdfs_path):
        path = self._resolve_path(hdfs_path)
        if os.path.exists(path + '.gz'):
            try:
                with gzip.open(path + '.gz', 'rt', errors='replace') as f:
                    return f.read(1024 * 100)
            except Exception:
                pass
        if os.path.exists(path) and not os.path.isdir(path):
            with open(path, 'r', errors='replace') as f:
                return f.read(1024 * 100)
        return None

    def rm(self, hdfs_path, recursive=False):
        path = self._resolve_path(hdfs_path)
        if not os.path.exists(path):
            return False
        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
                # Also remove compressed versions
                if os.path.exists(path + '.gz'):
                    os.remove(path + '.gz')
            else:
                return False
        else:
            os.remove(path)
            if os.path.exists(path + '.gz'):
                os.remove(path + '.gz')
        # Clean up DB
        col = get_collection('hdfs_files')
        col.delete_one({'file_path': hdfs_path})
        return True

    def du(self, hdfs_path='/'):
        path = self._resolve_path(hdfs_path)
        total = 0
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    if f.startswith('.'):
                        continue
                    fp = os.path.join(dirpath, f)
                    total += os.path.getsize(fp)
        else:
            total = os.path.getsize(path)
        return total

    def df(self):
        total, used, free = shutil.disk_usage(self.base_path)
        return {
            'total': total, 'used': used, 'free': free,
            'usage_percent': round((used / total) * 100, 2) if total > 0 else 0,
            'capacity': _fmt_size(total), 'remaining': _fmt_size(free),
        }

    def exists(self, hdfs_path):
        return os.path.exists(self._resolve_path(hdfs_path))

    def get_file_info(self, hdfs_path):
        path = self._resolve_path(hdfs_path)
        if not os.path.exists(path):
            return None
        stat = os.stat(path)
        col = get_collection('hdfs_files')
        row = col.find_one({'file_path': hdfs_path})
        info = {
            'name': os.path.basename(path), 'path': hdfs_path,
            'is_dir': os.path.isdir(path),
            'size': stat.st_size if not os.path.isdir(path) else 0,
            'replication': 3, 'block_size': 134217728,
            'owner': 'climate_user',
            'permissions': 'rwxr-xr-x' if os.path.isdir(path) else 'rw-r--r--',
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'checksum': '', 'compression': 'none',
        }
        if row:
            info['checksum'] = row['checksum']
            info['compression'] = row['compression']
            info['replication_factor'] = row['replication_factor']
        return info

    def count_files(self, hdfs_path='/'):
        path = self._resolve_path(hdfs_path)
        dirs = files = 0
        if os.path.isdir(path):
            for item in os.listdir(path):
                if item.startswith('.'):
                    continue
                full = os.path.join(path, item)
                if os.path.isdir(full):
                    dirs += 1
                else:
                    files += 1
        return {'directories': dirs, 'files': files}

    # ── Upload helper for Flask file objects ──

    def upload(self, hdfs_path, file_obj):
        dest = self._resolve_path(hdfs_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        file_obj.save(dest)
        return True

    def read_file(self, hdfs_path):
        return self.cat(hdfs_path)

    def download(self, hdfs_path):
        from flask import send_file
        path = self._resolve_path(hdfs_path)
        if os.path.exists(path):
            return send_file(path, as_attachment=True)
        return None

    def delete(self, hdfs_path):
        return self.rm(hdfs_path, recursive=True)

    # ── Storage tiering ──

    @staticmethod
    def get_tier_stats():
        col = get_collection('hdfs_files')
        pipeline = list(col.aggregate([
            {'$match': {'is_directory': 0}},
            {'$group': {
                '_id': {'$ifNull': ['$tier', 'hot']},
                'cnt': {'$sum': 1},
                'total_size': {'$sum': {'$ifNull': ['$file_size', 0]}},
            }},
        ]))
        result = {'hot': {'count': 0, 'size': 0}, 'warm': {'count': 0, 'size': 0}, 'cold': {'count': 0, 'size': 0}}
        for r in pipeline:
            tier = r['_id'] or 'hot'
            if tier in result:
                result[tier] = {'count': r['cnt'], 'size': r['total_size']}
        return result

    @staticmethod
    def classify_tier(file_path):
        """Classify file tier based on last access time."""
        col = get_collection('hdfs_files')
        row = col.find_one({'file_path': file_path})
        if not row or not row.get('created_at'):
            return 'hot'
        try:
            created = datetime.fromisoformat(row['created_at'])
            age_days = (datetime.utcnow() - created).days
            if age_days <= 7:
                return 'hot'
            elif age_days <= 30:
                return 'warm'
            else:
                return 'cold'
        except Exception:
            return 'hot'


def _fmt_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"


# ── Singleton instances ──
hdfs_manager = HDFSManager()
datanode_manager = DataNodeManager()
block_manager = BlockManager()
partition_manager = PartitionManager()
compression_manager = CompressionManager()
