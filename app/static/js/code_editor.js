// static/js/code_editor.js
document.addEventListener('DOMContentLoaded', function() {
    const contentArea = document.getElementById('content');
    const originalFilename = contentArea ? contentArea.dataset.originalFilename : null;
    // Read the theme from the data attribute, defaulting to 'material' if not set
    const userTheme = contentArea ? (contentArea.dataset.codemirrorTheme || 'material') : 'material';

    if (contentArea && originalFilename) { // Ensure both contentArea and originalFilename exist
        console.log("Textarea initial value:", contentArea.value.substring(0, 200));
        console.log("Original filename from data attribute:", originalFilename);
        console.log("Using CodeMirror theme:", userTheme.replace('.css', ''));

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
                case 'h': return 'text/x-c++src'; // Often C/C++ header
                case 'hpp': return 'text/x-c++src';
                case 'cs': return 'text/x-csharp';
                // Add more cases as needed
            }
            // Fallback to CodeMirror's mode finder
            if (CodeMirror.findModeByExtension) {
                const modeInfo = CodeMirror.findModeByExtension(extension);
                if (modeInfo && modeInfo.mode) {
                    if (typeof modeInfo.mode === 'string') {
                        if (CodeMirror.modes.hasOwnProperty(modeInfo.mode)) {
                            return modeInfo.mode;
                        }
                    } else if (typeof modeInfo.mode === 'object') { // e.g., {name: "javascript", json: true}
                        if (CodeMirror.modes.hasOwnProperty(modeInfo.mode.name)) {
                            return modeInfo.mode;
                        }
                    }
                }
            }
            return 'text/plain'; // Default mode
        }

        const editorMode = getModeForFilename(originalFilename);
        console.log("Selected CodeMirror mode:", editorMode);

        const editor = CodeMirror.fromTextArea(contentArea, {
            lineNumbers: true,
            mode: editorMode,
            theme: userTheme.replace('.css', ''), // Use the theme, removing .css if present
                                               indentUnit: 4,
                                               smartIndent: true,
                                               tabSize: 4,
                                               indentWithTabs: false,
                                               electricChars: true,
                                               autoCloseBrackets: true,
                                               matchBrackets: true,
                                               lineWrapping: true,
        });

        editor.setSize(null, '60vh'); // Adjust height as needed

        // Save content back to textarea before form submission
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
