/**
 * Same-origin, authenticated run-artifact helpers.
 *
 * Recordings/transcripts are streamed through the backend
 * (`/api/v1/workflow/{workflowId}/runs/{runId}/{recording|transcript}`) so
 * playback works in browsers even when the storage backend itself is not
 * directly reachable (e.g. internal MinIO behind HTTP on an HTTPS site).
 */

export type RunArtifactKind = 'recording' | 'transcript';

export function runArtifactFilename(
    runId: number,
    kind: RunArtifactKind,
): string {
    return `run-${runId}-${kind}${kind === 'recording' ? '.wav' : '.txt'}`;
}

export async function fetchRunArtifact(
    workflowId: number,
    runId: number,
    kind: RunArtifactKind,
    getToken: () => Promise<string>,
): Promise<Blob> {
    const accessToken = await getToken();
    const response = await fetch(
        `/api/v1/workflow/${workflowId}/runs/${runId}/${kind}`,
        {
            headers: { Authorization: `Bearer ${accessToken}` },
        },
    );
    if (!response.ok) {
        throw new Error(`Failed to fetch ${kind} (HTTP ${response.status})`);
    }
    return await response.blob();
}

export async function fetchRunTranscriptText(
    workflowId: number,
    runId: number,
    getToken: () => Promise<string>,
): Promise<string> {
    const blob = await fetchRunArtifact(workflowId, runId, 'transcript', getToken);
    return await blob.text();
}

/**
 * Download a run artifact via a temporary object URL (authenticated fetch).
 */
export async function downloadRunArtifact(
    workflowId: number,
    runId: number,
    kind: RunArtifactKind,
    getToken: () => Promise<string>,
): Promise<void> {
    const blob = await fetchRunArtifact(workflowId, runId, kind, getToken);
    const objectUrl = URL.createObjectURL(blob);
    try {
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = runArtifactFilename(runId, kind);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } finally {
        // Revoke after the browser has picked up the download.
        setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
    }
}

/**
 * Object URL for in-browser preview (e.g. <audio src>). Caller must revoke
 * via URL.revokeObjectURL when done.
 */
export async function getRunArtifactObjectUrl(
    workflowId: number,
    runId: number,
    kind: RunArtifactKind,
    getToken: () => Promise<string>,
): Promise<string> {
    const blob = await fetchRunArtifact(workflowId, runId, kind, getToken);
    return URL.createObjectURL(blob);
}
