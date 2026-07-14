import React from "react";

// 1. The Interface Contract
interface ExtractionFormProps {
    targetColumn: string;
    setTargetColumn: (val: string) => void;
    prompt: string;
    setPrompt: (val: string) => void;
    replacement: string;
    setReplacement: (val: string) => void;

    // Tracking Props
    jobStatus: string;
    progress: number;
    resultData: any;
    errorMessage: string;

    // Actions
    onSubmit: () => void;
    onCancel: () => void;
}

export default function ExtractionForm({
    targetColumn,
    setTargetColumn,
    prompt,
    setPrompt,
    replacement,
    setReplacement,
    jobStatus,
    progress,
    resultData,
    errorMessage,
    onSubmit,
    onCancel,
}: ExtractionFormProps) {

    // Helper variable to determine if the UI should be locked down
    const isRunning =
        jobStatus === "QUEUED" ||
        jobStatus === "RUNNING" ||
        jobStatus === "SUBMITTING";

    return (
        <div className="space-y-6 mt-6">

            {/* --- User Input Section --- */}
            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Target Column
                </label>
                <input
                    type="text"
                    value={targetColumn}
                    onChange={(e) => setTargetColumn(e.target.value)}
                    disabled={isRunning}
                    placeholder="e.g., Email"
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 disabled:opacity-50"
                />
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Natural Language Regex Rule
                </label>
                <textarea
                    rows={3}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    disabled={isRunning}
                    placeholder="e.g., Find email addresses in the Email column and replace them with 'REDACTED'"
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 disabled:opacity-50"
                />
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Replacement Value
                </label>
                <input
                    type="text"
                    value={replacement}
                    onChange={(e) => setReplacement(e.target.value)}
                    disabled={isRunning}
                    placeholder="e.g., [REDACTED] or leave blank to delete"
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 disabled:opacity-50"
                />
            </div>

            {/* --- Dynamic Tracking UI Section --- */}
            <div className="mt-8 space-y-4">

                {/* The Action Buttons */}
                <div className="flex gap-4">
                    <button
                        type="button"
                        onClick={onSubmit}
                        disabled={isRunning}
                        className={`flex-1 font-medium py-3 rounded-lg text-white transition-colors
                            ${isRunning ? "bg-gray-400 cursor-not-allowed" : "bg-gray-900 hover:bg-gray-800"}`}
                    >
                        {isRunning ? "Processing Data..." : "Process Data"}
                    </button>

                    {/* Only show Cancel button if actively processing */}
                    {isRunning && (
                        <button
                            type="button"
                            onClick={onCancel}
                            className="px-6 py-3 border border-red-200 text-red-600 font-medium rounded-lg hover:bg-red-50 transition-colors"
                        >
                            Cancel
                        </button>
                    )}
                </div>

                {/* The Progress Bar (Only visible when running) */}
                {isRunning && (
                    <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                        <div
                            className="bg-blue-600 h-2.5 transition-all duration-500 ease-out"
                            style={{ width: `${progress}%` }}
                        ></div>
                        <p className="text-xs text-center text-gray-500 mt-2 font-medium tracking-wide">
                            {jobStatus} ({progress}%)
                        </p>
                    </div>
                )}

                {/* Success Output */}
                {jobStatus === "SUCCESS" && resultData && (
                    <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                        <h3 className="text-green-800 font-medium">
                            Processing Complete
                        </h3>
                        <p className="text-sm text-green-700 mt-1">
                            {resultData.message}
                        </p>
                        <div className="mt-2 p-2 bg-white rounded border border-green-100 font-mono text-xs text-gray-600 break-all">
                            <strong>Regex Applied:</strong>{" "}
                            {resultData.regex_used}
                        </div>
                    </div>
                )}

                {/* Error Output */}
                {jobStatus === "FAILED" && errorMessage && (
                    <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                        <h3 className="text-red-800 font-medium">
                            Error Processing Data
                        </h3>
                        <p className="text-sm text-red-700 mt-1">
                            {errorMessage}
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}
