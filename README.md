# PyCloud
Nextcloud alternative made with python, js, html, css. Easy to run, fast and currently in development.
# Coming Soon
### Integrated Git Server, Fix for wrong time issue
# Key features
### File Storage
### Notes
### AI Chat (Ollama)
### General Group Chat
### Admin Settings
### Password reset using smtp
### User profiles ( Bio, profile picture & more ) *NEW*
### Social Media Posting *NEW*
### Changeable email ( For user ) *NEW*
### Notifications for friend invite, messages, new posts
### Disable(Banning) / Delete users
### Batch selection for files
### Friends & Friend Chat
### Code color syntax in file editor thanks to [MirrorCode](https://codemirror.net/)
### GBA Emulator thanks to [mGBA](https://github.com/mgba-emu/mgba), [emscripten](https://github.com/emscripten-core/emscripten), [GBA-wasm](https://github.com/kxkx5150/GBA-wasm)
> I do not provide the GBA Bios, find it somewhere else and put it in 
>> ./PyCloud/static/bios/gba_bios.bin 
>>> or if installed /home/username/.local/share/PyCloud/static/bios/gba_bios.bin
# Upcoming features
### Email verification


### Rate limiting password reset
### Separated Upload Limit for group chat
### Wipe entire Group Chat in admin settings


### Drag files around
### & More

# Known bugs that will be corrected in near future
### Files checkbox doesn't work properly FIXED
### Audio Player not working with chromium based browsers FIXED
### Unarchiving un archive with subfolders will cause files to not go into appropriate folders
 export FLASK_APP=main.py
 1019  flask --app main.py db init
 1020  flask db migrate -m "Create git_repository table and other initial tables"
 1021  flask db upgrade
