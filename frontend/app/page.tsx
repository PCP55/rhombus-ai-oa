"use client";

import ExtractionForm from "../components/ExtractionForm";
import FileDropzone from "../components/FileDropzone";
import ResultsTable from "../components/ResultsTable";
import { useDataProcessor } from "../hooks/useDataProcessor";

/**
 * Home Page Component
 * Serves as the main layout wrapper for the Data Processor workflow.
 * Connects the `useDataProcessor` hook to the presentation components.
 */
export default function Home() {
    // Destructure all required state and methods from our custom logic hook
    const {
        file,
        columns,
        targetColumn,
        setTargetColumn,
        prompt,
        setPrompt,
        replacementValue,
        setReplacementValue,
        jobId,
        jobStatus,
        progress,
        resultData,
        errorMessage,
        uploadProgress,
        onFileSelected,
        onSubmit,
        onCancel,
    } = useDataProcessor();

    return (
        // Main wrapper: Full viewport height, centered content with a soft gray background
        <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">

            {/* Card Container: Constrains width and adds styling for the app interface */}
            <div className="bg-white w-full max-w-xl rounded-xl shadow-sm p-8">

                {/* Header Section */}
                <h1 className="text-2xl font-bold text-gray-900">
                    Data Processor
                </h1>
                <p className="text-gray-500 mt-2 mb-6">
                    Upload a CSV and define your dynamic regex rules.
                </p>

                {/*
                  Step 1: File Upload
                  Handles the drag-and-drop UI and shows immediate upload transfer progress.
                */}
                <FileDropzone
                    file={file}
                    onFileSelected={onFileSelected}
                    isInspecting={jobStatus === "INSPECTING"}
                    uploadProgress={uploadProgress}
                />

                {/*
                  Step 2: Configuration & Processing
                  Collects user inputs (columns, prompts) and displays the background
                  processing bar (Celery/Spark progress) once submitted.
                */}
                <ExtractionForm
                    columns={columns}
                    targetColumn={targetColumn}
                    setTargetColumn={setTargetColumn}
                    prompt={prompt}
                    setPrompt={setPrompt}
                    replacement={replacementValue}
                    setReplacement={setReplacementValue}
                    jobStatus={jobStatus}
                    progress={progress}
                    resultData={resultData}
                    errorMessage={errorMessage}
                    onSubmit={onSubmit}
                    onCancel={onCancel}
                />

                {/*
                  Step 3: Results
                  Conditionally renders the results table ONLY when the backend
                  job completes successfully.
                */}
                {jobStatus === "SUCCESS" && jobId && (
                    <ResultsTable jobId={jobId} />
                )}

            </div>
        </main>
    );
}
