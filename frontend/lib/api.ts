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
