from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from admin import admin_bp
from auth.decorators import admin_required
from utils.hdfs import hdfs_manager, datanode_manager, block_manager, partition_manager
from utils.helper import format_file_size
from utils.database import get_collection
from utils.webhdfs import real_hdfs


def _storage():
    return real_hdfs if real_hdfs.using_real_hdfs() else hdfs_manager


@admin_bp.route('/hdfs')
@login_required
@admin_required
def hdfs():
    """HDFS Health Monitoring Dashboard."""
    health = datanode_manager.get_health_summary()
    nodes = datanode_manager.get_all()
    storage = _storage()
    disk_info = storage.df()
    file_count = storage.count_files('/')
    tier_stats = storage.get_tier_stats()
    partitions = partition_manager.get_all()

    # DB file stats
    files_col = get_collection('hdfs_files')
    blocks_col = get_collection('hdfs_blocks')
    total_files = files_col.count_documents({'is_directory': 0})
    total_dirs = files_col.count_documents({'is_directory': 1})
    total_blocks = blocks_col.count_documents({})
    size_pipeline = list(files_col.aggregate([
        {'$match': {'is_directory': 0}},
        {'$group': {'_id': None, 'total': {'$sum': {'$ifNull': ['$file_size', 0]}}}},
    ]))
    total_size = size_pipeline[0]['total'] if size_pipeline else 0

    # Pre-compute dynamic CSS values (avoids Jinja2 block tags inside inline styles)
    hp = health.get('health_pct', 0)
    health_color = 'var(--success)' if hp > 66 else ('var(--warning)' if hp > 33 else 'var(--danger)')
    health_label = 'Healthy' if hp > 66 else ('Degraded' if hp > 33 else 'Critical')
    up = disk_info.get('usage_percent', 0)
    disk_bg = 'var(--danger)' if up > 80 else ('var(--warning)' if up > 60 else 'var(--success)')

    return render_template('admin/hdfs.html',
                         health=health, nodes=nodes, disk_info=disk_info,
                         file_count=file_count, tier_stats=tier_stats,
                         partitions=partitions,
                         total_files=total_files, total_dirs=total_dirs,
                         total_blocks=total_blocks, total_size=total_size,
                         format_file_size=format_file_size,
                         health_color=health_color, health_label=health_label,
                         disk_bg=disk_bg,
                         active_page='hdfs')


@admin_bp.route('/hdfs/mkdir', methods=['POST'])
@login_required
@admin_required
def hdfs_mkdir():
    path = request.form.get('path', '')
    if path:
        _storage().mkdir(path)
        flash(f'Directory created: {path}', 'success')
    else:
        flash('Path is required.', 'danger')
    return redirect(url_for('admin.hdfs'))


@admin_bp.route('/hdfs/delete', methods=['POST'])
@login_required
@admin_required
def hdfs_delete():
    path = request.form.get('path', '')
    recursive = request.form.get('recursive', False)
    if path:
        _storage().rm(path, recursive=bool(recursive))
        flash(f'Deleted: {path}', 'success')
    return redirect(url_for('admin.hdfs'))


@admin_bp.route('/hdfs/file-info')
@login_required
@admin_required
def hdfs_file_info():
    path = request.args.get('path', '/')
    info = _storage().get_file_info(path)
    if info:
        # Get block details
        files_col = get_collection('hdfs_files')
        row = files_col.find_one({'file_path': path})
        blocks = []
        if row:
            blocks = block_manager.get_blocks(row['id'])
        info['blocks'] = blocks
        info['block_count'] = len(blocks)
        return jsonify(info)
    return jsonify({'error': 'File not found'})


@admin_bp.route('/hdfs/disk-usage')
@login_required
@admin_required
def hdfs_disk_usage():
    return jsonify(_storage().df())


@admin_bp.route('/hdfs/datanode/<int:node_id>/toggle', methods=['POST'])
@login_required
@admin_required
def hdfs_datanode_toggle(node_id):
    datanode_manager.toggle_status(node_id)
    flash('DataNode status toggled.', 'success')
    return redirect(url_for('admin.hdfs'))


