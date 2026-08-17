// 1. The Interface Contract
// ARCHITECTURE DECISION: Just like the ExtractionForm, this is a Presentational component.
// It receives the exact percentage (`uploadProgress`) from its parent, meaning the
// complex XHR/XMLHttpRequest logic is kept safely out of the UI rendering layer.
interface FileDropzoneProps {
    file: File | null;
    onFileSelected: (file: File) => void;
    isInspecting: boolean;
    // 0-100, percentage of the file actually transferred to the server so
    // far. Only meaningful while isInspecting is true.
    uploadProgress: number;
}

export default function FileDropzone({
    file,
    onFileSelected,
    isInspecting,
    uploadProgress,
}: FileDropzoneProps) {

    // UX / PRODUCT SENSE: This is a brilliant micro-interaction.
    // The "Upload" phase actually consists of two steps:
    // 1. The physical network transfer to Django (uploadProgress 0 -> 100).
    // 2. The Celery worker reading the file to extract columns.
    // By separating `isStillUploading` from `isInspecting`, we prevent the "99% frozen"
    // problem where users think the app crashed because the bar hit 100% but the UI didn't update.
    const isStillUploading = isInspecting && uploadProgress < 100;

    return (
        // SEMANTIC HTML & ACCESSIBILITY:
        // Native <input type="file"> elements are notoriously hard to style.
        // The standard engineering pattern used here is to hide the actual input,
        // and wrap it in a <label>. Clicking the styled label automatically triggers
        // the hidden input's file dialog.
        <label
            className={`border-2 border-dashed border-gray-300 rounded-lg p-10 text-center block cursor-pointer hover:border-blue-500 transition-colors bg-gray-50 ${
                // Visual feedback: If it's busy, fade it out and change the mouse cursor
                isInspecting ? "opacity-70 cursor-wait" : ""
            }`}
        >
            <p className="text-gray-500 font-medium">
                {/* DYNAMIC FEEDBACK TEXT: Guides the user through the exact micro-state */}
                {isStillUploading
                    ? `Uploading ${file?.name}… ${uploadProgress}%`
                    : isInspecting
                      ? `Reading columns from ${file?.name}…`
                      : file
                        ? `Selected: ${file.name}`
                        : "Click to select your CSV/Excel file here"}
            </p>

            {/* The XHR Network Progress Bar */}
            {isInspecting && (
                <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden mt-3">
                    <div
                        className="bg-blue-600 h-2 transition-all duration-200 ease-out"
                        style={{
                            // Lock it at 100% visually while Celery finishes the column read
                            width: `${isStillUploading ? uploadProgress : 100}%`,
                        }}
                    ></div>
                </div>
            )}

            <input
                type="file"
                // Strict frontend validation to match the Django backend ALLOWED_UPLOAD_EXTENSIONS
                accept=".csv,.xls,.xlsx"
                className="hidden"
                disabled={isInspecting}
                onChange={(e) => {
                    // Safety check: Ensure the user actually selected a file before triggering state
                    if (e.target.files && e.target.files.length > 0) {
                        onFileSelected(e.target.files[0]);
                    }
                }}
            />
        </label>
    );
}
