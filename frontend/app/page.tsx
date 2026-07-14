"use client";

import { useEffect, useState } from "react";
import ExtractionForm from "../components/ExtractionForm";
import FileDropzone from "../components/FileDropzone";

import ResultsTable from "../components/ResultsTable";

export default function Home() {
    // 1. Form Input State
    const [file, setFile] = useState<File | null>(null);
    const [targetColumn, setTargetColumn] = useState("");
    const [prompt, setPrompt] = useState("");
    const [replacementValue, setReplacementValue] = useState("");

    // 2. Job Tracking State (Notice: isLoading is gone!)
    const [jobId, setJobId] = useState<string | null>(null);
    const [jobStatus, setJobStatus] = useState<string>("");
    const [progress, setProgress] = useState<number>(0);
    const [resultData, setResultData] = useState<any>(null);
    const [errorMessage, setErrorMessage] = useState<string>("");

    // 3. The Submit Handler
    const onSubmit = async () => {
        if (!file || !targetColumn.trim() || !prompt.trim()) {
            alert("Please fill out all required fields.");
            return;
        }

        // Reset tracking state before a fresh run
        setJobId(null);
        setJobStatus("SUBMITTING");
        setProgress(0);
        setResultData(null);
        setErrorMessage("");

        const formData = new FormData();
        formData.append("file", file);
        formData.append("target_column", targetColumn);
        formData.append("prompt", prompt);
        formData.append("replacement_value", replacementValue);

        try {
            const response = await fetch("http://localhost:8000/api/upload/", {
                method: "POST",
                body: formData,
            });

            const data = await response.json();

            if (response.ok) {
                setJobId(data.job_id);
                setJobStatus("QUEUED");
            } else {
                setJobStatus("FAILED");
                setErrorMessage(data.error || "Failed to submit job.");
            }
        } catch (error) {
            console.error(error);
            setJobStatus("FAILED");
            setErrorMessage(
                "Network Error: Could not reach the Django backend on port 8000.",
            );
        }
    };

    // 4. The Cancel Handler (Newly added!)
    const onCancel = async () => {
        if (!jobId) return;

        try {
            await fetch(`http://localhost:8000/api/cancel/${jobId}/`, {
                method: "POST",
            });
            setJobStatus("FAILED");
            setErrorMessage("Job was cancelled by the user.");
        } catch (error) {
            console.error("Failed to cancel job", error);
        }
    };

    // 5. The Poller (Background Listener)
    useEffect(() => {
        let intervalId: ReturnType<typeof setInterval>;

        // ONLY start asking if we actually have a jobId and it is actively running
        if (jobId && (jobStatus === "QUEUED" || jobStatus === "RUNNING")) {
            intervalId = setInterval(async () => {
                try {
                    const res = await fetch(
                        `http://localhost:8000/api/status/${jobId}/`,
                    );
                    const data = await res.json();

                    if (res.ok) {
                        setJobStatus(data.status);
                        setProgress(data.progress || 0);

                        // If it's done, save the results and stop asking
                        if (data.status === "SUCCESS") {
                            setResultData(data.result_data);
                            clearInterval(intervalId);
                        } else if (data.status === "FAILED") {
                            setErrorMessage(
                                data.error_message ||
                                    "Task failed in the background.",
                            );
                            clearInterval(intervalId);
                        }
                    }
                } catch (err) {
                    console.error("Polling error", err);
                }
            }, 2000);
        }

        return () => clearInterval(intervalId);
    }, [jobId, jobStatus]);

    // 6. The UI Render
    return (
        <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
            <div className="bg-white w-full max-w-xl rounded-xl shadow-sm p-8">
                <h1 className="text-2xl font-bold text-gray-900">
                    Data Processor
                </h1>
                <p className="text-gray-500 mt-2 mb-6">
                    Upload a CSV and define your dynamic regex rules.
                </p>

                <FileDropzone file={file} setFile={setFile} />

                <ExtractionForm
                    targetColumn={targetColumn}
                    setTargetColumn={setTargetColumn}
                    prompt={prompt}
                    setPrompt={setPrompt}

                    // Perfectly mapped variables to match the interface contract
                    replacement={replacementValue}
                    setReplacement={setReplacementValue}

                    jobStatus={jobStatus}
                    progress={progress}
                    resultData={resultData}
                    errorMessage={errorMessage}

                    onSubmit={onSubmit}
                    onCancel={onCancel}
                />

                {/* Render the Table when the job is finished */}
                {jobStatus === "SUCCESS" && jobId && (
                    <ResultsTable jobId={jobId} />
                )}
            </div>
        </main>
    );
}
