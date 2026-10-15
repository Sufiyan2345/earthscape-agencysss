from flask import render_template, redirect, url_for, flash, make_response
from flask import session, current_app
from flask_login import logout_user, current_user, login_required
from auth import auth_bp
from utils.database import log_activity


@auth_bp.route('/logout')
@login_required
def logout():
    try:
        log_activity(current_user.id, 'logout', f'User {current_user.username} logged out')
    except Exception:
        pass

    # Clear the session BEFORE logout_user(). logout_user() flags the
    # "remember me" cookie for removal by setting session['_remember'] =
    # 'clear' (the cookie itself is only deleted from the response later).
    # Clearing the session afterwards would erase that flag, leaving the
    # cookie alive and silently re-logging the user in on the next request.
    session.clear()
    logout_user()

    resp = make_response(render_template('auth/logout.html'))

    # Belt and braces: explicitly expire the remember-me cookie as well.
    remember_cookie = current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    resp.delete_cookie(remember_cookie,
                       domain=current_app.config.get('REMEMBER_COOKIE_DOMAIN'),
                       path=current_app.config.get('REMEMBER_COOKIE_PATH', '/'))

    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp
