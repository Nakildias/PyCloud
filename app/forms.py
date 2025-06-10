# app/forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, BooleanField, EmailField,
    TextAreaField, IntegerField, SelectField, URLField
)
from wtforms.validators import (
    DataRequired, Length, Email, EqualTo, ValidationError, Optional,
    NumberRange, URL, InputRequired
)
from flask_wtf.file import FileField, FileAllowed, FileRequired

from .models import User


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose another.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already registered. Please use another.')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')


class UploadFileForm(FlaskForm):
    file = FileField('File', validators=[FileRequired(message='No file selected!')])
    submit = SubmitField('Upload')


class CreateFolderForm(FlaskForm):
    name = StringField('Folder Name', validators=[
        DataRequired(message="Folder name cannot be empty."),
        Length(min=1, max=100, message="Folder name must be between 1 and 100 characters.")
    ])
    submit = SubmitField('Create Folder')


class EditFileForm(FlaskForm):
    content = TextAreaField('File Content', validators=[DataRequired()])
    submit = SubmitField('Save Changes')


class NoteForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=150)])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Save Note')


class ForgotPasswordForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')


class EditProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)], render_kw={'readonly': True})
    email = EmailField('Email', validators=[DataRequired(), Email()])
    bio = TextAreaField('Bio', validators=[Optional(), Length(max=2500)])
    profile_picture = FileField('Profile Picture', validators=[
        Optional(),
        FileAllowed(['jpg', 'png', 'jpeg', 'gif'], 'Images only!')
    ])
    github_url = URLField('GitHub URL', validators=[Optional(), URL()])
    spotify_url = URLField('Spotify URL', validators=[Optional(), URL()])
    youtube_url = URLField('YouTube URL', validators=[Optional(), URL()])
    twitter_url = URLField('X (Twitter) URL', validators=[Optional(), URL()])
    steam_url = URLField('Steam URL', validators=[Optional(), URL()])
    twitch_url = URLField('Twitch URL', validators=[Optional(), URL()])
    discord_server_url = URLField('Discord Server URL', validators=[Optional(), URL()])
    reddit_url = URLField('Reddit URL', validators=[Optional(), URL()])
    submit = SubmitField('Update Profile')

    def __init__(self, original_username=None, original_email=None, *args, **kwargs):
        super(EditProfileForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already registered. Please use another.')


class EditUserForm(FlaskForm): # For Admin
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    is_admin = BooleanField('Administrator Status')
    storage_limit_mb = IntegerField(
        'Specific Storage Limit (MB)',
        validators=[Optional(), NumberRange(min=0, message='Storage limit must be 0 or greater.')],
        description=""
    )
    max_file_size = IntegerField(
        'Per User Max File Upload Size (MB)',
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"placeholder": ""}
    )
    password = PasswordField('New Password', validators=[Optional(), Length(min=6, message="Password must be at least 6 characters long if provided.")])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('password', message='New passwords must match.') if 'password' else Optional()]) # Conditional EqualTo
    submit = SubmitField('Update User')

    def __init__(self, original_username=None, original_email=None, *args, **kwargs):
        super(EditUserForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=username.data).first()
            if user:
                raise ValidationError('That username is already taken. Please choose another.')

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already registered. Please use another.')

    def validate_confirm_password(self, confirm_password):
        if self.password.data and not confirm_password.data:
            raise ValidationError('Please confirm the new password.')


class AdminSettingsForm(FlaskForm):
    allow_registration = BooleanField('Allow New User Registrations')
    default_storage_limit_mb = IntegerField(
        'Default Storage Limit per User (MB)',
        validators=[DataRequired(), NumberRange(min=0, message='Storage limit cannot be negative. Enter 0 for unlimited.')]
    )
    max_upload_size_mb = IntegerField(
        'Max Single File Upload Size (MB)',
        validators=[DataRequired(message="Please specify a maximum upload size."), NumberRange(min=1, message='Maximum upload size must be at least 1 MB.')],
        description=""
    )
    ollama_api_url = URLField(
        'Ollama API Base URL',
        validators=[Optional(), URL(message='Please enter a valid URL.')],
        description="URL for your Ollama instance (e.g., http://localhost:11434). Leave blank to disable."
    )
    ollama_model = StringField(
        'Ollama Model Name',
        validators=[Optional(), Length(min=1, max=100)],
        description="The name of the Ollama model to use (e.g., 'llama3'). Required if URL is set."
    )
    mail_server = StringField('SMTP Server Host', validators=[Optional(), Length(max=100)])
    mail_port = IntegerField('SMTP Port', validators=[Optional(), NumberRange(min=1, max=65535)])
    mail_use_tls = BooleanField('Use TLS')
    mail_use_ssl = BooleanField('Use SSL')
    mail_username = StringField('SMTP Username/Email', validators=[Optional(), Length(max=100)])
    mail_password = PasswordField('SMTP Password', validators=[Optional(), Length(min=1, max=100)])
    mail_default_sender_name = StringField('Default Sender Name', validators=[Optional(), Length(max=100)], description='The "From" name displayed in emails.')
    mail_default_sender_email = EmailField('Default Sender Email', validators=[Optional(), Email(), Length(max=120)], description='The "From" email address.')
    submit = SubmitField('Save Settings')


class CreatePostForm(FlaskForm):
    text_content = TextAreaField('What\'s on your mind?', validators=[Length(max=5000)])
    photo = FileField('Upload Photo', validators=[
        Optional(),
        FileAllowed(['jpg', 'png', 'jpeg', 'gif', 'webp'], 'Images only!')
    ])
    video = FileField('Upload Video', validators=[
        Optional(),
        FileAllowed(['mp4', 'webm', 'ogg', 'mov'], 'Videos only!')
    ])
    submit = SubmitField('Post')


class CommentForm(FlaskForm):
    text_content = TextAreaField('Write a comment...', validators=[DataRequired(), Length(min=1, max=1000)])
    submit = SubmitField('Comment')


class OllamaChatForm(FlaskForm):
    message = TextAreaField('You: ', validators=[DataRequired(), Length(max=4000)])
    submit = SubmitField('Send')


class GroupChatForm(FlaskForm):
    content = TextAreaField('Message', validators=[Length(max=4000)])
    file = FileField('Attach File', validators=[Optional()])
    submit = SubmitField('Send')

class DirectMessageForm(FlaskForm):
    content = TextAreaField('Message', validators=[Length(max=4000)])
    file = FileField('Attach File', validators=[Optional()])
    # No submit field needed if handled by JS + Enter key for DMs

class YtdlpForm(FlaskForm):
    youtube_url = URLField('YouTube Video URL', validators=[DataRequired(), URL(message="Please enter a valid URL.")])
    download_format = SelectField('Format', choices=[
        ('mp4', 'MP4 Video'),
        ('mp3', 'MP3 Audio')
    ], default='mp4', validators=[DataRequired()])
    video_quality = SelectField('Video Quality (for MP4)', choices=[
        ('best', 'Best Available'),
        ('1080', '1080p'),
        ('720', '720p'),
        ('480', '480p'),
        ('360', '360p')
    ], default='best', validators=[Optional()])
    submit = SubmitField('Download')

class ImageUpscalerForm(FlaskForm):
    image_file = FileField(  # Ensure this line is present and correct
        'Upload Image',
        validators=[
            DataRequired(message="Please select an image to upscale."),
            FileAllowed(['jpg', 'jpeg', 'png', 'bmp', 'webp'], 'Only image files (jpg, png, bmp, webp) are allowed!')
        ]
    )
    scale_factor = SelectField(
        'Upscale Factor',
        choices=[('2', '2x'), ('3', '3x'), ('4', '4x')],
        default='2',
        validators=[DataRequired()]
    )
    submit = SubmitField('Upscale Image')


class RepoEditFileForm(FlaskForm): # For Git file editing
    file_content = TextAreaField('File Content', validators=[DataRequired()])
    commit_message = StringField('Commit Message', validators=[DataRequired(), Length(min=1, max=200)])
    submit = SubmitField('Save Changes')

class AddServerForm(FlaskForm):
    name = StringField('Server Name', validators=[DataRequired(), Length(min=1, max=20)])
    host = StringField('Server Host/IP', validators=[DataRequired(), Length(min=1, max=255)])
    port = IntegerField('Port', default=65432, validators=[DataRequired(), NumberRange(min=1, max=65535)])
    password = PasswordField('Daemon Password', validators=[Optional(), Length(min=1, max=255)])
    submit = SubmitField('Add Server')
