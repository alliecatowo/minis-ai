"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, LogIn } from "lucide-react";

const ANON_MESSAGE_LIMIT = 5;

interface ChatInputProps {
  input: string;
  setInput: (value: string) => void;
  isStreaming: boolean;
  isAuthenticated: boolean;
  isPromoMini: boolean;
  anonMessageCount: number;
  anonLimitReached: boolean;
  miniUsername: string;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onSend: (text: string) => void;
  onLogin: () => void;
}

export function ChatInput({
  input,
  setInput,
  isStreaming,
  isAuthenticated,
  isPromoMini,
  anonMessageCount,
  anonLimitReached,
  miniUsername,
  textareaRef,
  onSend,
  onLogin,
}: ChatInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend(input);
    }
  };

  if (isAuthenticated || (isPromoMini && !anonLimitReached)) {
    return (
      <div className="border-t">
        <div className="p-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message @${miniUsername}... (Shift+Enter for newline)`}
              className="min-h-[44px] max-h-32 resize-none font-mono text-sm"
              rows={1}
              disabled={isStreaming}
            />
            <Button
              size="icon"
              onClick={() => onSend(input)}
              disabled={!input.trim() || isStreaming}
              className="h-[44px] w-[44px] shrink-0"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
          {!isAuthenticated && isPromoMini && (
            <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-muted-foreground">
              {ANON_MESSAGE_LIMIT - anonMessageCount} free message
              {ANON_MESSAGE_LIMIT - anonMessageCount !== 1 ? "s" : ""} remaining &mdash;{" "}
              <button onClick={onLogin} className="underline hover:text-foreground">
                sign in
              </button>{" "}
              for unlimited chat
            </p>
          )}
        </div>
      </div>
    );
  }

  if (anonLimitReached) {
    return (
      <div className="border-t">
        <div className="flex flex-col items-center gap-2 p-4">
          <p className="text-sm font-medium">Sign in to keep chatting!</p>
          <p className="text-xs text-muted-foreground">
            You&apos;ve used your {ANON_MESSAGE_LIMIT} free messages
          </p>
          <Button onClick={onLogin} size="sm" className="mt-1 gap-1.5">
            <LogIn className="h-3.5 w-3.5" />
            Sign In with GitHub
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="border-t">
      <div className="flex items-center justify-center gap-3 p-4">
        <p className="text-sm text-muted-foreground">
          Sign in to chat with @{miniUsername}
        </p>
        <Button onClick={onLogin} size="sm" variant="outline" className="gap-1.5">
          <LogIn className="h-3.5 w-3.5" />
          Sign In
        </Button>
      </div>
    </div>
  );
}
