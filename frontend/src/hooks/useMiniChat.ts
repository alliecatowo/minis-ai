"use client";

import { useState, useRef, useCallback } from "react";
import { flushSync } from "react-dom";
import {
  fetchChatStream,
  type ChatMessage,
} from "@/lib/api";

export type ChatMessageWithId = ChatMessage & { _id: string };

let _msgCounter = 0;
export function nextMsgId() {
  return `msg-${++_msgCounter}`;
}

interface UseMiniChatOptions {
  miniId: string | undefined;
  isAuthenticated: boolean;
  conversationId: string | null;
  onConversationCreated: (conversationId: string) => void;
}

interface UseMiniChatReturn {
  messages: ChatMessageWithId[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessageWithId[]>>;
  input: string;
  setInput: React.Dispatch<React.SetStateAction<string>>;
  isStreaming: boolean;
  toolActivity: string | null;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  sendMessage: (text: string) => Promise<void>;
  anonMessageCount: number;
  clearMessages: () => void;
}

export function useMiniChat({
  miniId,
  isAuthenticated,
  conversationId,
  onConversationCreated,
}: UseMiniChatOptions): UseMiniChatReturn {
  const [messages, setMessages] = useState<ChatMessageWithId[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [, setPendingToolCalls] = useState<Array<{ tool: string; args: Record<string, string>; result?: string }>>([]);
  const pendingToolCallsRef = useRef<Array<{ tool: string; args: Record<string, string>; result?: string }>>([]);
  const [toolActivity, setToolActivity] = useState<string | null>(null);
  const [anonMessageCount, setAnonMessageCount] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setInput("");
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming || !miniId) return;

      const userMsg: ChatMessageWithId = { _id: nextMsgId(), role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setIsStreaming(true);
      if (!isAuthenticated) setAnonMessageCount((c) => c + 1);

      const history = messages.map(({ role, content, toolCalls }) => ({ role, content, toolCalls }));

      try {
        const res = await fetchChatStream(
          miniId,
          text,
          history,
          conversationId || undefined,
        );
        if (!res.ok) throw new Error("Chat request failed");
        if (!res.body) throw new Error("No response body");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let hasReceivedFirstChunk = false;
        let chunkIndex = 0;

        // Add empty assistant message
        const assistantId = nextMsgId();
        flushSync(() => {
          setMessages((prev) => [
            ...prev,
            { _id: assistantId, role: "assistant", content: "" },
          ]);
        });

        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Normalize \r\n to \n (sse_starlette uses \r\n line endings)
          buffer = buffer.replace(/\r\n/g, "\n");

          // SSE spec: events are separated by \n\n (blank line)
          const events = buffer.split("\n\n");
          buffer = events.pop() || ""; // Last element may be incomplete

          for (const eventStr of events) {
            if (!eventStr.trim()) continue;

            let eventType = "";
            const dataLines: string[] = [];

            for (const rawLine of eventStr.split("\n")) {
              const line = rawLine.replace(/\r$/, "").replace(/^\uFEFF/, "");
              if (!line || line.startsWith(":")) continue;

              const sepIndex = line.indexOf(":");
              if (sepIndex < 0) continue;

              const field = line.slice(0, sepIndex).trim();
              let value = line.slice(sepIndex + 1);
              if (value.startsWith(" ")) value = value.slice(1);

              if (field === "event") {
                eventType = value.trim();
              } else if (field === "data") {
                dataLines.push(value);
              }
            }

            const data = dataLines.join("\n");

            if (eventType === "done" || data === "[DONE]") {
              // Parse conversation_id from done event if present
              if (eventType === "done" && data) {
                try {
                  const doneData = JSON.parse(data);
                  if (doneData.conversation_id) {
                    onConversationCreated(doneData.conversation_id);
                  }
                } catch {
                  // Not JSON or no conversation_id — that's fine
                }
              }
              break;
            }

            // Parse conversation_id from a dedicated event
            if (eventType === "conversation") {
              try {
                const convoData = JSON.parse(data);
                if (convoData.conversation_id) {
                  onConversationCreated(convoData.conversation_id);
                }
              } catch {
                // ignore
              }
              continue;
            }

            if (eventType === "tool_call") {
              try {
                const toolData = JSON.parse(data);
                const tc = { tool: toolData.tool, args: toolData.args || {} };
                pendingToolCallsRef.current = [...pendingToolCallsRef.current, tc];
                setPendingToolCalls([...pendingToolCallsRef.current]);

                // Set tool activity label directly
                const labels: Record<string, string> = {
                  search_memories: "Searching memories...",
                  search_evidence: "Searching evidence...",
                  think: "Thinking...",
                };
                setToolActivity(labels[tc.tool] || `Using ${tc.tool}...`);
              } catch { /* ignore parse errors */ }
              continue;
            }

            if (eventType === "tool_result") {
              try {
                const resultData = JSON.parse(data);
                const updated = [...pendingToolCallsRef.current];
                const last = updated.findLast(tc => tc.tool === resultData.tool && !tc.result);
                if (last) last.result = resultData.summary || resultData.result;
                pendingToolCallsRef.current = updated;
                setPendingToolCalls(updated);
              } catch { /* ignore parse errors */ }
              continue;
            }

            if (eventType === "error") {
              throw new Error(data || "Chat failed");
            }

            if (eventType === "chunk" || eventType === "") {
              // Clear tool activity when first chunk arrives
              setToolActivity(null);
              if (process.env.NODE_ENV !== "production") {
                console.debug("[useMiniChat] stream chunk", { assistantId, chunkIndex, data });
              }
              chunkIndex += 1;

              // On first chunk, attach accumulated tool calls to the message
              if (!hasReceivedFirstChunk && pendingToolCallsRef.current.length > 0) {
                const captured = [...pendingToolCallsRef.current];
                flushSync(() => {
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m._id === assistantId);
                    if (idx < 0) return prev;
                    const updated = [...prev];
                    const target = updated[idx];
                    updated[idx] = { ...target, role: "assistant", toolCalls: captured };
                    return updated;
                  });
                });
                pendingToolCallsRef.current = [];
                setPendingToolCalls([]);
              }

              hasReceivedFirstChunk = true;
              flushSync(() => {
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m._id === assistantId);
                  if (idx < 0) return prev;
                  const updated = [...prev];
                  const target = updated[idx];
                  updated[idx] = {
                    ...target,
                    role: "assistant",
                    content: `${target.content}${data}`,
                  };
                  return updated;
                });
              });
            }
          }
        }

        // If we have pending tool calls but no content, attach them to the message
        if (pendingToolCallsRef.current.length > 0) {
          const captured = [...pendingToolCallsRef.current];
          setMessages((prev) => {
            const idx = prev.findIndex((m) => m._id === assistantId);
            if (idx < 0) return prev;
            const updated = [...prev];
            const target = updated[idx];
            updated[idx] = { ...target, role: "assistant", toolCalls: captured };
            return updated;
          });
        }
      } catch {
        setMessages((prev) => [
          ...prev.filter((m) => m.content !== ""),
          {
            _id: nextMsgId(),
            role: "assistant",
            content: "Sorry, I couldn't respond right now. Please try again.",
          },
        ]);
      } finally {
        setIsStreaming(false);
        setToolActivity(null);
        pendingToolCallsRef.current = [];
        setPendingToolCalls([]);
        textareaRef.current?.focus();
      }
    },
    [miniId, messages, isStreaming, isAuthenticated, conversationId, onConversationCreated]
  );

  return {
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
  };
}
