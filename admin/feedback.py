from flask import render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.feedback_model import Feedback
from models.knowledge_model import KnowledgeBase
from utils.notifications import NotificationManager, create_user_notification
import os
import uuid


@admin_bp.route('/feedback')
@login_required
@admin_required
def feedback():
    status = request.args.get('status', None)
    category = request.args.get('category', None)
    priority = request.args.get('priority', None)
    search = request.args.get('search', None)
    all_feedback = Feedback.get_all(status=status, category=category, priority=priority, search=search)
    stats = Feedback.get_stats()
    return render_template('admin/feedback.html', feedback_list=all_feedback,
                         active_page='feedback', status_filter=status,
                         category_filter=category, priority_filter=priority,
                         search_query=search, stats=stats)


@admin_bp.route('/feedback/<int:feedback_id>')
@login_required
@admin_required
def view_feedback(feedback_id):
    fb = Feedback.get_by_id(feedback_id)
    if not fb:
        flash('Feedback not found.', 'danger')
        return redirect(url_for('admin.feedback'))
    return render_template('admin/feedback.html', feedback_item=fb,
                         feedback_list=Feedback.get_all(), active_page='feedback',
                         stats=Feedback.get_stats())


@admin_bp.route('/feedback/<int:feedback_id>/respond', methods=['POST'])
@login_required
@admin_required
def respond_feedback(feedback_id):
    response = request.form.get('response', '').strip()
    if not response:
        flash('Response is required.', 'danger')
        return redirect(url_for('admin.feedback'))

    Feedback.respond(feedback_id, response, current_user.id)

    fb = Feedback.get_by_id(feedback_id)

    # In-app notification for the user who submitted the feedback
    if fb and fb.get('user_id'):
        try:
            create_user_notification(
                fb['user_id'],
                title='Admin responded to your feedback',
                message=f"Your feedback \"{fb.get('subject', '')}\" received a response.",
                link=url_for('analyst.view_feedback', feedback_id=feedback_id),
                reference=f'feedback_{feedback_id}',
            )
        except Exception as e:
            print(f"Failed to create feedback notification: {e}")

    # Email the user who submitted feedback
    try:
        if fb and (fb.get('user_id') or fb.get('email')):
            NotificationManager.send_email(
                to_email=fb.get('email', ''),
                subject=f'Your feedback has been responded to: {fb.get("subject", "")}',
                body=f'Hello {fb.get("full_name", "User")},\n\n'
                     f'Your feedback "{fb.get("subject", "")}" has been responded to.\n\n'
                     f'Response:\n{response}\n\n'
                     f'Thank you for your feedback!'
            )
    except Exception as e:
        print(f"Failed to send response notification: {e}")

    flash('Response sent.', 'success')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback_id))


@admin_bp.route('/feedback/<int:feedback_id>/status', methods=['POST'])
@login_required
@admin_required
def update_feedback_status(feedback_id):
    status = request.form.get('status', 'open')
    assigned_to = request.form.get('assigned_to', None)
    Feedback.update_status(feedback_id, status, assigned_to=int(assigned_to) if assigned_to else None)
    flash('Status updated.', 'success')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback_id))


@admin_bp.route('/feedback/<int:feedback_id>/assign', methods=['POST'])
@login_required
@admin_required
def assign_feedback(feedback_id):
    assigned_to = request.form.get('assigned_to', '')
    if not assigned_to:
        flash('Please select an admin to assign.', 'danger')
        return redirect(url_for('admin.view_feedback', feedback_id=feedback_id))
    Feedback.assign(feedback_id, int(assigned_to))
    flash('Feedback assigned successfully.', 'success')
    return redirect(url_for('admin.view_feedback', feedback_id=feedback_id))


@admin_bp.route('/feedback/<int:feedback_id>/attachment')
@login_required
@admin_required
def download_feedback_attachment(feedback_id):
    """Download a feedback attachment as a real file download."""
    fb = Feedback.get_by_id(feedback_id)
    path = fb.get('attachment_path') if fb else ''
    if not path or not os.path.exists(path):
        flash('Attachment file not found on server.', 'danger')
        return redirect(url_for('admin.view_feedback', feedback_id=feedback_id))
    return send_file(os.path.abspath(path), as_attachment=True)


@admin_bp.route('/feedback/<int:feedback_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_feedback(feedback_id):
    Feedback.delete(feedback_id)
    flash('Feedback deleted.', 'success')
    return redirect(url_for('admin.feedback'))


@admin_bp.route('/feedback/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_feedback_action():
    action = request.form.get('action', '')
    feedback_ids = request.form.getlist('feedback_ids')
    if not feedback_ids:
        flash('No feedback items selected.', 'warning')
        return redirect(url_for('admin.feedback'))

    if action == 'resolve':
        for fid in feedback_ids:
            Feedback.update_status(int(fid), 'resolved')
        flash(f'{len(feedback_ids)} feedback(s) resolved.', 'success')
    elif action == 'close':
        for fid in feedback_ids:
            Feedback.update_status(int(fid), 'closed')
        flash(f'{len(feedback_ids)} feedback(s) closed.', 'success')
    elif action == 'delete':
        for fid in feedback_ids:
            Feedback.delete(int(fid))
        flash(f'{len(feedback_ids)} feedback(s) deleted.', 'success')
    else:
        flash('Invalid action.', 'danger')

    return redirect(url_for('admin.feedback'))


# ========== Knowledge Base / FAQ ==========

@admin_bp.route('/knowledge')
@login_required
@admin_required
def knowledge_base():
    category = request.args.get('category', None)
    search = request.args.get('search', None)
    articles = KnowledgeBase.get_all(category=category, search=search)
    categories = KnowledgeBase.get_categories()
    return render_template('admin/knowledge_base.html',
                         articles=articles, categories=categories,
                         active_page='knowledge',
                         category_filter=category, search_query=search)


@admin_bp.route('/knowledge/create', methods=['POST'])
@login_required
@admin_required
def create_knowledge_article():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', 'general')
    tags = request.form.get('tags', '').strip()

    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(url_for('admin.knowledge_base'))

    KnowledgeBase.create(title, content, category, tags, current_user.id)
    flash('Article created successfully.', 'success')
    return redirect(url_for('admin.knowledge_base'))


@admin_bp.route('/knowledge/<int:article_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_knowledge_article(article_id):
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', 'general')
    tags = request.form.get('tags', '').strip()
    is_published = 1 if request.form.get('is_published') else 0

    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(url_for('admin.knowledge_base'))

    KnowledgeBase.update(article_id, title=title, content=content,
                        category=category, tags=tags, is_published=is_published)
    flash('Article updated.', 'success')
    return redirect(url_for('admin.knowledge_base'))


@admin_bp.route('/knowledge/<int:article_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_knowledge_article(article_id):
    KnowledgeBase.delete(article_id)
    flash('Article deleted.', 'success')
    return redirect(url_for('admin.knowledge_base'))
