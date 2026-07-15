import { NextRequest, NextResponse } from "next/server";

// Gates the entire site behind HTTP Basic Auth when BASIC_AUTH_USER and
// BASIC_AUTH_PASSWORD are set, so a publicly deployed demo is only usable by
// whoever you hand the credentials to. No-ops when either is unset (e.g.
// local development). The browser's native login prompt handles this once
// per session — no frontend code changes needed beyond this file.
export function middleware(request: NextRequest) {
    const user = process.env.BASIC_AUTH_USER;
    const password = process.env.BASIC_AUTH_PASSWORD;

    if (!user || !password) {
        return NextResponse.next();
    }

    const authHeader = request.headers.get("authorization");

    if (authHeader?.startsWith("Basic ")) {
        const decoded = Buffer.from(authHeader.slice(6), "base64").toString();
        const [providedUser, providedPassword] = decoded.split(":");

        if (providedUser === user && providedPassword === password) {
            return NextResponse.next();
        }
    }

    return new NextResponse("Authentication required.", {
        status: 401,
        headers: {
            "WWW-Authenticate": 'Basic realm="Restricted", charset="UTF-8"',
        },
    });
}

export const config = {
    // Apply to every route, including static assets, so there's no
    // unauthenticated way to view the app.
    matcher: "/:path*",
};
