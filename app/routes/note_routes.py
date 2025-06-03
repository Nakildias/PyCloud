# app/routes/note_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user

# Import necessary components from the app package
from app import db # db is initialized in app/__init__.py
from app.models import Note # Note model
from app.forms import NoteForm # NoteForm

# Define the blueprint
bp = Blueprint('note_routes', __name__, url_prefix='/notes')


@bp.route('/')
@login_required
def list_notes():
    """Displays a list of the current user's notes."""
    user_notes = Note.query.filter_by(author=current_user).order_by(Note.timestamp.desc()).all()
    return render_template('notes/notes.html', title='My Notes', notes=user_notes) # Assuming templates in notes/


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_note():
    """Handles creation of a new note."""
    form = NoteForm()
    if form.validate_on_submit():
        try:
            note = Note(title=form.title.data,
                        content=form.content.data,
                        author=current_user)
            db.session.add(note)
            db.session.commit()
            flash('Note created successfully!', 'success')
            current_app.logger.info(f"Note '{note.title}' (ID: {note.id}) created by user {current_user.id}")
            return redirect(url_for('note_routes.list_notes'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating note for user {current_user.id}: {e}", exc_info=True)
            flash('Failed to create note.', 'danger')
    return render_template('notes/note_form.html', title='New Note', form=form, legend='Create New Note')


@bp.route('/<int:note_id>')
@login_required
def view_note(note_id):
    """Displays a single note."""
    note = Note.query.get_or_404(note_id)
    if note.author != current_user:
        current_app.logger.warning(f"User {current_user.id} attempted to access note {note_id} owned by user {note.user_id}")
        abort(403)
    return render_template('notes/view_note.html', title=note.title, note=note)


@bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    """Handles editing an existing note."""
    note = Note.query.get_or_404(note_id)
    if note.author != current_user:
        current_app.logger.warning(f"User {current_user.id} attempted to edit note {note_id} owned by user {note.user_id}")
        abort(403)

    form = NoteForm()
    if form.validate_on_submit():
        try:
            note.title = form.title.data
            note.content = form.content.data
            # note.timestamp = datetime.utcnow() # Optionally update timestamp on edit
            db.session.commit()
            flash('Note updated successfully!', 'success')
            current_app.logger.info(f"Note {note_id} updated by user {current_user.id}")
            return redirect(url_for('note_routes.view_note', note_id=note.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing note {note_id} for user {current_user.id}: {e}", exc_info=True)
            flash('Failed to update note.', 'danger')
    elif request.method == 'GET':
        form.title.data = note.title
        form.content.data = note.content
    return render_template('notes/note_form.html', title='Edit Note', form=form, legend=f'Edit Note: "{note.title}"', note_id=note_id)


@bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    """Deletes a note."""
    note = Note.query.get_or_404(note_id)
    if note.author != current_user:
        current_app.logger.warning(f"User {current_user.id} attempted to delete note {note_id} owned by user {note.user_id}")
        abort(403)
    try:
        note_title = note.title
        db.session.delete(note)
        db.session.commit()
        flash(f'Note "{note_title}" deleted successfully!', 'success')
        current_app.logger.info(f"Note '{note_title}' (ID: {note_id}) deleted by user {current_user.id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting note {note_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Failed to delete note.', 'danger')
    return redirect(url_for('note_routes.list_notes'))
