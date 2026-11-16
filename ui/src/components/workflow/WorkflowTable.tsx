'use client';

import { Archive, Eye, RotateCcw, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import {
    deleteWorkflowEndpointApiV1WorkflowWorkflowIdDelete,
    updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut,
} from '@/client/sdk.gen';
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
import { Button } from '@/components/ui/button';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
interface Workflow {
    id: number;
    name: string;
    status: string;
    created_at: string;
    total_runs?: number | null;
}

interface WorkflowTableProps {
    workflows: Workflow[];
    showArchived: boolean;
}

export function WorkflowTable({ workflows, showArchived }: WorkflowTableProps) {
    const router = useRouter();
    const [isPending, startTransition] = useTransition();
    const [loadingWorkflowId, setLoadingWorkflowId] = useState<number | null>(null);
    const [workflowToDelete, setWorkflowToDelete] = useState<Workflow | null>(null);
    const [deletingWorkflowId, setDeletingWorkflowId] = useState<number | null>(null);

    const handleView = (id: number) => {
        router.push(`/workflow/${id}`);
    };

    const handleArchiveToggle = async (id: number, currentStatus: string) => {
        const newStatus = currentStatus === 'active' ? 'archived' : 'active';
        const action = currentStatus === 'active' ? 'Archive' : 'Restore';

        setLoadingWorkflowId(id);

        try {
            const response = await updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut({
                path: {
                    workflow_id: id,
                },
                body: {
                    status: newStatus,
                },
            });

            if (response.data) {
                toast.success(`Workflow ${action.toLowerCase()}d successfully`);
                startTransition(() => {
                    router.refresh();
                });
            }
        } catch (error) {
            console.error(`Error ${action.toLowerCase()}ing workflow:`, error);
            toast.error(`Failed to ${action.toLowerCase()} workflow`);
        } finally {
            setLoadingWorkflowId(null);
        }
    };

    const handleDelete = async () => {
        if (!workflowToDelete) return;
        const { id, name } = workflowToDelete;

        setDeletingWorkflowId(id);

        try {
            const response = await deleteWorkflowEndpointApiV1WorkflowWorkflowIdDelete({
                path: {
                    workflow_id: id,
                },
            });

            if (response.error) {
                const detail = (response.error as { detail?: string })?.detail
                    || 'Failed to delete workflow';
                throw new Error(detail);
            }

            toast.success(`Workflow "${name}" deleted`);
            setWorkflowToDelete(null);
            startTransition(() => {
                router.refresh();
            });
        } catch (error) {
            console.error('Error deleting workflow:', error);
            toast.error(error instanceof Error ? error.message : 'Failed to delete workflow');
        } finally {
            setDeletingWorkflowId(null);
        }
    };

    return (
        <>
            <div className="bg-card border rounded-lg overflow-hidden shadow-sm">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="font-semibold">ID</TableHead>
                        <TableHead className="font-semibold">Agent Name</TableHead>
                        <TableHead className="font-semibold">Created At</TableHead>
                        <TableHead className="font-semibold text-center">Total Runs</TableHead>
                        <TableHead className="font-semibold text-right">Actions</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {workflows.map((workflow) => (
                        <TableRow
                            key={workflow.id}
                            className={`hover:bg-accent transition-colors ${showArchived ? 'opacity-60' : ''}`}
                        >
                            <TableCell className="text-muted-foreground">
                                {workflow.id}
                            </TableCell>
                            <TableCell className="font-medium">
                                {workflow.name}
                            </TableCell>
                            <TableCell>
                                {new Date(workflow.created_at).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                })}
                            </TableCell>
                            <TableCell className="text-center">
                                <span className="inline-flex items-center justify-center min-w-[2rem] px-2 py-1 text-sm font-semibold bg-muted rounded-full">
                                    {workflow.total_runs || 0}
                                </span>
                            </TableCell>
                            <TableCell className="text-right">
                                <div className="flex justify-end gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleView(workflow.id)}
                                        className="flex items-center gap-2"
                                    >
                                        <Eye size={16} />
                                        View
                                    </Button>
                                    <Button
                                        variant={showArchived ? "default" : "outline"}
                                        size="sm"
                                        onClick={() => handleArchiveToggle(workflow.id, workflow.status)}
                                        disabled={loadingWorkflowId === workflow.id || isPending}
                                        className="flex items-center gap-2"
                                    >
                                        {loadingWorkflowId === workflow.id ? (
                                            <>
                                                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                                {showArchived ? 'Restoring...' : 'Archiving...'}
                                            </>
                                        ) : (
                                            <>
                                                {showArchived ? (
                                                    <>
                                                        <RotateCcw size={16} />
                                                        Restore
                                                    </>
                                                ) : (
                                                    <>
                                                        <Archive size={16} />
                                                        Archive
                                                    </>
                                                )}
                                            </>
                                        )}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setWorkflowToDelete(workflow)}
                                        disabled={deletingWorkflowId === workflow.id || isPending}
                                        className="flex items-center gap-2"
                                        aria-label={`Delete agent ${workflow.name}`}
                                    >
                                        {deletingWorkflowId === workflow.id ? (
                                            <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                        ) : (
                                            <Trash2 size={16} className="text-destructive" />
                                        )}
                                    </Button>
                                </div>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
            </div>
            <AlertDialog open={!!workflowToDelete} onOpenChange={(open) => !open && setWorkflowToDelete(null)}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete agent?</AlertDialogTitle>
                        <AlertDialogDescription>
                            {workflowToDelete ? `Delete "${workflowToDelete.name}"? This permanently removes the agent and its call history, including transcripts, summaries, and recordings. Its triggers, embed widgets, and scheduled callbacks are also removed. Automations using this agent must be deleted first. This action cannot be undone.` : ''}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleDelete}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                            {deletingWorkflowId ? 'Deleting...' : 'Delete'}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}
