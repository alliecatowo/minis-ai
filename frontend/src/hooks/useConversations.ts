"use client";

import { useState, useCallback } from "react";
import {
  getConversations,
  getConversation,
  deleteConversation,
  type Conversation,
} from "@/lib/api";
import { type ChatMessageWithId } from "./useMiniChat";

interface UseConversationsOptions {
  miniId: string | undefined;
  isAuthenticated: boolean;
}

interface UseConversationsReturn {
  conversations: Conversation[];
  setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>;
  conversationId: string | null;
  setConversationId: React.Dispatch<React.SetStateAction<string | null>>;
  loadingConversation: boolean;
  conversationsSupported: boolean;
  refreshConversations: () => void;
  loadConversation: (convoId: string) => Promise<ChatMessageWithId[] | null>;
  handleDeleteConversation: (convoId: string, e: React.MouseEvent) => Promise<void>;
}

export function useConversations({
  miniId,
  isAuthenticated,
}: UseConversationsOptions): UseConversationsReturn {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationsSupported] = useState(true);

  const refreshConversations = useCallback(() => {
    if (!miniId || !isAuthenticated || !conversationsSupported) return;
    getConversations(miniId).then(setConversations);
  }, [miniId, isAuthenticated, conversationsSupported]);

  const loadConversation = useCallback(
    async (convoId: string): Promise<ChatMessageWithId[] | null> => {
      if (!miniId) return null;
      setLoadingConversation(true);
      const result = await getConversation(miniId, convoId);
      setLoadingConversation(false);
      if (result) {
        setConversationId(convoId);
        return result.messages.map((m) => ({
          _id: m.id,
          role: m.role,
          content: m.content,
        }));
      }
      return null;
    },
    [miniId]
  );

  const handleDeleteConversation = useCallback(
    async (convoId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!miniId) return;
      const success = await deleteConversation(miniId, convoId);
      if (success) {
        setConversations((prev) => prev.filter((c) => c.id !== convoId));
        if (conversationId === convoId) {
          setConversationId(null);
        }
      }
    },
    [miniId, conversationId]
  );

  return {
    conversations,
    setConversations,
    conversationId,
    setConversationId,
    loadingConversation,
    conversationsSupported,
    refreshConversations,
    loadConversation,
    handleDeleteConversation,
  };
}
