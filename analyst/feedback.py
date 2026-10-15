from flask import render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.feedback_model import Feedback
from models.knowledge_model import KnowledgeBase
from utils.notifications import (NotificationManager, mark_user_notifications_read,
                                  create_user_notification, get_support_recipients)
from utils.database import get_collection
import os
import uuid


UPLOAD_FOLDER = os.path.join('static', 'uploads', 'feedback')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'csv', 'log'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_attachment(file):
    """Save uploaded file and return the relative path."""
    if not file or file.filename == '':
        return None
    if not _allowed_file(file.filename):
        return None
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return filepath


@analyst_bp.route('/feedback', methods=['GET', 'POST'])
@login_required
@analyst_required
def feedback():
    """Handle feedback submission and display user's feedback history."""
    if request.method == 'POST':
        action = request.form.get('action', 'submit_feedback')

        if action == 'submit_feedback':
            subject = request.form.get('subject', '').strip()
            message = request.form.get('message', '').strip()
            category = request.form.get('category', 'general')
            priority = request.form.get('priority', 'medium')

            if not subject or not message:
                flash('Subject and message are required.', 'danger')
                return redirect(url_for('analyst.feedback'))

            # Handle file attachment
            attachment_path = None
            if 'attachment' in request.files:
                file = request.files['attachment']
                attachment_path = _save_attachment(file)

            try:
                feedback_id = Feedback.create(subject, message, category, priority, current_user.id, attachment_path=attachment_path)
                _notify_admins('New analyst feedback', f'New feedback: {subject}', feedback_id)
                # Notify admins about new feedback
                for recipient in get_support_recipients():
                    try:
                        NotificationManager.send_email(
                            to_email=recipient,
                            subject=f'New Feedback: {subject}',
                            body=f'From: {current_user.full_name}\nCategory: {category}\nPriority: {priority}\n\n{message}'
                        )
                    except Exception:
                        pass
                flash('Feedback submitted successfully. Thank you!', 'success')
            except Exception as e:
                flash(f'Failed to submit feedback: {str(e)}', 'danger')

        elif action == 'delete_feedback':
            feedback_id = request.form.get('feedback_id', type=int)
            if feedback_id:
                try:
                    if not Feedback.get_by_user(current_user.id) or not any(fb.get('id') == feedback_id for fb in Feedback.get_by_user(current_user.id)):
                        raise ValueError('Feedback not found.')
                    Feedback.delete(feedback_id)
                    flash('Feedback deleted.', 'success')
                except Exception as e:
                    flash(f'Failed to delete feedback: {str(e)}', 'danger')

        return redirect(url_for('analyst.feedback'))

    # GET: Load user's feedback history with stats
    my_feedback = Feedback.get_by_user(current_user.id)

    # Opening the feedback page counts as reading any admin-response notifications
    try:
        mark_user_notifications_read(current_user.id)
    except Exception:
        pass

    # Calculate feedback stats
    total_feedback = len(my_feedback)
    resolved_count = sum(1 for fb in my_feedback if fb.get('status') == 'resolved')
    pending_count = sum(1 for fb in my_feedback if fb.get('status') in ('open', 'in_progress'))

    # Category breakdown
    categories = {}
    for fb in my_feedback:
        cat = fb.get('category', 'general')
        categories[cat] = categories.get(cat, 0) + 1

    return render_template('analyst/feedback.html',
                         feedback_list=my_feedback,
                         active_page='feedback',
                         total_feedback=total_feedback,
                         resolved_count=resolved_count,
                         pending_count=pending_count,
                         categories=categories)


