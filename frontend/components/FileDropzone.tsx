interface FileDropzoneProps {
    file: File | null;
    setFile: (file: File) => void;
}

export default function FileDropzone({ file, setFile }: FileDropzoneProps) {
    return (
        <label className="border-2 border-dashed border-gray-300 rounded-lg p-10 text-center block cursor-pointer hover:border-blue-500 transition-colors bg-gray-50">
            <p className="text-gray-500 font-medium">
                {file
                    ? `Selected: ${file.name}`
                    : "Click to select your CSV/Excel file here"}
            </p>
            <input
                type="file"
                accept=".csv,.xls,.xlsx"
                className="hidden"
                onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                        setFile(e.target.files[0]);
                    }
                }}
            />
        </label>
    );
}
