"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { AlertCircle, ChevronLeft, Lock, PanelLeftClose, PanelLeftOpen, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { getMiniByUsername, deleteMini, getConversations, type Mini } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMiniChat } from "@/hooks/useMiniChat";
import { useConversations } from "@/hooks/useConversations";
import { ChatMessages } from "@/components/chat/ChatMessages";
import { ChatInput } from "@/components/chat/ChatInput";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { MiniProfile } from "@/components/chat/MiniProfile";

const PROMO_MINI = process.env.NEXT_PUBLIC_PROMO_MINI || "alliecatowo";

export default function MiniProfilePage() {
  const params = useParams();
  const router = useRouter();
  const username = params.username as string;
  const { user, login } = useAuth();

  const [mini, setMini] = useState<Mini | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chatSidebarOpen, setChatSidebarOpen] = useState(false);

  const isOwner = user?.id != null && user.id === mini?.owner_id;
  const isPromoMini = username.toLowerCase() === PROMO_MINI.toLowerCase();

  // Conversations hook
  const {
    conversations,
    setConversations,
    conversationId,
    setConversationId,
    loadingConversation,
    conversationsSupported,
    refreshConversations,
    loadConversation,
    handleDeleteConversation,
  } = useConversations({
    miniId: mini?.id,
    isAuthenticated: !!user,
  });

  // Chat hook
  const {
    messages,
    setMessages,
    input,
    setInput,
    isStreaming,
    toolActivity,
    textareaRef,
    messagesEndRef,
    scrollContainerRef,
    sendMessage,
    anonMessageCount,
    clearMessages,
  } = useMiniChat({
    miniId: mini?.id,
    isAuthenticated: !!user,
    conversationId,
    onConversationCreated: useCallback((id: string) => {
      setConversationId(id);
      refreshConversations();
    }, [setConversationId, refreshConversations]),
  });

  const anonLimitReached = !user && anonMessageCount >= 5;

  // Load mini
  useEffect(() => {
    getMiniByUsername(username)
      .then(setMini)
      .catch(() => setError("Could not load this mini."))
      .finally(() => setLoading(false));
  }, [username]);

  // Auto-scroll to bottom on new messages.
  // Uses scrollContainerRef instead of scrollIntoView to avoid propagating
  // scroll events to the page body (which is scrollable due to the footer),
  // which would cause the sticky nav to overlap the top of the chat area
  // and visually cut off the first line of streamed responses (ALLIE-380).
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages, scrollContainerRef]);

  // Auto-resize textarea as content grows
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [input, textareaRef]);

  // Load conversations when mini is available and user is logged in
  useEffect(() => {
    if (!mini || !user || !conversationsSupported) return;
    getConversations(mini.id).then((convos) => {
      setConversations(convos);
    });
  }, [mini, user, conversationsSupported, setConversations]);

  const handleLoadConversation = useCallback(async (convoId: string) => {
    const msgs = await loadConversation(convoId);
    if (msgs) {
      setMessages(msgs);
      setChatSidebarOpen(false);
    }
  }, [loadConversation, setMessages]);

  const handleDeleteAndClear = useCallback(async (convoId: string, e: React.MouseEvent) => {
    await handleDeleteConversation(convoId, e);
    if (conversationId === convoId) {
      clearMessages();
    }
  }, [handleDeleteConversation, conversationId, clearMessages]);

  const startNewChat = useCallback(() => {
    setConversationId(null);
    clearMessages();
    setChatSidebarOpen(false);
    textareaRef.current?.focus();
  }, [setConversationId, clearMessages, textareaRef]);

  const clearConversation = useCallback(() => {
    setConversationId(null);
    clearMessages();
    textareaRef.current?.focus();
  }, [setConversationId, clearMessages, textareaRef]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteMini(mini!.id);
      router.push("/gallery");
    } catch {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-4 lg:flex-row">
        <div className="w-full space-y-4 lg:w-80">
          <div className="flex items-start gap-4">
            <Skeleton className="h-16 w-16 shrink-0 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-20" />
            </div>
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Separator />
          <Skeleton className="h-[180px] w-full rounded-lg" />
        </div>
        <div className="flex-1">
          <Skeleton className="h-[60vh] w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !mini || mini.status === "failed") {
    const isFailed = mini?.status === "failed";
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="w-full max-w-md rounded-xl border border-border/50 bg-card p-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
            {isFailed ? (
              <AlertCircle className="h-6 w-6 text-destructive" />
            ) : (
              <Lock className="h-6 w-6 text-muted-foreground" />
            )}
          </div>
          <h2 className="mb-2 text-lg font-semibold">
            {isFailed ? "Mini Creation Failed" : "Mini Not Available"}
          </h2>
          <p className="mb-6 text-sm text-muted-foreground">
            {isFailed
              ? `Something went wrong while creating @${username}'s mini. You can try creating it again.`
              : `This mini doesn't exist or is private. @${username} may not have been cloned yet, or the owner has restricted access.`}
          </p>
          <div className="flex flex-col items-center gap-3">
            <Link href={`/create?username=${username}`}>
              <Button variant="default" className="gap-2">
                <Sparkles className="h-4 w-4" />
                {isFailed ? "Retry Creation" : "Create This Mini"}
              </Button>
            </Link>
            <Link
              href="/gallery"
              className="text-sm text-muted-foreground underline transition-colors hover:text-foreground"
            >
              Back to Gallery
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-6xl flex-col lg:flex-row">
      {/* Mobile sidebar toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="flex items-center gap-2 border-b px-4 py-3 text-sm text-muted-foreground lg:hidden"
      >
        <ChevronLeft
          className={`h-4 w-4 transition-transform ${sidebarOpen ? "rotate-90" : "-rotate-90"}`}
        />
        {sidebarOpen ? "Hide profile" : "Show profile"}
      </button>

      {/* Left sidebar — mini profile */}
      <aside
        className={`${
          sidebarOpen ? "block" : "hidden"
        } w-full shrink-0 overflow-y-auto border-b p-6 lg:block lg:w-80 lg:border-b-0 lg:border-r`}
      >
        <MiniProfile
          mini={mini}
          isOwner={isOwner}
          onDelete={handleDelete}
          deleting={deleting}
        />
      </aside>

      {/* Chat area */}
      <div className="flex flex-1 flex-col">
        {/* Chat header */}
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-2">
            {user && conversationsSupported && (
              <button
                onClick={() => setChatSidebarOpen(!chatSidebarOpen)}
                className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                title={chatSidebarOpen ? "Hide conversations" : "Show conversations"}
              >
                {chatSidebarOpen ? (
                  <PanelLeftClose className="h-4 w-4" />
                ) : (
                  <PanelLeftOpen className="h-4 w-4" />
                )}
              </button>
            )}
            <span className="text-xs text-muted-foreground">
              {messages.length > 0
                ? `${messages.length} message${messages.length !== 1 ? "s" : ""}`
                : `Chat with @${mini.username}`}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                onClick={clearConversation}
                disabled={isStreaming}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
              >
                <Trash2 className="h-3 w-3" />
                Clear
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Conversation history sidebar */}
          {user && conversationsSupported && chatSidebarOpen && (
            <ChatSidebar
              conversations={conversations}
              conversationId={conversationId}
              loadingConversation={loadingConversation}
              onLoadConversation={handleLoadConversation}
              onDeleteConversation={handleDeleteAndClear}
              onNewChat={startNewChat}
            />
          )}

          {/* Messages + Input column */}
          <div className="flex flex-1 flex-col overflow-hidden">
            <ChatMessages
              messages={messages}
              isStreaming={isStreaming}
              toolActivity={toolActivity}
              messagesEndRef={messagesEndRef}
              scrollContainerRef={scrollContainerRef}
              mini={mini}
              isAuthenticated={!!user}
              isPromoMini={isPromoMini}
              onSendMessage={sendMessage}
              onLogin={login}
            />
            <ChatInput
              input={input}
              setInput={setInput}
              isStreaming={isStreaming}
              isAuthenticated={!!user}
              isPromoMini={isPromoMini}
              anonMessageCount={anonMessageCount}
              anonLimitReached={anonLimitReached}
              miniUsername={mini.username}
              textareaRef={textareaRef}
              onSend={sendMessage}
              onLogin={login}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
