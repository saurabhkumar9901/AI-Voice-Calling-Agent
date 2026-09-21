'use client';

import { Headphones, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { useAuth } from '@/lib/auth';
import {
    downloadRunArtifact,
    getRunArtifactObjectUrl,
    fetchRunTranscriptText,
    RunArtifactKind,
} from '@/lib/files';

export function MediaPreviewDialog() {
    const auth = useAuth();
    const [isOpen, setIsOpen] = useState(false);
    const [audioObjectUrl, setAudioObjectUrl] = useState<string | null>(null);
    const [transcriptContent, setTranscriptContent] = useState<string | null>(null);
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);
    const [hasRecording, setHasRecording] = useState(false);
    const [hasTranscript, setHasTranscript] = useState(false);
    const [mediaLoading, setMediaLoading] = useState(false);
    const [mediaError, setMediaError] = useState<string | null>(null);

    const revokeAudioUrl = useCallback(() => {
        setAudioObjectUrl((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return null;
        });
    }, []);

    // Revoke object URLs when the dialog closes or unmounts.
    useEffect(() => {
        if (!isOpen) revokeAudioUrl();
    }, [isOpen, revokeAudioUrl]);

    useEffect(() => revokeAudioUrl, [revokeAudioUrl]);

    const openPreview = useCallback(
        async (workflowId: number, runId: number, recording: boolean, transcript: boolean) => {
            if (!recording && !transcript) return;
            revokeAudioUrl();
            setMediaLoading(true);
            setMediaError(null);
            setTranscriptContent(null);
            setHasRecording(recording);
            setHasTranscript(transcript);
            setSelectedRunId(runId);
            setSelectedWorkflowId(workflowId);
            setIsOpen(true);

            try {
                const getToken = () => auth.getAccessToken();
                const [audioResult, transcriptResult] = await Promise.all([
                    recording ? getRunArtifactObjectUrl(workflowId, runId, 'recording', getToken) : null,
                    transcript ? fetchRunTranscriptText(workflowId, runId, getToken) : null,
                ]);

                if (audioResult) {
                    setAudioObjectUrl(audioResult);
                }
                if (transcriptResult !== null) {
                    setTranscriptContent(transcriptResult);
                }
            } catch (error) {
                console.error('Error loading preview:', error);
                setMediaError('Failed to load recording or transcript.');
            } finally {
                setMediaLoading(false);
            }
        },
        [auth, revokeAudioUrl],
    );

    const handleDownload = useCallback(
        async (kind: RunArtifactKind) => {
            if (selectedWorkflowId === null || selectedRunId === null) return;
            try {
                await downloadRunArtifact(selectedWorkflowId, selectedRunId, kind, () =>
                    auth.getAccessToken(),
                );
            } catch (error) {
                console.error('Error downloading file:', error);
            }
        },
        [auth, selectedWorkflowId, selectedRunId],
    );

    return {
        openPreview,
        dialog: (
            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent className="sm:max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>
                            Run Preview
                            {selectedRunId && ` - Run #${selectedRunId}`}
                        </DialogTitle>
                    </DialogHeader>

                    {mediaLoading && (
                        <div className="flex items-center justify-center py-8 space-x-2">
                            <Loader2 className="h-6 w-6 animate-spin" />
                            <span>Loading...</span>
                        </div>
                    )}

                    {!mediaLoading && audioObjectUrl && (
                        <audio src={audioObjectUrl} controls autoPlay className="w-full mt-4" />
                    )}

                    {!mediaLoading && transcriptContent && (
                        <pre className="w-full h-[60vh] overflow-auto border rounded-md mt-4 p-4 bg-muted text-sm whitespace-pre-wrap font-mono">
                            {transcriptContent}
                        </pre>
                    )}

                    {!mediaLoading && !audioObjectUrl && !transcriptContent && (
                        <div className="flex items-center justify-center py-8 text-muted-foreground">
                            {mediaError ?? 'No recording or transcript available.'}
                        </div>
                    )}

                    <DialogFooter className="pt-4">
                        <DialogClose asChild>
                            <Button variant="secondary">Close</Button>
                        </DialogClose>
                        <div className="flex gap-2">
                            {hasRecording && (
                                <Button variant="outline" onClick={() => handleDownload('recording')}>
                                    Download Recording
                                </Button>
                            )}
                            {hasTranscript && (
                                <Button variant="outline" onClick={() => handleDownload('transcript')}>
                                    Download Transcript
                                </Button>
                            )}
                        </div>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        ),
    };
}

interface MediaPreviewButtonProps {
    workflowId: number;
    runId: number;
    hasRecording: boolean;
    hasTranscript: boolean;
    onOpenPreview: (workflowId: number, runId: number, hasRecording: boolean, hasTranscript: boolean) => void;
    onSelect?: (runId: number) => void;
}

export function MediaPreviewButton({
    workflowId,
    runId,
    hasRecording,
    hasTranscript,
    onOpenPreview,
    onSelect,
}: MediaPreviewButtonProps) {
    if (!hasRecording && !hasTranscript) return null;

    const handleOpen = () => {
        onSelect?.(runId);
        onOpenPreview(workflowId, runId, hasRecording, hasTranscript);
    };

    return (
        <Button
            variant="outline"
            size="icon"
            onClick={handleOpen}
        >
            <Headphones className="h-4 w-4" />
        </Button>
    );
}
