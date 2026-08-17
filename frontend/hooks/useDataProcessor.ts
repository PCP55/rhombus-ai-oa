import { useEffect, useState } from "react";
import {
    apiFetch,
    apiUploadWithProgress,
    formatUploadError,
    type JobResultData,
} from "../lib/api";

/**
 * Helper: Polls the backend until the uploaded file has been processed
 * enough to discover its columns.
 *
 * @param jobId - The UUID of the uploaded file draft.
 * @returns A promise that resolves to an array of column names.
 * @throws Error if polling times out (60s) or the backend reports a failure.
 */
async function pollForColumns(jobId: string): Promise<string[]> {
    // Cap attempts at 60 to prevent infinite loops (60 attempts * 1s = 1 minute timeout)
    for (let attempt = 0; attempt < 60; attempt++) {
        const res = await apiFetch(`/api/status/${jobId}/`);
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || "Failed to read column names.");
        }
        if (data.status === "FAILED") {
            throw new Error(
                data.error_message || "Could not read columns from this file."
            );
        }

        // Success condition: Backend has parsed the CSV and returned headers
        if (data.columns?.length) {
            return data.columns;
        }

        // Wait 1 second before polling again to avoid hammering the server
        await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    throw new Error("Timed out waiting for column discovery.");
}

/**
 * Custom Hook: useDataProcessor
 * Encapsulates all state, file uploading, and job polling logic for the processing pipeline.
 */
export function useDataProcessor() {
    // --- 1. Form Input State ---
    const [file, setFile] = useState<File | null>(null);
    const [columns, setColumns] = useState<string[]>([]);
    const [targetColumn, setTargetColumn] = useState("");
    const [prompt, setPrompt] = useState("");
    const [replacementValue, setReplacementValue] = useState("");

    // --- 2. Job Tracking State ---
    // State machine: "" -> INSPECTING -> DRAFT -> SUBMITTING -> QUEUED -> RUNNING -> SUCCESS/FAILED
    const [jobId, setJobId] = useState<string | null>(null);
    const [jobStatus, setJobStatus] = useState<string>("");
    const [progress, setProgress] = useState<number>(0);
    const [resultData, setResultData] = useState<JobResultData | null>(null);
    const [errorMessage, setErrorMessage] = useState<string>("");

    // Tracks multipart file upload progress to the server (distinct from job processing progress)
    const [uploadProgress, setUploadProgress] = useState<number>(0);

    // --- 3. Handlers ---

    /**
     * Handles the initial file selection. Uploads the file to create a 'DRAFT'
     * job and automatically polls for column headers.
     */
    const onFileSelected = async (selectedFile: File) => {
        // Cleanup: If user swaps files mid-flight, cancel the previous draft to save server resources
        if (jobId && (jobStatus === "DRAFT" || jobStatus === "INSPECTING")) {
            apiFetch(`/api/cancel/${jobId}/`, { method: "POST" }).catch(() => {
                // Silently catch error: we don't care if cancelling an orphaned draft fails
            });
        }

        // Reset state for the new file
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

                // Fetch columns so the UI can populate the column selection dropdown
                const discoveredColumns = await pollForColumns(id);
                setColumns(discoveredColumns);
                setJobStatus("DRAFT");
            } else {
                setJobStatus("FAILED");
                setErrorMessage(formatUploadError(result));
            }
        } catch (error) {
            console.error("Upload error:", error);
            setJobStatus("FAILED");
            setErrorMessage(
                error instanceof Error
                    ? error.message
                    : "Network Error: Could not reach the backend.",
            );
        }
    };

    /**
     * Commits the draft job to the background queue (e.g., Celery/Spark) for full processing.
     */
    const onSubmit = async () => {
        // Basic validation guard
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
                setJobStatus(data.status); // Transitions to "QUEUED"
            } else {
                setJobStatus("FAILED");
                setErrorMessage(data.error || "Failed to submit job.");
            }
        } catch (error) {
            console.error("Submit error:", error);
            setJobStatus("FAILED");
            setErrorMessage("Network Error: Could not reach the backend.");
        }
    };

    /**
     * Aborts an active or queued job.
     */
    const onCancel = async () => {
        if (!jobId) return;

        try {
            await apiFetch(`/api/cancel/${jobId}/`, { method: "POST" });
            setJobStatus("FAILED");
            setErrorMessage("Job was cancelled by the user.");
        } catch (error) {
            console.error("Failed to cancel job", error);
        }
    };

    // --- 4. Background Polling Effect ---

    /**
     * Listens to jobStatus. If a job is actively running in the background,
     * spin up an interval to poll the backend every 2 seconds for progress updates.
     */
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

                        // Job terminal states - cleanup interval and update UI
                        if (data.status === "SUCCESS") {
                            setResultData(data.result_data);
                            clearInterval(intervalId);
                        } else if (data.status === "FAILED") {
                            setErrorMessage(
                                data.error_message || "Task failed in the background."
                            );
                            clearInterval(intervalId);
                        }
                    }
                } catch (err) {
                    console.error("Status polling error", err);
                }
            }, 2000); // 2000ms = 2 seconds
        }

        // Cleanup function: clears the interval if the component unmounts
        // or if jobId/jobStatus change to prevent memory leaks.
        return () => clearInterval(intervalId);
    }, [jobId, jobStatus]);

    // Expose only what the UI needs to render and interact
    return {
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
    };
}
