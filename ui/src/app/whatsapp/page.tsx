"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MessageCircle, Settings, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export default function WhatsAppPage() {
  const [activeTab, setActiveTab] = useState("chats");
  const [chats, setChats] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedChat, setSelectedChat] = useState<any>(null);
  const [replyText, setReplyText] = useState("");

  const fetchChats = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/v1/whatsapp/chats", { headers: { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` } });
      // Fallback: try direct backend via client sdk would be better; for MVP use fetch with current host
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      setChats(data.chats || []);
    } catch {
      setChats([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "chats") fetchChats();
  }, [activeTab]);

  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2"><MessageCircle className="h-7 w-7" /> WhatsApp (Text-only LLM)</h1>
          <p className="text-muted-foreground">Isolated text-only workflow • Org-level Meta config • Chats stored in workflow runs (gathered_context.whatsapp_history + logs.whatsapp_events)</p>
        </div>
        <Link href="/whatsapp-configurations"><Button variant="outline"><Settings className="h-4 w-4 mr-2" /> Configure</Button></Link>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-3 max-w-md">
          <TabsTrigger value="chats">Chats</TabsTrigger>
          <TabsTrigger value="template">Template</TabsTrigger>
          <TabsTrigger value="setup">Setup</TabsTrigger>
        </TabsList>

        <TabsContent value="chats" className="mt-6">
          <div className="grid grid-cols-3 gap-4">
            <Card className="col-span-1">
              <CardHeader><CardTitle>Conversations</CardTitle><CardDescription>WorkflowRun mode=whatsapp • per wa_id</CardDescription></CardHeader>
              <CardContent className="space-y-2 max-h-[60vh] overflow-auto">
                {loading ? <p className="text-sm text-muted-foreground">Loading...</p> : chats.length === 0 ? <p className="text-sm text-muted-foreground">No chats yet. Send a WhatsApp message to your WABA number.</p> : chats.map((c) => (
                  <div key={c.id} onClick={() => setSelectedChat(c)} className={`p-3 rounded border cursor-pointer ${selectedChat?.id===c.id ? "bg-accent" : "hover:bg-muted"}`}>
                    <div className="font-medium text-sm">{c.contact_name || c.wa_id || "Unknown"} <span className="text-xs text-muted-foreground">#{c.id}</span></div>
                    <div className="text-xs text-muted-foreground truncate">{c.history?.slice(-1)[0]?.content || c.events?.slice(-1)[0]?.text || "—"}</div>
                    <div className="text-xs text-muted-foreground">w{c.workflow_id} • {new Date(c.created_at).toLocaleString()}</div>
                  </div>
                ))}
                <Button size="sm" variant="ghost" onClick={fetchChats} className="w-full">Refresh</Button>
              </CardContent>
            </Card>
            <Card className="col-span-2">
              <CardHeader><CardTitle>{selectedChat ? `${selectedChat.contact_name || selectedChat.wa_id} • Run #${selectedChat.id}` : "Select a chat"}</CardTitle><CardDescription>History = gathered_context.whatsapp_history, Events = logs.whatsapp_events, Cost = usage_info llm bucket</CardDescription></CardHeader>
              <CardContent>
                {!selectedChat ? <p className="text-sm text-muted-foreground">Pick a conversation on the left. Use operator send below for handoff.</p> : (
                  <>
                    <div className="space-y-2 max-h-[40vh] overflow-auto border rounded p-3 mb-3">
                      {(selectedChat.history || []).map((h: any, i: number) => (
                        <div key={i} className={h.role==="assistant" ? "text-right" : "text-left"}>
                          <span className={`inline-block px-3 py-1 rounded text-sm ${h.role==="assistant" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>{h.content}</span>
                        </div>
                      ))}
                    </div>
                    <div className="text-xs text-muted-foreground mb-2">Cost: {JSON.stringify(selectedChat.cost_info?.cost_breakdown || selectedChat.usage_info || {})}</div>
                    <div className="flex gap-2">
                      <Input placeholder="Operator reply..." value={replyText} onChange={(e)=>setReplyText(e.target.value)} />
                      <Button onClick={async()=>{
                        if (!replyText.trim()) return;
                        await fetch(`/api/v1/whatsapp/chats/${selectedChat.id}/send`, { method:"POST", headers:{ "Content-Type":"application/json", Authorization:`Bearer ${localStorage.getItem("access_token")||""}` }, body:JSON.stringify({ wa_id: selectedChat.wa_id, text: replyText }) });
                        setReplyText(""); fetchChats();
                      }}><Send className="h-4 w-4 mr-1"/>Send</Button>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="template">
          <Card>
            <CardHeader><CardTitle>Isolated Text-Only Workflow Template</CardTitle><CardDescription>Create a workflow with a single “WhatsApp” start node containing your system prompt. Link it in WhatsApp Configuration → linked_workflow_id. Inbound text runs that workflow’s prompt + history tail (last 10) via create_llm_service (your Models config gemini-3.5-flash-lite etc) - no STT/TTS.</CardDescription></CardHeader>
            <CardContent className="text-sm space-y-2">
              <p>Fallback if no linked workflow: first active workflow in org, or generic prompt “You are a helpful WhatsApp assistant...”</p>
              <p>See <code>api/services/whatsapp/whatsapp_pipeline.py:_compose_reply_text → WorkflowGraph nodes[].data.prompt</code> and <code>create_llm_service</code>.</p>
              <Link href="/workflow"><Button>Create / Link Workflow</Button></Link>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="setup">
          <Card>
            <CardHeader><CardTitle>Setup (Meta)</CardTitle><CardDescription>Org-level: WABA ID, Phone Number ID, Access Token, App Secret, Verify Token. Webhook: GET /api/v1/whatsapp/webhook?hub.mode=subscribe&hub.challenge=&hub.verify_token=  + POST /api/v1/whatsapp/webhook (X-Hub-Signature-256). Add to Meta Dashboard → WhatsApp → Configuration → Webhook Callback URL.</CardDescription></CardHeader>
            <CardContent className="text-sm space-y-1">
              <p>Verify: <code>GET /api/v1/whatsapp/webhook?hub.verify_token={"{verify_token}"}&hub.challenge=123&hub.mode=subscribe</code></p>
              <p>Inbound: <code>POST /api/v1/whatsapp/webhook</code> (support <code>?organization_id=</code> query for multi-tenant debug)</p>
              <p>Config API: <code>GET/POST/DELETE /api/v1/organizations/whatsapp-config</code> (masked, org-level)</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
