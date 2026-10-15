from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from analyst import analyst_bp
from auth.decorators import analyst_required
from utils.hdfs import hdfs_manager, datanode_manager, block_manager, partition_manager
from utils.helper import format_file_size
from utils.database import get_collection, next_id
from utils.webhdfs import real_hdfs
import os


def _storage():
    return real_hdfs if real_hdfs.using_real_hdfs() else hdfs_manager


@analyst_bp.route('/hdfs', methods=['GET', 'POST'])
@login_required
@analyst_required
def hdfs():
    """HDFS File Browser with partition management."""
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'create_dir':
            dir_name = request.form.get('dir_name', '').strip()
            path = request.form.get('path', '/')
            if dir_name:
                new_path = os.path.join(path, dir_name).replace('\\', '/')
                _storage().mkdir(new_path)
                flash(f'Directory "{dir_name}" created successfully.', 'success')
            else:
                flash('Directory name is required.', 'danger')
            return redirect(url_for('analyst.hdfs', path=path))

        elif action == 'upload':
            path = request.form.get('path', '/')
            file = request.files.get('file')
            if file and file.filename:
                file_path = os.path.join(path, file.filename).replace('\\', '/')
                _storage().upload(file_path, file)

                # Register in hdfs_files and create blocks
                local_dest = _storage()._resolve_path(file_path) if not real_hdfs.using_real_hdfs() else ''
                file_size = os.path.getsize(local_dest) if local_dest and os.path.exists(local_dest) else 0
                checksum = hdfs_manager._file_checksum(local_dest) if local_dest and os.path.exists(local_dest) else ''

                conn_col = get_collection('hdfs_files')
                existing = conn_col.find_one({'file_path': file_path})
                if existing:
                    conn_col.update_one(
                        {'id': existing['id']},
                        {'$set': {
                            'file_name': file.filename,
                            'file_size': file_size,
                            'is_directory': 0,
                            'replication_factor': 3,
                            'block_size': 134217728,
                            'owner': 'climate_user',
                            'permissions': 'rw-r--r--',
                            'checksum': checksum,
                            'compression': 'none',
                        }},
                    )
                    file_id = existing['id']
                else:
                    file_id = next_id('hdfs_files')
                    conn_col.insert_one({
                        'id': file_id,
                        'file_path': file_path,
                        'file_name': file.filename,
                        'file_size': file_size,
                        'is_directory': 0,
                        'replication_factor': 3,
                        'block_size': 134217728,
                        'owner': 'climate_user',
                        'permissions': 'rw-r--r--',
                        'checksum': checksum,
                        'compression': 'none',
                    })

                # Split into blocks across DataNodes
                block_manager.split_and_store(file_id, local_dest, replication=3)

                # Update partition stats
                part_key = _path_to_partition(file_path)
                partition_manager.update_partition_stats(part_key, record_delta=0, size_delta=file_size)

                flash(f'File "{file.filename}" uploaded and distributed across DataNodes.', 'success')
            else:
                flash('No file selected.', 'danger')
            return redirect(url_for('analyst.hdfs', path=path))

        elif action == 'delete':
            file_path = request.form.get('path', '')
            if file_path:
                _storage().delete(file_path)
                flash('File deleted successfully.', 'success')
            return redirect(url_for('analyst.hdfs', path=os.path.dirname(file_path).replace('\\', '/')))

        elif action == 'create_partition':
            ptype = request.form.get('partition_type', 'type')
            pvalue = request.form.get('partition_value', '').strip()
            if pvalue:
                pkey = 'climate_data_' + pvalue.lower().replace(' ', '_')
                ppath = partition_manager.get_partition_path(data_type=pvalue.lower())
                parent = 'climate_data'
                partition_manager.get_or_create_partition(pkey, ptype, pvalue, ppath, parent)
                _storage().mkdir(ppath)
                flash(f'Partition "{pvalue}" created at {ppath}', 'success')
            else:
                flash('Partition value is required.', 'danger')
            return redirect(url_for('analyst.hdfs'))

        return redirect(url_for('analyst.hdfs'))

    # GET request
    path = request.args.get('path', '/')
    action = request.args.get('action', '')

    # Download a file (returns the file itself)
    if action == 'download' and path:
        response = _storage().download(path)
        if response:
            return response
        flash('File not found in HDFS.', 'danger')
        return redirect(url_for('analyst.hdfs',
                                path=os.path.dirname(path).replace('\\', '/') or '/'))

    # View file content inline (browse the file's parent directory)
    view_content = None
    view_file = None
    if action == 'view' and path:
        view_content = _storage().read_file(path)
        view_file = os.path.basename(path)
        path = os.path.dirname(path).replace('\\', '/') or '/'

    storage = _storage()
    files = storage.ls(path)
    disk_info = storage.df()
    partitions = partition_manager.get_all()
    health = datanode_manager.get_health_summary()

    if path and path != '/':
        parent_path = os.path.dirname(path).replace('\\', '/')
        if not parent_path.startswith('/'):
            parent_path = '/' + parent_path
    else:
        parent_path = '/'

    total = disk_info.get('total', 1073741824)
    used = disk_info.get('used', 0)
    usage_percent = round((used / max(total, 1)) * 100, 1)

    # Get block info for files in current directory
    files_col = get_collection('hdfs_files')
    file_blocks = {}
    for f in files:
        if not f['is_dir']:
            row = files_col.find_one({'file_path': f['path']})
            if row:
                blocks = block_manager.get_blocks(row['id'])
                file_blocks[f['path']] = len(blocks)

    return render_template('analyst/hdfs.html',
                         files=files,
                         current_path=path,
                         parent_path=parent_path,
                         disk_info=disk_info,
                         usage_percent=usage_percent,
                         storage_used=format_file_size(used),
                         storage_total=format_file_size(total),
                         format_file_size=format_file_size,
                         partitions=partitions,
                         health=health,
                         file_blocks=file_blocks,
                         view_content=view_content,
                         view_file=view_file,
                         active_page='hdfs')


@analyst_bp.route('/hdfs/file-info')
@login_required
@analyst_required
def hdfs_file_info():
    path = request.args.get('path', '')
    info = hdfs_manager.get_file_info(path)
    if info:
        files_col = get_collection('hdfs_files')
        row = files_col.find_one({'file_path': path})
        blocks = []
        if row:
            blocks = block_manager.get_blocks(row['id'])
        info['blocks'] = blocks
        info['block_count'] = len(blocks)
        return jsonify(info)
    return jsonify({'error': 'File not found'})


@analyst_bp.route('/hdfs/partitions')
@login_required
@analyst_required
def hdfs_partitions():
    parts = partition_manager.get_all()
    return jsonify(parts)


@analyst_bp.route('/hdfs/verify/<int:file_id>', methods=['POST'])
@login_required
@analyst_required
def hdfs_verify(file_id):
    result = block_manager.verify_integrity(file_id)
    return jsonify(result)


def _path_to_partition(hdfs_path):
    """Determine partition key from HDFS path."""
    parts = hdfs_path.strip('/').split('/')
    if len(parts) >= 2 and parts[0] == 'climate_data':
        return 'climate_data_' + parts[1]
    return 'climate_data'
