// static/js/code_editor.js
document.addEventListener('DOMContentLoaded', function() {
    const contentArea = document.getElementById('content');
    // We need to get originalFilename from the HTML somehow.
    // We'll use a data attribute on the contentArea (textarea) for this.
    const originalFilename = contentArea ? contentArea.dataset.originalFilename : null;

    if (contentArea && originalFilename) { // Ensure both contentArea and originalFilename exist
        console.log("Textarea initial value:", contentArea.value.substring(0, 200));
        console.log("Original filename from data attribute:", originalFilename);

        function getModeForFilename(filename) {
            const extension = filename.slice(filename.lastIndexOf(".") + 1).toLowerCase();
            switch (extension) {
                case 'py': return 'python';
                case 'js': return 'javascript';
                case 'json': return {name: 'javascript', json: true};
                case 'css': return 'css';
                case 'html': case 'htm': return 'htmlmixed';
                case 'xml': return 'xml';
                case 'md': return 'markdown';
                case 'sh': case 'bash': return 'shell';
                case 'sql': return 'sql';
                case 'yaml': case 'yml': return 'yaml';
                case 'java': return 'text/x-java';
                case 'c': return 'text/x-csrc';
                case 'cpp': return 'text/x-c++src';
                case 'h': return 'text/x-c++src';
                case 'hpp': return 'text/x-c++src';
                case 'cs': return 'text/x-csharp';
            }
            if (CodeMirror.findModeByExtension) {
                const modeInfo = CodeMirror.findModeByExtension(extension);
                if (modeInfo && modeInfo.mode) {
                    if (typeof modeInfo.mode === 'string') {
                        if (CodeMirror.modes.hasOwnProperty(modeInfo.mode)) {
                            return modeInfo.mode;
                        }
                    } else if (typeof modeInfo.mode === 'object') {
                        if (CodeMirror.modes.hasOwnProperty(modeInfo.mode.name)) {
                            return modeInfo.mode;
                        }
                    }
                }
            }
            return 'text/plain';
        }

        const editorMode = getModeForFilename(originalFilename);
        console.log("Selected CodeMirror mode:", editorMode);

        const editor = CodeMirror.fromTextArea(contentArea, {
            lineNumbers: true,
            mode: editorMode,
            theme: 'colorforth', /* Needs to be changed in edit.html too */
            indentUnit: 4,
            smartIndent: true,
            tabSize: 4,
            indentWithTabs: false,
            electricChars: true,
            autoCloseBrackets: true,
            matchBrackets: true,
            lineWrapping: true,
        });

        editor.setSize(null, '60vh');

        const form = document.getElementById('edit-form');
        if (form) {
            form.addEventListener('submit', function() {
                editor.save();
            });
        }
    } else {
        if (!contentArea) {
            console.error("CodeMirror Init: Textarea with ID 'content' not found.");
        }
        if (!originalFilename && contentArea) { // Only log missing filename if textarea was found
            console.error("CodeMirror Init: data-original-filename attribute not found on textarea.");
        }
    }
});
