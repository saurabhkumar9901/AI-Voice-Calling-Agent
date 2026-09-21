'use client';

import { TranscriptContainer } from './shared/TranscriptContainer';

interface CallSummaryProps {
    summary: string;
}

export const CallSummary = ({ summary }: CallSummaryProps) => {
    return (
        <TranscriptContainer title="Call Summary" status="ended">
            <div className="flex-1 overflow-y-auto">
                <div className="p-4">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{summary}</p>
                </div>
            </div>
        </TranscriptContainer>
    );
};