@admin_bp.route('/hdfs/datanode/<int:node_id>/heartbeat', methods=['POST'])
@login_required
@admin_required
def hdfs_datanode_heartbeat(node_id):
    datanode_manager.heartbeat(node_id)
    flash('Heartbeat sent.', 'success')
    return redirect(url_for('admin.hdfs'))


@admin_bp.route('/hdfs/datanode/<int:node_id>/blocks')
@login_required
@admin_required
def hdfs_datanode_blocks(node_id):
    blocks_col = get_collection('hdfs_blocks')
    files_col = get_collection('hdfs_files')
    blocks = list(blocks_col.find({'datanode_id': node_id}).sort('block_index', 1))
    # Resolve file paths via two-query pattern
    file_ids = list(set(b.get('file_id') for b in blocks if b.get('file_id')))
    file_map = {}
    if file_ids:
        for f in files_col.find({'id': {'$in': file_ids}}):
            file_map[f['id']] = f
    result = []
    for b in blocks:
        entry = dict(b)
        finfo = file_map.get(b.get('file_id'), {})
        entry['file_path'] = finfo.get('file_path', '')
        entry['file_name'] = finfo.get('file_name', '')
        result.append(entry)
    return jsonify(result)


@admin_bp.route('/hdfs/verify/<int:file_id>', methods=['POST'])
@login_required
@admin_required
def hdfs_verify_integrity(file_id):
    result = block_manager.verify_integrity(file_id)
    return jsonify(result)


@admin_bp.route('/hdfs/partitions')
@login_required
@admin_required
def hdfs_partitions():
    parts = partition_manager.get_all()
    return jsonify(parts)


@admin_bp.route('/hdfs/tier-stats')
@login_required
@admin_required
def hdfs_tier_stats():
    return jsonify(_storage().get_tier_stats())


@admin_bp.route('/hdfs/browse')
@login_required
@admin_required
def hdfs_browse():
    path = request.args.get('path', '/')
    storage = _storage()
    files = storage.ls(path)
    disk_info = storage.df()
    file_count = storage.count_files(path)

    if path and path != '/':
        parent = '/'.join(path.rstrip('/').split('/')[:-1]) or '/'
    else:
        parent = '/'

    # Get stats for template
    files_col = get_collection('hdfs_files')
    blocks_col = get_collection('hdfs_blocks')
    total_files = files_col.count_documents({'is_directory': 0})
    total_dirs = files_col.count_documents({'is_directory': 1})
    total_blocks = blocks_col.count_documents({})
    size_pipeline = list(files_col.aggregate([
        {'$match': {'is_directory': 0}},
        {'$group': {'_id': None, 'total': {'$sum': {'$ifNull': ['$file_size', 0]}}}},
    ]))
    total_size = size_pipeline[0]['total'] if size_pipeline else 0

    # Pre-compute dynamic CSS values
    health = datanode_manager.get_health_summary()
    hp = health.get('health_pct', 0)
    health_color = 'var(--success)' if hp > 66 else ('var(--warning)' if hp > 33 else 'var(--danger)')
    health_label = 'Healthy' if hp > 66 else ('Degraded' if hp > 33 else 'Critical')
    up = disk_info.get('usage_percent', 0)
    disk_bg = 'var(--danger)' if up > 80 else ('var(--warning)' if up > 60 else 'var(--success)')

    return render_template('admin/hdfs.html', files=files, current_path=path,
                         parent_path=parent, disk_info=disk_info, file_count=file_count,
                         health=health,
                         nodes=datanode_manager.get_all(),
                         tier_stats=storage.get_tier_stats(),
                         partitions=partition_manager.get_all(),
                         total_files=total_files, total_dirs=total_dirs,
                         total_blocks=total_blocks, total_size=total_size,
                         format_file_size=format_file_size,
                         health_color=health_color, health_label=health_label,
                         disk_bg=disk_bg,
                         active_page='hdfs')

