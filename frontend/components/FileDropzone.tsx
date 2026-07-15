interface FileDropzoneProps {
    file: File | null;
    onFileSelected: (file: File) => void;
    isInspecting: boolean;
}

export default function FileDropzone({
    file,
    onFileSelected,
    isInspecting,
}: FileDropzoneProps) {
    return (
        <label
            className={`border-2 border-dashed border-gray-300 rounded-lg p-10 text-center block cursor-pointer hover:border-blue-500 transition-colors bg-gray-50 ${isInspecting ? "opacity-70 cursor-wait" : ""
                }`}
        >
            <p className="text-gray-500 font-medium">
                {isInspecting
                    ? `Reading columns from ${file?.name}…`
                    : file
                        ? `Selected: ${file.name}`
                        : "Click to select your CSV/Excel file here"}
            </p>
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
