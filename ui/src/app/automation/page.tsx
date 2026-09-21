'use client';

import { ArrowLeft, ArrowRight, Check, ChevronDown, ChevronRight, FileSpreadsheet, PhoneCall, Upload } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ITimezoneOption } from 'react-timezone-select';
import { toast } from 'sonner';

import {
    createCampaignApiV1CampaignCreatePost,
    getCampaignDefaultsApiV1OrganizationsCampaignDefaultsGet,
    getWorkflowsSummaryApiV1WorkflowSummaryGet,
    startCampaignApiV1CampaignCampaignIdStartPost,
} from '@/client/sdk.gen';
import type { CreateCampaignRequest, WorkflowSummaryResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';

import CampaignAdvancedSettings, { getTimezoneValue, type TimeSlot } from '../campaigns/CampaignAdvancedSettings';

interface ExcelPreview {
    headers: string[];
    sample_rows: string[][];
    total_rows: number;
}

type Step = 1 | 2 | 3 | 4;

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

const NAME_GUESSES = ['name', 'full name', 'fullname', 'customer', 'customer name', 'client', 'contact', 'person'];
const PHONE_GUESSES = ['phone', 'phone number', 'phonenumber', 'mobile', 'contact number', 'tel', 'telephone'];
const CITY_GUESSES = ['city', 'location', 'town', 'address city', 'place', 'lives in', 'where they live'];

function guessColumn(headers: string[], guesses: string[]): string {
    const normalized = headers.map((h) => h.trim().toLowerCase());
    for (const guess of guesses) {
        const idx = normalized.indexOf(guess);
        if (idx !== -1) return headers[idx];
    }
    // Fallback: substring match
    for (const guess of guesses) {
        const idx = normalized.findIndex((h) => h.includes(guess) || guess.includes(h));
        if (idx !== -1) return headers[idx];
    }
    return '';
}

export default function AutomationPage() {
    const router = useRouter();
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();

    const [step, setStep] = useState<Step>(1);
    const [workflows, setWorkflows] = useState<WorkflowSummaryResponse[]>([]);
    const [isLoadingWorkflows, setIsLoadingWorkflows] = useState(true);
    const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
    const [automationName, setAutomationName] = useState('');

    const [fileKey, setFileKey] = useState('');
    const [fileName, setFileName] = useState('');
    const [uploading, setUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [preview, setPreview] = useState<ExcelPreview | null>(null);
    const [loadingPreview, setLoadingPreview] = useState(false);
    const [nameCol, setNameCol] = useState('');
    const [phoneCol, setPhoneCol] = useState('');
    const [cityCol, setCityCol] = useState('');

    const [isLaunching, setIsLaunching] = useState(false);
    const [launchError, setLaunchError] = useState<string | null>(null);

    // Advanced settings (same edit options as campaigns)
    const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
    const [orgConcurrentLimit, setOrgConcurrentLimit] = useState<number>(2);
    const [fromNumbersCount, setFromNumbersCount] = useState<number>(0);
    const [maxConcurrency, setMaxConcurrency] = useState<string>('');
    const [retryEnabled, setRetryEnabled] = useState(true);
    const [maxRetries, setMaxRetries] = useState<string>('2');
    const [retryDelaySeconds, setRetryDelaySeconds] = useState<string>('120');
    const [retryOnBusy, setRetryOnBusy] = useState(true);
    const [retryOnNoAnswer, setRetryOnNoAnswer] = useState(true);
    const [retryOnVoicemail, setRetryOnVoicemail] = useState(true);
    const [scheduleEnabled, setScheduleEnabled] = useState(false);
    const [scheduleTimezone, setScheduleTimezone] = useState<ITimezoneOption | string>(() => {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone;
        } catch {
            return 'UTC';
        }
    });
    const [timeSlots, setTimeSlots] = useState<TimeSlot[]>([
        { day_of_week: 0, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 1, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 2, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 3, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 4, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 5, start_time: '09:00', end_time: '17:00' },
        { day_of_week: 6, start_time: '09:00', end_time: '17:00' },
    ]);
    const [circuitBreakerEnabled, setCircuitBreakerEnabled] = useState(true);
    const [circuitBreakerFailureThreshold, setCircuitBreakerFailureThreshold] = useState<string>('50');
    const [circuitBreakerWindowSeconds, setCircuitBreakerWindowSeconds] = useState<string>('120');
    const [circuitBreakerMinCalls, setCircuitBreakerMinCalls] = useState<string>('5');

    useEffect(() => {
        if (!loading && !user) redirectToLogin();
    }, [loading, user, redirectToLogin]);

    const fetchWorkflows = useCallback(async () => {
        if (!user) return;
        try {
            const accessToken = await getAccessToken();
            const response = await getWorkflowsSummaryApiV1WorkflowSummaryGet({
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) setWorkflows(response.data);
        } catch (error) {
            console.error('Failed to fetch workflows:', error);
            toast.error('Failed to load voice agents');
        } finally {
            setIsLoadingWorkflows(false);
        }
    }, [user, getAccessToken]);

    useEffect(() => {
        if (user) fetchWorkflows();
    }, [user, fetchWorkflows]);

    // Fetch org limits for max-concurrency validation
    useEffect(() => {
        if (!user) return;
        const fetchDefaults = async () => {
            try {
                const accessToken = await getAccessToken();
                const response = await getCampaignDefaultsApiV1OrganizationsCampaignDefaultsGet({
                    headers: { Authorization: `Bearer ${accessToken}` },
                });
                if (response.data) {
                    setOrgConcurrentLimit(response.data.concurrent_call_limit);
                    setFromNumbersCount(response.data.from_numbers_count);
                    const retryConfig = response.data.default_retry_config;
                    if (retryConfig) {
                        setRetryEnabled(retryConfig.enabled);
                        setMaxRetries(String(retryConfig.max_retries));
                        setRetryDelaySeconds(String(retryConfig.retry_delay_seconds));
                        setRetryOnBusy(retryConfig.retry_on_busy);
                        setRetryOnNoAnswer(retryConfig.retry_on_no_answer);
                        setRetryOnVoicemail(retryConfig.retry_on_voicemail);
                    }
                }
            } catch (error) {
                console.error('Failed to fetch campaign defaults:', error);
            }
        };
        fetchDefaults();
    }, [user, getAccessToken]);

    const resetFileState = () => {
        setFileKey('');
        setFileName('');
        setPreview(null);
        setNameCol('');
        setPhoneCol('');
        setCityCol('');
    };

    const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        if (!file.name.toLowerCase().endsWith('.xlsx') && !file.name.toLowerCase().endsWith('.xls')) {
            toast.error('Please select an Excel file (.xlsx or .xls)');
            return;
        }
        if (file.size > MAX_FILE_SIZE) {
            toast.error('File size must be less than 10MB');
            return;
        }

        setUploading(true);
        try {
            const accessToken = await getAccessToken();
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch('/api/v1/s3/upload-csv-direct', {
                method: 'POST',
                headers: { Authorization: `Bearer ${accessToken}` },
                body: formData,
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: 'Upload failed' }));
                throw new Error(err.detail || 'Failed to upload file');
            }
            const data = await response.json();
            setFileKey(data.file_key);
            setFileName(file.name);
            toast.success(`File uploaded: ${file.name}`);
            await fetchPreview(data.file_key, accessToken);
        } catch (error) {
            logger.error('Error uploading Excel:', error);
            toast.error(error instanceof Error ? error.message : 'Failed to upload file');
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const fetchPreview = async (key: string, accessToken?: string) => {
        setLoadingPreview(true);
        try {
            const token = accessToken ?? (await getAccessToken());
            const response = await fetch('/api/v1/campaign/excel/preview', {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ file_key: key }),
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: 'Preview failed' }));
                throw new Error(err.detail || 'Could not read Excel file');
            }
            const data: ExcelPreview = await response.json();
            setPreview(data);
            setNameCol(guessColumn(data.headers, NAME_GUESSES));
            setPhoneCol(guessColumn(data.headers, PHONE_GUESSES));
            setCityCol(guessColumn(data.headers, CITY_GUESSES));
        } catch (error) {
            logger.error('Error previewing Excel:', error);
            toast.error(error instanceof Error ? error.message : 'Could not read Excel file');
            setPreview(null);
        } finally {
            setLoadingPreview(false);
        }
    };

    const canProceedFromMapping =
        nameCol !== '' && phoneCol !== '' && cityCol !== '' &&
        new Set([nameCol, phoneCol, cityCol]).size === 3;

    const handleLaunch = async () => {
        if (!automationName.trim() || !selectedWorkflowId || !fileKey || !canProceedFromMapping) {
            toast.error('Please complete all steps first');
            return;
        }
        setIsLaunching(true);
        setLaunchError(null);
        try {
            const accessToken = await getAccessToken();

            // Validate max_concurrency against the effective org limit.
            const effectiveLimit = fromNumbersCount > 0
                ? Math.min(orgConcurrentLimit, fromNumbersCount)
                : orgConcurrentLimit;
            const maxConcurrencyValue = maxConcurrency ? parseInt(maxConcurrency) : null;
            if (maxConcurrencyValue !== null) {
                if (isNaN(maxConcurrencyValue) || maxConcurrencyValue < 1 || maxConcurrencyValue > 100) {
                    throw new Error('Max concurrent calls must be between 1 and 100');
                }
                if (maxConcurrencyValue > effectiveLimit) {
                    throw new Error(`Max concurrent calls cannot exceed ${effectiveLimit}`);
                }
            }

            const timezoneValue = getTimezoneValue(scheduleTimezone);
            const body = {
                name: automationName.trim(),
                workflow_id: parseInt(selectedWorkflowId),
                source_type: 'excel',
                source_id: fileKey,
                column_mapping: {
                    name_col: nameCol,
                    phone_col: phoneCol,
                    city_col: cityCol,
                },
                retry_config: {
                    enabled: retryEnabled,
                    max_retries: parseInt(maxRetries) || 2,
                    retry_delay_seconds: parseInt(retryDelaySeconds) || 120,
                    retry_on_busy: retryOnBusy,
                    retry_on_no_answer: retryOnNoAnswer,
                    retry_on_voicemail: retryOnVoicemail,
                },
                max_concurrency: maxConcurrencyValue,
                schedule_config: scheduleEnabled && timeSlots.length > 0
                    ? { enabled: true, timezone: timezoneValue, slots: timeSlots }
                    : undefined,
                circuit_breaker: {
                    enabled: circuitBreakerEnabled,
                    failure_threshold: (parseInt(circuitBreakerFailureThreshold) || 50) / 100,
                    window_seconds: parseInt(circuitBreakerWindowSeconds) || 120,
                    min_calls_in_window: parseInt(circuitBreakerMinCalls) || 5,
                },
            } as unknown as CreateCampaignRequest;
            const createResponse = await createCampaignApiV1CampaignCreatePost({
                body,
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (createResponse.error || !createResponse.data) {
                const detail = (createResponse.error as { detail?: string })?.detail
                    || 'Failed to create automation';
                throw new Error(detail);
            }
            const campaignId = createResponse.data.id;
            const startResponse = await startCampaignApiV1CampaignCampaignIdStartPost({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (startResponse.error) {
                const detail = (startResponse.error as { detail?: string })?.detail
                    || 'Automation created but failed to start';
                throw new Error(detail);
            }
            toast.success('Automation launched — the agent is now calling your list');
            router.push(`/campaigns/${campaignId}`);
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to launch automation';
            setLaunchError(message);
            toast.error(message);
        } finally {
            setIsLaunching(false);
        }
    };

    const steps = ['Agent', 'Upload Excel', 'Map Columns', 'Launch'];

    return (
        <div className="container mx-auto p-6 pb-12 space-y-6 max-w-3xl">
            <div>
                <h1 className="text-3xl font-bold mb-2">Automation</h1>
                <p className="text-muted-foreground">
                    Upload an Excel sheet, map your columns, and let the voice agent call everyone.
                </p>
            </div>

            {/* Stepper */}
            <div className="flex items-center gap-2">
                {steps.map((label, idx) => {
                    const num = (idx + 1) as Step;
                    const active = step === num;
                    const done = step > num;
                    return (
                        <div key={label} className="flex items-center gap-2 flex-1 last:flex-none">
                            <div
                                className={`h-8 w-8 rounded-full flex items-center justify-center text-sm font-medium shrink-0 ${
                                    done
                                        ? 'bg-green-500 text-white'
                                        : active
                                          ? 'bg-primary text-primary-foreground'
                                          : 'bg-muted text-muted-foreground'
                                }`}
                            >
                                {done ? <Check className="h-4 w-4" /> : num}
                            </div>
                            <span className={`text-sm hidden sm:inline ${active ? 'font-medium' : 'text-muted-foreground'}`}>
                                {label}
                            </span>
                            {idx < steps.length - 1 && <div className="flex-1 h-px bg-border mx-2" />}
                        </div>
                    );
                })}
            </div>

            {/* Step 1: Agent */}
            {step === 1 && (
                <Card>
                    <CardHeader>
                        <CardTitle>1. Choose your voice agent</CardTitle>
                        <CardDescription>Which agent should make these calls?</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-2">
                            <Label>Voice Agent</Label>
                            <Select value={selectedWorkflowId} onValueChange={setSelectedWorkflowId}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Select a voice agent" />
                                </SelectTrigger>
                                <SelectContent>
                                    {isLoadingWorkflows ? (
                                        <SelectItem value="loading" disabled>Loading...</SelectItem>
                                    ) : workflows.length === 0 ? (
                                        <SelectItem value="none" disabled>No voice agents found</SelectItem>
                                    ) : (
                                        workflows.map((w) => (
                                            <SelectItem key={w.id} value={w.id.toString()}>
                                                {w.name} (#{w.id})
                                            </SelectItem>
                                        ))
                                    )}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <Label>Automation Name</Label>
                            <Input
                                placeholder="e.g., Diwali offers outreach"
                                value={automationName}
                                onChange={(e) => setAutomationName(e.target.value)}
                                maxLength={255}
                            />
                        </div>
                        <Collapsible
                            open={showAdvancedSettings}
                            onOpenChange={setShowAdvancedSettings}
                            className="border rounded-lg"
                        >
                            <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 transition-colors">
                                <span className="font-medium">Advanced Settings</span>
                                {showAdvancedSettings ? (
                                    <ChevronDown className="h-4 w-4" />
                                ) : (
                                    <ChevronRight className="h-4 w-4" />
                                )}
                            </CollapsibleTrigger>
                            <CollapsibleContent className="px-4 pb-4">
                                <CampaignAdvancedSettings
                                    maxConcurrency={maxConcurrency}
                                    onMaxConcurrencyChange={setMaxConcurrency}
                                    effectiveLimit={fromNumbersCount > 0 ? Math.min(orgConcurrentLimit, fromNumbersCount) : orgConcurrentLimit}
                                    orgConcurrentLimit={orgConcurrentLimit}
                                    fromNumbersCount={fromNumbersCount}
                                    retryEnabled={retryEnabled}
                                    onRetryEnabledChange={setRetryEnabled}
                                    maxRetries={maxRetries}
                                    onMaxRetriesChange={setMaxRetries}
                                    retryDelaySeconds={retryDelaySeconds}
                                    onRetryDelaySecondsChange={setRetryDelaySeconds}
                                    retryOnBusy={retryOnBusy}
                                    onRetryOnBusyChange={setRetryOnBusy}
                                    retryOnNoAnswer={retryOnNoAnswer}
                                    onRetryOnNoAnswerChange={setRetryOnNoAnswer}
                                    retryOnVoicemail={retryOnVoicemail}
                                    onRetryOnVoicemailChange={setRetryOnVoicemail}
                                    scheduleEnabled={scheduleEnabled}
                                    onScheduleEnabledChange={setScheduleEnabled}
                                    scheduleTimezone={scheduleTimezone}
                                    onScheduleTimezoneChange={setScheduleTimezone}
                                    timeSlots={timeSlots}
                                    onTimeSlotsChange={setTimeSlots}
                                    circuitBreakerEnabled={circuitBreakerEnabled}
                                    onCircuitBreakerEnabledChange={setCircuitBreakerEnabled}
                                    circuitBreakerFailureThreshold={circuitBreakerFailureThreshold}
                                    onCircuitBreakerFailureThresholdChange={setCircuitBreakerFailureThreshold}
                                    circuitBreakerWindowSeconds={circuitBreakerWindowSeconds}
                                    onCircuitBreakerWindowSecondsChange={setCircuitBreakerWindowSeconds}
                                    circuitBreakerMinCalls={circuitBreakerMinCalls}
                                    onCircuitBreakerMinCallsChange={setCircuitBreakerMinCalls}
                                />
                            </CollapsibleContent>
                        </Collapsible>
                        <div className="flex justify-end">
                            <Button
                                onClick={() => setStep(2)}
                                disabled={!selectedWorkflowId || !automationName.trim()}
                            >
                                Continue <ArrowRight className="h-4 w-4 ml-2" />
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Step 2: Upload */}
            {step === 2 && (
                <Card>
                    <CardHeader>
                        <CardTitle>2. Upload your Excel sheet</CardTitle>
                        <CardDescription>
                            .xlsx or .xls with a header row. Must contain names, phone numbers, and cities. Max 10MB.
                            Tip: type phone numbers without the leading + (Excel treats + as a formula) — with country code, e.g. 918071579893. Spaces and dashes are fine.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".xlsx,.xls"
                            onChange={handleFileSelect}
                            className="hidden"
                        />
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploading || loadingPreview}
                        >
                            <Upload className="h-4 w-4 mr-2" />
                            {uploading ? 'Uploading...' : loadingPreview ? 'Reading...' : fileName ? 'Replace file' : 'Upload Excel File'}
                        </Button>
                        {fileName && !uploading && !loadingPreview && (
                            <p className="text-sm">
                                <span className="text-muted-foreground">Selected: </span>
                                <span className="text-primary">{fileName}</span>
                                {preview && (
                                    <span className="text-muted-foreground"> — {preview.total_rows} contacts found</span>
                                )}
                            </p>
                        )}
                        <div className="flex justify-between">
                            <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>
                            <Button onClick={() => setStep(3)} disabled={!preview}>
                                Continue <ArrowRight className="h-4 w-4 ml-2" />
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Step 3: Map columns */}
            {step === 3 && preview && (
                <Card>
                    <CardHeader>
                        <CardTitle>3. Map your columns</CardTitle>
                        <CardDescription>
                            Tell us which column holds each detail. The + prefix is added automatically — just map the digits.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="grid sm:grid-cols-3 gap-4">
                            <div className="space-y-2">
                                <Label>Name</Label>
                                <Select value={nameCol} onValueChange={setNameCol}>
                                    <SelectTrigger><SelectValue placeholder="Name column" /></SelectTrigger>
                                    <SelectContent>
                                        {preview.headers.map((h) => (
                                            <SelectItem key={h} value={h}>{h}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-2">
                                <Label>Phone Number</Label>
                                <Select value={phoneCol} onValueChange={setPhoneCol}>
                                    <SelectTrigger><SelectValue placeholder="Phone column" /></SelectTrigger>
                                    <SelectContent>
                                        {preview.headers.map((h) => (
                                            <SelectItem key={h} value={h}>{h}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-2">
                                <Label>City</Label>
                                <Select value={cityCol} onValueChange={setCityCol}>
                                    <SelectTrigger><SelectValue placeholder="City column" /></SelectTrigger>
                                    <SelectContent>
                                        {preview.headers.map((h) => (
                                            <SelectItem key={h} value={h}>{h}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        {!canProceedFromMapping && (
                            <p className="text-sm text-amber-600">
                                Map all three to three different columns to continue.
                            </p>
                        )}
                        <div className="border rounded-md overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="bg-muted/50 text-left">
                                        {preview.headers.map((h) => (
                                            <th key={h} className="font-medium px-3 py-2 whitespace-nowrap">
                                                {h}
                                                {h === nameCol && ' 👤'}
                                                {h === phoneCol && ' 📞'}
                                                {h === cityCol && ' 📍'}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {preview.sample_rows.map((row, i) => (
                                        <tr key={i} className="border-t">
                                            {preview.headers.map((h, j) => (
                                                <td key={j} className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                                                    {row[j] ?? ''}
                                                </td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <div className="flex justify-between">
                            <Button variant="ghost" onClick={() => { resetFileState(); setStep(2); }}>
                                Back
                            </Button>
                            <Button onClick={() => setStep(4)} disabled={!canProceedFromMapping}>
                                Continue <ArrowRight className="h-4 w-4 ml-2" />
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Step 4: Launch */}
            {step === 4 && (
                <Card>
                    <CardHeader>
                        <CardTitle>4. Review & launch</CardTitle>
                        <CardDescription>
                            The agent will call every mapped number using your selected workflow.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="rounded-md border p-4 space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Agent</span>
                                <span className="font-medium">
                                    {workflows.find((w) => w.id.toString() === selectedWorkflowId)?.name} (#{selectedWorkflowId})
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">File</span>
                                <span className="font-medium">{fileName} ({preview?.total_rows ?? 0} contacts)</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Name →</span>
                                <span className="font-medium">{nameCol}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Phone →</span>
                                <span className="font-medium">{phoneCol}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">City →</span>
                                <span className="font-medium">{cityCol}</span>
                            </div>
                        </div>
                        {launchError && (
                            <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive">
                                {launchError}
                            </div>
                        )}
                        <div className="flex justify-between">
                            <Button variant="ghost" onClick={() => setStep(3)} disabled={isLaunching}>
                                Back
                            </Button>
                            <Button onClick={handleLaunch} disabled={isLaunching}>
                                <PhoneCall className="h-4 w-4 mr-2" />
                                {isLaunching ? 'Launching...' : 'Launch Calls'}
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            Progress, retries, summaries, transcripts and the Reports CSV work exactly like campaigns.
                        </p>
                    </CardContent>
                </Card>
            )}
        </div>
    );
}
