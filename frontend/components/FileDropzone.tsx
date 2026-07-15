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
    // The upload transfer and the (usually near-instant) server-side column
    // read both happen while isInspecting is true -- split the label so a
    // multi-GB file shows real transfer progress instead of looking stuck.
    const isStillUploading = isInspecting && uploadProgress < 100;

    return (
        <label
            className={`border-2 border-dashed border-gray-300 rounded-lg p-10 text-center block cursor-pointer hover:border-blue-500 transition-colors bg-gray-50 ${
                isInspecting ? "opacity-70 cursor-wait" : ""
            }`}
        >
            <p className="text-gray-500 font-medium">
                {isStillUploading
                    ? `Uploading ${file?.name}… ${uploadProgress}%`
                    : isInspecting
                      ? `Reading columns from ${file?.name}…`
                      : file
                        ? `Selected: ${file.name}`
                        : "Click to select your CSV/Excel file here"}
            </p>

            {isInspecting && (
                <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden mt-3">
                    <div
                        className="bg-blue-600 h-2 transition-all duration-200 ease-out"
                        style={{
                            width: `${isStillUploading ? uploadProgress : 100}%`,
                        }}
                    ></div>
                </div>
            )}

            <input
                type="file"
                accept=".csv,.xls,.xlsx"
                className="hidden"
                disabled={isInspecting}
                onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                        onFileSelected(e.target.files[0]);
                    }
                }}
            />
        </label>
    );
}
