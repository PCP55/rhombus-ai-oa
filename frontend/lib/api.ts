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

export interface UploadResult {
    ok: boolean;
    status: number;
    data: any;
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
            let data: any = null;
            try {
                data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
            } catch {
                data = null;
            }
            resolve({
                ok: xhr.status >= 200 && xhr.status < 300,
                status: xhr.status,
                data,
            });
        };

        xhr.onerror = () =>
            reject(new Error("Network error while uploading the file."));
        xhr.onabort = () => reject(new Error("Upload was cancelled."));

        xhr.send(formData);
    });
}