@analyst_bp.route('/feedback/view/<int:feedback_id>')
@login_required
@analyst_required
def view_feedback(feedback_id):
    """View a single feedback detail."""
    my_feedback = Feedback.get_by_user(current_user.id)
    feedback_item = None
    for fb in my_feedback:
        if fb.get('id') == feedback_id:
            feedback_item = fb
            break

    if not feedback_item:
        flash('Feedback not found.', 'danger')
        return redirect(url_for('analyst.feedback'))

    # Reading the detail clears this feedback's response notification
    try:
        mark_user_notifications_read(current_user.id, reference=f'feedback_{feedback_id}')
    except Exception:
        pass

    return render_template('analyst/feedback_detail.html',
                         feedback=feedback_item,
                         active_page='feedback')


@analyst_bp.route('/feedback/view/<int:feedback_id>/reply', methods=['POST'])
@login_required
@analyst_required
def reply_feedback(feedback_id):
    """Reply to an Admin response from the Analyst feedback detail page."""
    feedback_item = next((fb for fb in Feedback.get_by_user(current_user.id)
                          if fb.get('id') == feedback_id), None)
    response = request.form.get('response', '').strip()
    if not feedback_item:
        flash('Feedback not found.', 'danger')
    elif not response:
        flash('Reply message is required.', 'danger')
    elif feedback_item.get('status') == 'closed':
        flash('Closed feedback cannot receive new replies.', 'warning')
    else:
        Feedback.analyst_reply(feedback_id, response, current_user.id)
        _notify_admins('Analyst replied to feedback',
                       f'New reply on feedback "{feedback_item.get("subject", "")}"', feedback_id)
        flash('Reply sent to Admin.', 'success')
    return redirect(url_for('analyst.view_feedback', feedback_id=feedback_id))


def _notify_admins(title, message, feedback_id):
    """Create private notifications for every active Admin account."""
    try:
        admins = get_collection('users').find({'role': 'admin'})
        for admin in admins:
            create_user_notification(
                admin['id'], title, message,
                link=url_for('admin.view_feedback', feedback_id=feedback_id),
                reference=f'feedback_{feedback_id}',
            )
    except Exception:
        pass


@analyst_bp.route('/feedback/view/<int:feedback_id>/attachment')
@login_required
@analyst_required
def download_feedback_attachment(feedback_id):
    """Download the attachment of one of this user's feedback items."""
    feedback_item = None
    for fb in Feedback.get_by_user(current_user.id):
        if fb.get('id') == feedback_id:
            feedback_item = fb
            break
    path = feedback_item.get('attachment_path') if feedback_item else ''
    if not path or not os.path.exists(path):
        flash('Attachment file not found on server.', 'danger')
        return redirect(url_for('analyst.view_feedback', feedback_id=feedback_id))
    return send_file(os.path.abspath(path), as_attachment=True)


# ========== Knowledge Base / Help Center ==========

@analyst_bp.route('/help')
@login_required
@analyst_required
def knowledge_base():
    """View knowledge base articles (FAQ / help center)."""
    category = request.args.get('category', None)
    search = request.args.get('search', None)
    articles = KnowledgeBase.get_all(category=category, search=search, published_only=True)
    categories = KnowledgeBase.get_categories()
    return render_template('analyst/knowledge_base.html',
                         articles=articles, categories=categories,
                         active_page='help',
                         category_filter=category, search_query=search)


@analyst_bp.route('/help/<int:article_id>')
@login_required
@analyst_required
def view_knowledge_article(article_id):
    """View a single knowledge base article."""
    article = KnowledgeBase.get_by_id(article_id)
    if not article or not article.get('is_published'):
        flash('Article not found.', 'danger')
        return redirect(url_for('analyst.knowledge_base'))
    return render_template('analyst/knowledge_article.html',
                         article=article, active_page='help')


@analyst_bp.route('/help/<int:article_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_knowledge_article(article_id):
    """Delete a knowledge base article."""
    article = KnowledgeBase.get_by_id(article_id)
    if not article:
        flash('Article not found.', 'danger')
        return redirect(url_for('analyst.knowledge_base'))
    KnowledgeBase.delete(article_id)
    flash(f'Article "{article.get("title", "")}" deleted.', 'success')
    return redirect(url_for('analyst.knowledge_base'))
