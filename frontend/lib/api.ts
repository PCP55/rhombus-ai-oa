// Central place for talking to the Django backend so the API origin and
// access key aren't hardcoded/duplicated across components.

export const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const ACCESS_KEY = process.env.NEXT_PUBLIC_APP_ACCESS_KEY || "";

/**
 * fetch() wrapper that targets the Django API and attaches the shared
 * X-Access-Key header (see backend/api/middleware.py). A no-op header when
 * NEXT_PUBLIC_APP_ACCESS_KEY isn't set, e.g. local development.
 */
export function apiFetch(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    if (ACCESS_KEY) {
        headers.set("X-Access-Key", ACCESS_KEY);
    }

    return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

/** JSON shape returned by POST /api/upload/ */
export interface UploadResponse {
    job_id: string;
    status: string;
    columns: string[];
    error?: string;
}

/** Preview metadata stored on a completed job */
export interface JobResultData {
    message: string;
    regex_used: string;
    preview: Record<string, unknown>[];
}

export interface UploadResult<T = UploadResponse | null> {
    ok: boolean;
    status: number;
    data: T;
    // Raw response body, kept around so callers can surface *something*
    // useful (status code, a snippet of an HTML error page, etc.) when the
    // response wasn't valid JSON -- e.g. a proxy/gateway timeout page, or a
    // worker crashing before Django gets a chance to return real JSON.
    rawText: string;
}

/**
 * POSTs `formData` to the Django API with real upload-progress reporting.
 *
 * fetch() intentionally has no way to observe request-body upload progress
 * (only download/response progress via ReadableStream) -- so for a
 * multi-hundred-MB/multi-GB file, apiFetch() would otherwise look "stuck"
 * for however long the transfer takes, with no feedback at all.
 * XMLHttpRequest's `upload.onprogress` is the one browser API that still
 * exposes this, so this uses XHR instead of fetch specifically for uploads.
 */
export function apiUploadWithProgress(
    path: string,
    formData: FormData,
    onProgress?: (percent: number) => void,
): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE_URL}${path}`);
        if (ACCESS_KEY) {
            xhr.setRequestHeader("X-Access-Key", ACCESS_KEY);
        }

        xhr.upload.onprogress = (event) => {
            if (onProgress && event.lengthComputable) {
                onProgress(Math.round((event.loaded / event.total) * 100));
            }
        };

        xhr.onload = () => {
            let data: UploadResponse | null = null;
            try {
                data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
            } catch {
                data = null;
            }
            resolve({
                ok: xhr.status >= 200 && xhr.status < 300,
                status: xhr.status,
                data,
                rawText: xhr.responseText || "",
            });
        };

        xhr.onerror = () =>
            reject(
                new Error(
                    "Network error while uploading the file (connection dropped or was refused).",
                ),
            );
        xhr.onabort = () => reject(new Error("Upload was cancelled."));
        xhr.ontimeout = () =>
            reject(new Error("Upload timed out before the server responded."));

        xhr.send(formData);
    });
}

/** Turn an upload API result into a user-visible error string. */
export function formatUploadError(result: UploadResult): string {
    if (result.data?.error) {
        return result.data.error;
    }

    if (result.status === 413) {
        return "Uploaded file is too large for the server limit.";
    }
    if (result.status === 401) {
        return "Unauthorized — the API access key may be missing or wrong.";
    }
    if (result.status === 507) {
        return (
            "The server could not store this file — it may be out of disk space."
        );
    }
    if (result.status >= 500) {
        return (
            `Server error (HTTP ${result.status}) while saving the upload. ` +
            "Check `docker compose logs web` on the droplet for details."
        );
    }

    if (result.rawText) {
        const snippet = result.rawText
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 200);
        if (snippet) {
            return `Upload failed (HTTP ${result.status}): ${snippet}`;
        }
    }

    return `Upload failed (HTTP ${result.status || "unknown"}).`;
}
