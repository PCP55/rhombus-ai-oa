import React from "react";

import type { JobResultData } from "../lib/api";

// 1. The Interface Contract
interface ExtractionFormProps {
    columns: string[];
    targetColumn: string;
    setTargetColumn: (val: string) => void;
    prompt: string;
    setPrompt: (val: string) => void;
    replacement: string;
    setReplacement: (val: string) => void;

    // Tracking Props
    jobStatus: string;
    progress: number;
    resultData: JobResultData | null;
    errorMessage: string;

    // Actions
    onSubmit: () => void;
    onCancel: () => void;
}

export default function ExtractionForm({
    columns,
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
    // Locks the whole form down while a file is being inspected or a job is
    // being submitted/queued/run — none of these are safe moments to edit inputs.
    const isBusy = ["INSPECTING", "SUBMITTING", "QUEUED", "RUNNING"].includes(
        jobStatus,
    );
    // Only QUEUED/RUNNING jobs actually exist in Celery and can be cancelled.
    const isActive = ["QUEUED", "RUNNING"].includes(jobStatus);
    const hasColumns = columns.length > 0;

    return (
        <div className="space-y-6 mt-6">
            {/* --- User Input Section --- */}
            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Target Column
                </label>
                <select
                    value={targetColumn}
                    onChange={(e) => setTargetColumn(e.target.value)}
                    disabled={isBusy || !hasColumns}
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-900 disabled:opacity-50"
                >
                    <option value="" disabled>
                        {hasColumns
                            ? "Select a column…"
                            : "Upload a file to see its columns"}
                    </option>
                    {columns.map((column) => (
                        <option key={column} value={column}>
                            {column}
                        </option>
                    ))}
                </select>
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Natural Language Regex Rule
                </label>
                <textarea
                    rows={3}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    disabled={isBusy}
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
                    disabled={isBusy}
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
                        disabled={isBusy || !hasColumns}
                        className={`flex-1 font-medium py-3 rounded-lg text-white transition-colors
                            ${isBusy || !hasColumns ? "bg-gray-400 cursor-not-allowed" : "bg-gray-900 hover:bg-gray-800"}`}
                    >
                        {jobStatus === "SUBMITTING"
                            ? "Submitting..."
                            : isActive
                              ? "Processing Data..."
                              : "Process Data"}
                    </button>

                    {/* Only show Cancel button if actively processing */}
                    {isActive && (
                        <button
                            type="button"
                            onClick={onCancel}
                            className="px-6 py-3 border border-red-200 text-red-600 font-medium rounded-lg hover:bg-red-50 transition-colors"
                        >
                            Cancel
                        </button>
                    )}
                </div>

                {/* The Progress Bar (Only visible once a job is actually queued/running) */}
                {isActive && (
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
