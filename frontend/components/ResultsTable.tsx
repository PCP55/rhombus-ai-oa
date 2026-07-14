"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";

interface ResultsTableProps {
    jobId: string;
}

export default function ResultsTable({ jobId }: ResultsTableProps) {
    const [data, setData] = useState<any[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        const fetchPage = async () => {
            setIsLoading(true);
            try {
                const res = await apiFetch(
                    `/api/results/${jobId}/?page=${currentPage}`,
                );
                const json = await res.json();

                if (res.ok) {
                    setData(json.data);
                    setTotalPages(json.pagination.total_pages);
                } else {
                    setError(json.error || "Failed to load data.");
                }
            } catch (err) {
                setError("Network error while fetching results.");
            } finally {
                setIsLoading(false);
            }
        };

        fetchPage();
    }, [jobId, currentPage]);

    if (error)
        return (
            <div className="text-red-500 mt-4 p-4 bg-red-50 rounded-lg">
                {error}
            </div>
        );
    if (data.length === 0 && !isLoading) return null;

    // Dynamically grab the column headers from the first row of data
    const headers = data.length > 0 ? Object.keys(data[0]) : [];

    return (
        <div className="mt-8 border border-gray-100 rounded-xl overflow-hidden shadow-sm bg-white">
            <div className="overflow-x-auto">
                <table className="w-full text-sm text-left text-gray-600">
                    <thead className="text-xs text-gray-500 uppercase bg-gray-50/50 border-b border-gray-100">
                        <tr>
                            {headers.map((header) => (
                                <th
                                    key={header}
                                    className="px-6 py-4 font-medium tracking-wider"
                                >
                                    {header}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {isLoading ? (
                            <tr>
                                <td
                                    colSpan={headers.length}
                                    className="px-6 py-8 text-center text-gray-400"
                                >
                                    Loading...
                                </td>
                            </tr>
                        ) : (
                            data.map((row, rowIndex) => (
                                <tr
                                    key={rowIndex}
                                    className="hover:bg-gray-50/50 transition-colors"
                                >
                                    {headers.map((header) => (
                                        <td
                                            key={header}
                                            className="px-6 py-4 whitespace-nowrap"
                                        >
                                            {/* Render redacted text distinctly if applicable */}
                                            {row[header] === "REDACTED" ? (
                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700">
                                                    REDACTED
                                                </span>
                                            ) : (
                                                row[header]
                                            )}
                                        </td>
                                    ))}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* Pagination Controls */}
            <div className="flex items-center justify-between px-6 py-4 bg-gray-50/30 border-t border-gray-100">
                <span className="text-sm text-gray-500">
                    Page{" "}
                    <span className="font-medium text-gray-900">
                        {currentPage}
                    </span>{" "}
                    of{" "}
                    <span className="font-medium text-gray-900">
                        {totalPages}
                    </span>
                </span>
                <div className="flex gap-2">
                    <button
                        onClick={() =>
                            setCurrentPage((p) => Math.max(1, p - 1))
                        }
                        disabled={currentPage === 1 || isLoading}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                        Previous
                    </button>
                    <button
                        onClick={() =>
                            setCurrentPage((p) => Math.min(totalPages, p + 1))
                        }
                        disabled={currentPage === totalPages || isLoading}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                        Next
                    </button>
                </div>
            </div>
        </div>
    );
}
