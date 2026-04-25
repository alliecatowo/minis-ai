"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { ChatMessageBubble } from "@/components/chat-message";
import { LogIn } from "lucide-react";
import { type ChatMessageWithId } from "@/hooks/useMiniChat";

const STARTERS = [
  "What would you block in a risky auth migration?",
  "How would you review a retry-policy design doc?",
  "What patterns do you usually ask people to fix before review?",
  "How strict would you be with a first PR from a new teammate?",
];

interface ChatMessagesProps {
  messages: ChatMessageWithId[];
  isStreaming: boolean;
  toolActivity: string | null;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  mini: {
    username: string;
    display_name?: string;
    avatar_url?: string;
  };
  isAuthenticated: boolean;
  isPromoMini: boolean;
  onSendMessage: (text: string) => void;
  onLogin: () => void;
}

export function ChatMessages({
  messages,
  isStreaming,
  toolActivity,
  messagesEndRef,
  scrollContainerRef,
  mini,
  isAuthenticated,
  isPromoMini,
  onSendMessage,
  onLogin,
}: ChatMessagesProps) {
  return (
    <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4 pb-6">
      <div className="mx-auto max-w-3xl space-y-6">
        {messages.length === 0 && (
          <div className="flex min-h-[50vh] flex-col items-center justify-center space-y-6">
            <div className="text-center">
              <Avatar className="mx-auto mb-3 h-12 w-12">
                <AvatarImage src={mini.avatar_url} alt={mini.username} />
                <AvatarFallback className="font-mono text-sm">
                  {mini.username.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <p className="text-sm text-muted-foreground">
                Start a review pre-flight with{" "}
                <span className="font-mono font-medium text-foreground">
                  {mini.display_name || mini.username}
                </span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground/60">
                Ask what they would flag, soften, or approve before the human review starts
              </p>
            </div>
            {isAuthenticated || isPromoMini ? (
              <div className="grid w-full max-w-sm gap-2">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    onClick={() => onSendMessage(s)}
                    className="rounded-lg border border-border/50 px-4 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-border hover:bg-secondary hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-xl border border-border/50 bg-secondary/30 px-8 py-6">
                <LogIn className="h-5 w-5 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  Sign in to chat with{" "}
                  <span className="font-mono font-medium text-foreground">
                    @{mini.username}
                  </span>
                </p>
                <Button onClick={onLogin} size="sm">
                  Sign In with GitHub
                </Button>
              </div>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={msg._id} data-message={msg._id}>
            <ChatMessageBubble
              message={msg}
              isStreaming={
                isStreaming &&
                i === messages.length - 1 &&
                msg.role === "assistant"
              }
              toolActivity={
                isStreaming &&
                i === messages.length - 1 &&
                msg.role === "assistant"
                  ? toolActivity
                  : undefined
              }
            />
          </div>
        ))}

        {isStreaming &&
          messages.length > 0 &&
          messages[messages.length - 1].role === "user" && (
            <div className="flex gap-3 px-4 py-3">
              <Avatar className="h-8 w-8 shrink-0">
                <AvatarImage src={mini.avatar_url} />
                <AvatarFallback className="text-xs">
                  {mini.username.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <span className="animate-pulse">Thinking</span>
                <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
              </div>
            </div>
          )}

        <div ref={messagesEndRef} className="h-2" />
      </div>
    </div>
  );
}
