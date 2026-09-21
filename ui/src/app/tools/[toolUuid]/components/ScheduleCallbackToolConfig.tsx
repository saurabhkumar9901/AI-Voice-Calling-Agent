"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface ScheduleCallbackToolConfigProps {
    name: string;
    onNameChange: (name: string) => void;
    description: string;
    onDescriptionChange: (description: string) => void;
}

export function ScheduleCallbackToolConfig({
    name,
    onNameChange,
    description,
    onDescriptionChange,
}: ScheduleCallbackToolConfigProps) {
    return (
        <Card>
            <CardHeader>
                <CardTitle>Schedule Callback Configuration</CardTitle>
                <CardDescription>
                    No configuration needed — the agent provides the callback time
                    (and an optional note) when the caller asks to be called back.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <div className="grid gap-2">
                    <Label>Tool Name</Label>
                    <Label className="text-xs text-muted-foreground">
                        A descriptive name for this tool
                    </Label>
                    <Input
                        value={name}
                        onChange={(e) => onNameChange(e.target.value)}
                        placeholder="e.g., Schedule Callback"
                    />
                </div>

                <div className="grid gap-2">
                    <Label>Description</Label>
                    <Label className="text-xs text-muted-foreground">
                        Helps the LLM understand when to use this tool
                    </Label>
                    <Textarea
                        value={description}
                        onChange={(e) => onDescriptionChange(e.target.value)}
                        placeholder="When should the AI schedule a callback?"
                        rows={3}
                    />
                </div>

                <div className="grid gap-2 pt-4 border-t">
                    <Label>How it works</Label>
                    <Label className="text-xs text-muted-foreground">
                        When the caller says something like “call me after 4 PM”, the
                        agent calls this tool with the resolved date and time. The
                        system calls the user back automatically, and retries once
                        after 5 minutes if the line is busy or the call fails. No
                        calls are placed between 10 PM and 8 AM in the
                        caller&apos;s timezone — those move to 8 AM.
                    </Label>
                </div>
            </CardContent>
        </Card>
    );
}
