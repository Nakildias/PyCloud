# app/routes/auth_routes.py
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy.exc import IntegrityError
from flask_mail import Message # For sending emails

# Import necessary components from the app package
from app import db, mail  # db and mail are initialized in app/__init__.py
from app.utils import get_user_upload_path # Import directly from app.utils
from app.models import User, Setting # Models
from app.forms import RegistrationForm, LoginForm, ForgotPasswordForm, ResetPasswordForm # Forms
from app.config import DEFAULT_SETTINGS # For fallback settings

# Define the blueprint
bp = Blueprint('auth', __name__, url_prefix='/auth') # Using '/auth' as a prefix


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main_routes.index')) # Assuming a main_routes blueprint for index

    registration_allowed = Setting.get('allow_registration', DEFAULT_SETTINGS['allow_registration']) == 'true'
    if not registration_allowed:
        flash('New user registration is currently disabled.', 'info')
        return redirect(url_for('auth.login'))

    form = RegistrationForm()
    if form.validate_on_submit():
        is_first_user = User.query.count() == 0
        try:
            default_limit_str = Setting.get('default_storage_limit_mb', DEFAULT_SETTINGS['default_storage_limit_mb'])
            default_limit_mb = int(default_limit_str)
            if default_limit_mb < 0: default_limit_mb = 0 # Treat negative as 0 (unlimited in some contexts)
        except (ValueError, TypeError):
            default_limit_mb = int(DEFAULT_SETTINGS['default_storage_limit_mb']) # Fallback
            current_app.logger.error(f"Invalid default_storage_limit_mb. Falling back to {default_limit_mb} MB.")

        new_user = User(
            username=form.username.data,
            email=form.email.data,
            is_admin=is_first_user,
            storage_limit_mb=default_limit_mb if default_limit_mb > 0 else None
        )
        new_user.set_password(form.password.data)

        try:
            db.session.add(new_user)
            db.session.commit()

            # Create user's upload directory
            try:
                user_upload_path = get_user_upload_path(new_user.id) # Using helper from app
                os.makedirs(user_upload_path, exist_ok=True)
                current_app.logger.info(f"Created upload directory for new user {new_user.id}: {user_upload_path}")
            except OSError as e:
                current_app.logger.error(f"Failed to create upload directory for user {new_user.id}: {e}", exc_info=True)

            flash(f'Account created for {form.username.data}! You can now log in.', 'success')
            if is_first_user:
                flash('You have been registered as the first user (Admin).', 'info')
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            current_app.logger.warning(f"Registration failed for {form.username.data} due to integrity error.")
            if User.query.filter_by(username=form.username.data).first():
                form.username.errors.append("This username was just taken. Please choose another.")
            elif User.query.filter_by(email=form.email.data).first():
                form.email.errors.append("This email was just registered. Please use another.")
            else:
                flash('An error occurred during registration. Please try again.', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error during registration for {form.username.data}: {e}", exc_info=True)
            flash('An unexpected error occurred during registration.', 'danger')

    return render_template('auth/register.html', title='Register', form=form) # Assuming templates in auth/ subdirectory


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main_routes.index')) # Or 'file_routes.list_files'

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            if user.is_disabled:
                flash('Your account has been disabled. Please contact an administrator.', 'danger')
                return redirect(url_for('auth.login'))
            if user.check_password(form.password.data):
                login_user(user, remember=form.remember.data)
                flash('Login successful!', 'success')
                next_page = request.args.get('next')
                # Be cautious with `next_page` to prevent open redirect vulnerabilities
                # A common practice is to ensure next_page is a relative path or from your domain.
                if next_page and not next_page.startswith(('/', request.host_url)):
                    next_page = None
                return redirect(next_page or url_for('main_routes.index')) # Or 'file_routes.list_files'
            else:
                flash('Login Unsuccessful. Please check username and password.', 'danger')
        else:
            flash('Login Unsuccessful. Please check username and password.', 'danger')
    return render_template('auth/login.html', title='Login', form=form)


@bp.route('/logout')
@login_required
def logout():
    if current_user.is_authenticated:
        current_user.is_online = False
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error setting user {current_user.id} offline during logout: {e}")

    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main_routes.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = user.get_reset_token()
            reset_url = url_for('auth.reset_token', token=token, _external=True)

            subject = "Password Reset Request"
            sender_name = Setting.get('MAIL_DEFAULT_SENDER_NAME', DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_NAME'])
            sender_email = Setting.get('MAIL_DEFAULT_SENDER_EMAIL', DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_EMAIL'])
            actual_sender = (str(sender_name), str(sender_email)) if sender_name and sender_email else sender_email or DEFAULT_SETTINGS['MAIL_DEFAULT_SENDER_EMAIL']


            text_body = f"""Hello {user.username},
To reset your password, please visit the following link:
{reset_url}
This link is valid for approximately 30 minutes.
If you did not request a password reset, please ignore this email.
Thank you,
The {sender_name} Team"""

            html_body = render_template(
                'auth/reset_email.html', # Assuming template in auth/
                subject=subject,
                username=user.username,
                reset_url=reset_url,
                app_name=sender_name,
            )
            msg = Message(subject, sender=actual_sender, recipients=[user.email], body=text_body, html=html_body)
            try:
                mail.send(msg)
                flash('An email has been sent with instructions to reset your password.', 'info')
            except Exception as e:
                current_app.logger.error(f"Failed to send password reset email to {user.email}: {e}", exc_info=True)
                flash('There was an error sending the password reset email. Please try again later.', 'danger')
        else:
            flash('If an account with that email exists, an email has been sent.', 'info') # To prevent email enumeration
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', title='Forgot Password', form=form)


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('main_routes.index'))

    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been updated! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', title='Reset Password', form=form, token=token)
