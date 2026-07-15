"use client";

import { useEffect, useState } from "react";
import ExtractionForm from "../components/ExtractionForm";
import FileDropzone from "../components/FileDropzone";

import ResultsTable from "../components/ResultsTable";
import {
    apiFetch,
    apiUploadWithProgress,
    formatUploadError,
    type JobResultData,
} from "../lib/api";

/** Poll /api/status/ until columns are populated after upload. */
async function pollForColumns(jobId: string): Promise<string[]> {
    for (let attempt = 0; attempt < 60; attempt++) {
        const res = await apiFetch(`/api/status/${jobId}/`);
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || "Failed to read column names.");
        }
        if (data.status === "FAILED") {
            throw new Error(
                data.error_message || "Could not read columns from this file.",
            );
        }
        if (data.columns?.length) {
            return data.columns;
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    throw new Error("Timed out waiting for column discovery.");
}

export default function Home() {
    // 1. Form Input State
    const [file, setFile] = useState<File | null>(null);
    const [columns, setColumns] = useState<string[]>([]);
    const [targetColumn, setTargetColumn] = useState("");
    const [prompt, setPrompt] = useState("");
    const [replacementValue, setReplacementValue] = useState("");

    // 2. Job Tracking State
    // "" -> INSPECTING -> DRAFT -> SUBMITTING -> QUEUED -> RUNNING -> SUCCESS/FAILED
    const [jobId, setJobId] = useState<string | null>(null);
    const [jobStatus, setJobStatus] = useState<string>("");
    const [progress, setProgress] = useState<number>(0);
    const [resultData, setResultData] = useState<JobResultData | null>(null);
    const [errorMessage, setErrorMessage] = useState<string>("");
    // Percentage of the file actually transferred to the server so far --
    // separate from `progress` above (which tracks Celery/Spark progress
    // once the job is queued). Large files can take a while just to upload,
    // well before there's any job to poll status for.
    const [uploadProgress, setUploadProgress] = useState<number>(0);

    // 3. File Selection Handler — uploads the file immediately (once) and
    // reads back its real column names, so the form can offer a dropdown
    // instead of asking the user to type a column name from memory.
    const onFileSelected = async (selectedFile: File) => {
        // Discard the previous draft (if any) so we don't leave an orphaned
        // upload sitting on the server every time someone swaps files.
        if (jobId && (jobStatus === "DRAFT" || jobStatus === "INSPECTING")) {
            apiFetch(`/api/cancel/${jobId}/`, { method: "POST" }).catch(
                () => {},
            );
        }

        setFile(selectedFile);
        setJobId(null);
        setColumns([]);
        setTargetColumn("");
        setResultData(null);
        setErrorMessage("");
        setUploadProgress(0);
        setJobStatus("INSPECTING");

        const formData = new FormData();
        formData.append("file", selectedFile);

        try {
            const result = await apiUploadWithProgress(
                "/api/upload/",
                formData,
                setUploadProgress,
            );

            if (result.ok && result.data?.job_id) {
                const id = result.data.job_id;
                setJobId(id);

                const discoveredColumns = await pollForColumns(id);
                setColumns(discoveredColumns);
                setJobStatus("DRAFT");
            } else {
                setJobStatus("FAILED");
                setErrorMessage(formatUploadError(result));
            }
        } catch (error) {
            console.error(error);
            setJobStatus("FAILED");
            setErrorMessage(
                error instanceof Error
                    ? error.message
                    : "Network Error: Could not reach the Django backend.",
            );
        }
    };

    // 4. The Submit Handler — attaches the chosen column/prompt/replacement
    // to the already-uploaded draft job and actually queues it.
    const onSubmit = async () => {
        if (!jobId || !targetColumn.trim() || !prompt.trim()) {
            alert("Please fill out all required fields.");
            return;
        }

        setJobStatus("SUBMITTING");
        setErrorMessage("");

        const formData = new FormData();
        formData.append("target_column", targetColumn);
        formData.append("prompt", prompt);
        formData.append("replacement_value", replacementValue);

        try {
            const response = await apiFetch(`/api/submit/${jobId}/`, {
                method: "POST",
                body: formData,
            });

            const data = await response.json();

            if (response.ok) {
                setProgress(0);
                setJobStatus(data.status); // "QUEUED"
            } else {
                setJobStatus("FAILED");
                setErrorMessage(data.error || "Failed to submit job.");
            }
        } catch (error) {
            console.error(error);
            setJobStatus("FAILED");
            setErrorMessage(
                "Network Error: Could not reach the Django backend.",
            );
        }
    };

    // 5. The Cancel Handler
    const onCancel = async () => {
        if (!jobId) return;

        try {
            await apiFetch(`/api/cancel/${jobId}/`, {
                method: "POST",
            });
            setJobStatus("FAILED");
            setErrorMessage("Job was cancelled by the user.");
        } catch (error) {
            console.error("Failed to cancel job", error);
        }
    };

    // 6. The Poller (Background Listener) — only once the job is actually
    // queued/running in Celery; DRAFT/INSPECTING have nothing to poll yet.
    useEffect(() => {
        let intervalId: ReturnType<typeof setInterval>;

        if (jobId && (jobStatus === "QUEUED" || jobStatus === "RUNNING")) {
            intervalId = setInterval(async () => {
                try {
                    const res = await apiFetch(`/api/status/${jobId}/`);
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

    // 7. The UI Render
    return (
        <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
            <div className="bg-white w-full max-w-xl rounded-xl shadow-sm p-8">
                <h1 className="text-2xl font-bold text-gray-900">
                    Data Processor
                </h1>
                <p className="text-gray-500 mt-2 mb-6">
                    Upload a CSV and define your dynamic regex rules.
                </p>

                <FileDropzone
                    file={file}
                    onFileSelected={onFileSelected}
                    isInspecting={jobStatus === "INSPECTING"}
                    uploadProgress={uploadProgress}
                />

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

                {/* Render the Table when the job is finished */}
                {jobStatus === "SUCCESS" && jobId && (
                    <ResultsTable jobId={jobId} />
                )}
            </div>
        </main>
    );
}
