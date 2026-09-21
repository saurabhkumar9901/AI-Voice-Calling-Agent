"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";

interface WhatsAppForm {
  waba_id: string;
  phone_number_id: string;
  access_token: string;
  app_secret: string;
  verify_token: string;
  display_phone_number: string;
  linked_workflow_id?: number;
}

export default function WhatsAppConfigPage() {
  const { getAccessToken } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [isFetching, setIsFetching] = useState(true);
  const [hasExisting, setHasExisting] = useState(false);
  const { register, handleSubmit, setValue, watch } = useForm<WhatsAppForm>({ defaultValues: { waba_id: "", phone_number_id: "", access_token: "", app_secret: "", verify_token: "", display_phone_number: "" } });

  useEffect(() => {
    const fetchConfig = async () => {
      setIsFetching(true);
      try {
        const token = await getAccessToken();
        const res = await fetch("/api/v1/organizations/whatsapp-config", { headers: { Authorization: `Bearer ${token}` } });
        if (res.ok) {
          const data = await res.json();
          setHasExisting(true);
          setValue("waba_id", data.waba_id || "");
          setValue("phone_number_id", data.phone_number_id || "");
          setValue("access_token", data.access_token || "");
          setValue("app_secret", data.app_secret || "");
          setValue("verify_token", data.verify_token || "");
          setValue("display_phone_number", data.display_phone_number || "");
          if (data.linked_workflow_id) setValue("linked_workflow_id", data.linked_workflow_id);
        }
      } catch (e) { console.error(e); } finally { setIsFetching(false); }
    };
    fetchConfig();
  }, [getAccessToken, setValue]);

  const onSubmit = async (data: WhatsAppForm) => {
    setIsLoading(true);
    try {
      const token = await getAccessToken();
      const body: any = { provider: "meta", waba_id: data.waba_id, phone_number_id: data.phone_number_id, access_token: data.access_token, app_secret: data.app_secret, verify_token: data.verify_token, display_phone_number: data.display_phone_number || undefined, linked_workflow_id: data.linked_workflow_id || undefined, from_numbers: [] };
      const res = await fetch("/api/v1/organizations/whatsapp-config", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(await res.text());
      toast.success("WhatsApp configuration saved");
      window.location.href = "/whatsapp";
    } catch (e: any) { toast.error(e.message || "Failed"); } finally { setIsLoading(false); }
  };

  const onDelete = async () => {
    if (!confirm("Delete WhatsApp configuration?")) return;
    const token = await getAccessToken();
    const res = await fetch("/api/v1/organizations/whatsapp-config", { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) { toast.success("Deleted"); window.location.reload(); } else toast.error("Delete failed");
  };

  if (isFetching) return <div className="container mx-auto px-4 py-8"><p className="text-muted-foreground">Loading...</p><div className="animate-spin h-8 w-8 border-b-2 border-primary rounded-full mt-4" /></div>;

  return (
    <div className="container mx-auto px-4 py-8 max-w-3xl">
      <h1 className="text-3xl font-bold mb-2">WhatsApp Configuration (Meta)</h1>
      <p className="text-muted-foreground mb-6">Org-level, text-only LLM. Isolated workflow template. Callback: <code>/api/v1/whatsapp/webhook</code></p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle>Setup Guide</CardTitle><CardDescription>Meta App → WhatsApp → API Setup → copy WABA ID, Phone Number ID, Access Token (System User permanent). App Settings → Basic → App Secret. Webhook: https://your-backend/api/v1/whatsapp/webhook?hub.verify_token=YOUR_TOKEN . Subscribe to <code>messages</code>.</CardDescription></CardHeader>
          <CardContent className="text-sm space-y-2">
            <p>Verify: <code>GET /api/v1/whatsapp/webhook?hub.mode=subscribe&hub.challenge=...&hub.verify_token=...</code></p>
            <p>Inbound: <code>POST /api/v1/whatsapp/webhook</code> with <code>X-Hub-Signature-256</code></p>
            <p>Storage: <code>gathered_context.whatsapp_history</code> + <code>logs.whatsapp_events</code> → visible in separate tab <code>/whatsapp</code></p>
            <p>LLM: uses your Models config (<code>gemini-3.5-flash-lite</code> etc) via <code>create_llm_service</code>, workflow prompt is system prompt, history last 10.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Credentials</CardTitle><CardDescription>{hasExisting ? "Leave masked (••••) to keep existing" : "Enter Meta credentials"}</CardDescription></CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-2"><Label>WABA ID</Label><Input placeholder="123456789..." {...register("waba_id", { required: true })} /></div>
              <div className="space-y-2"><Label>Phone Number ID</Label><Input placeholder="987654321..." {...register("phone_number_id", { required: true })} /></div>
              <div className="space-y-2"><Label>Access Token (System User)</Label><Input type="password" placeholder={hasExisting ? "•••• masked" : "EAA..."} {...register("access_token", { required: !hasExisting })} /></div>
              <div className="space-y-2"><Label>App Secret</Label><Input type="password" placeholder={hasExisting ? "•••• masked" : "app_secret"} {...register("app_secret", { required: !hasExisting })} /></div>
              <div className="space-y-2"><Label>Verify Token (you choose)</Label><Input placeholder="my_verify_token_123" {...register("verify_token", { required: !hasExisting })} /></div>
              <div className="space-y-2"><Label>Display Phone Number (optional)</Label><Input placeholder="+15551234567" {...register("display_phone_number")} /></div>
              <div className="space-y-2"><Label>Linked Workflow ID (isolated text template, optional)</Label><Input type="number" placeholder="e.g. 42" {...register("linked_workflow_id", { valueAsNumber: true })} /><p className="text-xs text-muted-foreground">If empty, first active workflow in org is used. Create a workflow with a WhatsApp/start node prompt.</p></div>
              <Button type="submit" className="w-full" disabled={isLoading}>{isLoading ? "Saving..." : "Save WhatsApp Config"}</Button>
              {hasExisting && <Button type="button" variant="destructive" className="w-full" onClick={onDelete}>Delete Config</Button>}
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
