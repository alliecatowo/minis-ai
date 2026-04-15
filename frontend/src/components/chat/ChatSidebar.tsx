"use client";

import { Clock, Plus, Trash2 } from "lucide-react";
import { type Conversation } from "@/lib/api";

interface ChatSidebarProps {
  conversations: Conversation[];
  conversationId: string | null;
  loadingConversation: boolean;
  onLoadConversation: (convoId: string) => void;
  onDeleteConversation: (convoId: string, e: React.MouseEvent) => void;
  onNewChat: () => void;
}

export function ChatSidebar({
  conversations,
  conversationId,
  loadingConversation,
  onLoadConversation,
  onDeleteConversation,
  onNewChat,
}: ChatSidebarProps) {
  return (
    <div className="flex w-[280px] shrink-0 flex-col border-r bg-secondary/20">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Conversations
        </span>
        <button
          onClick={onNewChat}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          title="New chat"
        >
          <Plus className="h-3 w-3" />
          New
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-4 py-8 text-center">
            <Clock className="mb-2 h-5 w-5 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground/60">
              No previous conversations
            </p>
          </div>
        ) : (
          <div className="py-1">
            {conversations.map((convo) => (
              <button
                key={convo.id}
                onClick={() => onLoadConversation(convo.id)}
                disabled={loadingConversation}
                className={`group flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-secondary/60 ${
                  conversationId === convo.id
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm leading-tight">
                    {convo.title || "Untitled"}
                  </p>
                  <p className="text-[11px] text-muted-foreground/60">
                    {new Date(convo.updated_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                    })}
                    {convo.message_count > 0 && (
                      <span> &middot; {convo.message_count} msgs</span>
                    )}
                  </p>
                </div>
                <button
                  onClick={(e) => onDeleteConversation(convo.id, e)}
                  className="shrink-0 rounded p-1 text-muted-foreground/40 opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                  title="Delete conversation"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
