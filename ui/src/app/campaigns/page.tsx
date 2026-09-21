"use client";

import { Plus, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { getCampaignsApiV1CampaignGet } from '@/client/sdk.gen';
import type { CampaignsResponse } from '@/client/types.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip';
import { useAuth } from '@/lib/auth';

export default function CampaignsPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const router = useRouter();

    const [campaignsData, setCampaignsData] = useState<CampaignsResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [campaignToDelete, setCampaignToDelete] = useState<{ id: number; name: string } | null>(null);
    const hasFetched = useRef(false);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const fetchCampaigns = async () => {
        setIsLoading(true);
        try {
            const accessToken = await getAccessToken();
            const response = await getCampaignsApiV1CampaignGet({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                }
            });

            if (response.data) {
                setCampaignsData(response.data);
            }
        } catch (error) {
            console.error('Failed to fetch campaigns:', error);
        } finally {
            setIsLoading(false);
        }
    };

    // Fetch campaigns once when user is ready
    useEffect(() => {
        if (loading || !user || hasFetched.current) {
            return;
        }
        hasFetched.current = true;
        fetchCampaigns();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [loading, user, getAccessToken]);

    const handleRowClick = (campaignId: number) => {
        router.push(`/campaigns/${campaignId}`);
    };

    const handleCreateCampaign = () => {
        router.push('/campaigns/new');
    };

    const handleDeleteCampaign = async () => {
        if (!campaignToDelete) return;
        const { id: campaignId } = campaignToDelete;
        setDeletingId(campaignId);
        try {
            const accessToken = await getAccessToken();
            const response = await fetch(`/api/v1/campaign/${campaignId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({ detail: 'Delete failed' }));
                throw new Error(err.detail || 'Failed to delete campaign');
            }
            toast.success('Campaign deleted');
            setCampaignToDelete(null);
            await fetchCampaigns();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Failed to delete campaign');
        } finally {
            setDeletingId(null);
        }
    };

    const isDeletable = (state: string) => !['running', 'syncing'].includes(state);

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString();
    };

    const getStateBadgeVariant = (state: string) => {
        switch (state) {
            case 'created':
                return 'secondary';
            case 'running':
                return 'default';
            case 'paused':
                return 'outline';
            case 'completed':
                return 'secondary';
            case 'failed':
                return 'destructive';
            default:
                return 'secondary';
        }
    };

    return (
        <div className="container mx-auto p-6 space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold mb-2">Campaigns</h1>
                    <p>Manage your bulk workflow execution campaigns</p>
                </div>
                    <Button onClick={handleCreateCampaign}>
                        <Plus className="h-4 w-4 mr-2" />
                        Create Campaign
                    </Button>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle>All Campaigns</CardTitle>
                        <CardDescription>
                            View and manage your campaigns
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        {isLoading ? (
                            <div className="animate-pulse space-y-3">
                                {[...Array(5)].map((_, i) => (
                                    <div key={i} className="h-12 bg-muted rounded"></div>
                                ))}
                            </div>
                        ) : campaignsData && campaignsData.campaigns.length > 0 ? (
                            <div className="overflow-x-auto">
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>ID</TableHead>
                                            <TableHead>Name</TableHead>
                                            <TableHead>Workflow</TableHead>
                                            <TableHead>State</TableHead>
                                            <TableHead>Created</TableHead>
                                            <TableHead className="text-right">Action</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {campaignsData.campaigns.map((campaign) => (
                                            <TableRow
                                                key={campaign.id}
                                                className="cursor-pointer hover:bg-muted/50"
                                                onClick={() => handleRowClick(campaign.id)}
                                            >
                                                <TableCell>{campaign.id}</TableCell>
                                                <TableCell className="font-medium">{campaign.name}</TableCell>
                                                <TableCell>{campaign.workflow_name}</TableCell>
                                                <TableCell>
                                                    <Badge variant={getStateBadgeVariant(campaign.state)}>
                                                        {campaign.state}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell>{formatDate(campaign.created_at)}</TableCell>
                                                <TableCell className="text-right">
                                                    <div className="flex justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => handleRowClick(campaign.id)}
                                                        >
                                                            View
                                                        </Button>
                                                        <TooltipProvider>
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <span className="inline-flex">
                                                                        <Button
                                                                            variant="outline"
                                                                            size="sm"
                                                                            disabled={!isDeletable(campaign.state) || deletingId === campaign.id}
                                                                            onClick={() => setCampaignToDelete({ id: campaign.id, name: campaign.name })}
                                                                            aria-label={`Delete campaign ${campaign.name}`}
                                                                        >
                                                                            <Trash2 className="h-4 w-4 text-destructive" />
                                                                        </Button>
                                                                    </span>
                                                                </TooltipTrigger>
                                                                {!isDeletable(campaign.state) && (
                                                                    <TooltipContent>
                                                                        Pause the campaign before deleting it
                                                                    </TooltipContent>
                                                                )}
                                                            </Tooltip>
                                                        </TooltipProvider>
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        ) : (
                            <div className="text-center py-8">
                                <p className="mb-4">No campaigns found</p>
                                <Button onClick={handleCreateCampaign} variant="outline">
                                    <Plus className="h-4 w-4 mr-2" />
                                    Create your first campaign
                                </Button>
                            </div>
                        )}
                    </CardContent>
                </Card>
                <AlertDialog open={!!campaignToDelete} onOpenChange={(open) => !open && setCampaignToDelete(null)}>
                    <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Delete campaign?</AlertDialogTitle>
                            <AlertDialogDescription>
                                {campaignToDelete ? `Delete "${campaignToDelete.name}"? Its queued calls will be removed, but completed call history is kept. This action cannot be undone.` : ''}
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction
                                onClick={handleDeleteCampaign}
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                                {deletingId ? 'Deleting...' : 'Delete'}
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
        </div>
    );
}
