"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

const GEMINI_VOICES = [
    { id: "Puck", name: "Puck", description: "Warm and approachable" },
    { id: "Charon", name: "Charon", description: "Deep and authoritative" },
    { id: "Kore", name: "Kore", description: "Bright and enthusiastic" },
    { id: "Fenrir", name: "Fenrir", description: "Strong and energetic" },
    { id: "Aoede", name: "Aoede", description: "Calm and articulate" },
];

interface GeminiVoiceSelectorProps {
    value: string;
    onChange: (voiceId: string) => void;
    className?: string;
}

export const GeminiVoiceSelector: React.FC<GeminiVoiceSelectorProps> = ({
    value,
    onChange,
    className,
}) => {
    return (
        <div className={cn("grid grid-cols-2 md:grid-cols-3 gap-3", className)}>
            {GEMINI_VOICES.map((voice) => {
                const isSelected = value === voice.id;

                return (
                    <div
                        key={voice.id}
                        onClick={() => onChange(voice.id)}
                        className={cn(
                            "relative flex flex-col items-center justify-center p-4 rounded-xl border-2 cursor-pointer transition-all duration-200",
                            "hover:border-primary/50 hover:bg-accent/50 hover:shadow-sm",
                            isSelected
                                ? "border-primary bg-primary/5 shadow-md scale-[1.02]"
                                : "border-muted bg-background text-muted-foreground"
                        )}
                    >
                        {isSelected && (
                            <div className="absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                                <Check className="h-3 w-3" strokeWidth={3} />
                            </div>
                        )}
                        <span className={cn(
                            "font-semibold text-lg mb-1 tracking-tight",
                            isSelected ? "text-foreground" : "text-muted-foreground"
                        )}>
                            {voice.name}
                        </span>
                        <span className="text-xs text-center leading-tight opacity-80">
                            {voice.description}
                        </span>
                    </div>
                );
            })}
        </div>
    );
};
