export function getMessageTopScrollPosition(
  container: HTMLElement,
  message: HTMLElement
): number {
  const containerRect = container.getBoundingClientRect();
  const messageRect = message.getBoundingClientRect();
  const paddingTop =
    Number.parseFloat(window.getComputedStyle(container).paddingTop) || 0;

  return Math.max(
    0,
    container.scrollTop + messageRect.top - containerRect.top - paddingTop
  );
}

type ChatMessageRole = "user" | "assistant";

type ChatScrollAction = "none" | "bottom" | "last-message-top";

interface ChatScrollDecisionInput {
  prevCount: number;
  currCount: number;
  lastMessageRole: ChatMessageRole | null;
}

export function getChatScrollAction({
  prevCount,
  currCount,
  lastMessageRole,
}: ChatScrollDecisionInput): ChatScrollAction {
  const delta = currCount - prevCount;

  if (currCount <= 0 || delta < 0) {
    return "none";
  }

  if (delta > 1) {
    return "last-message-top";
  }

  if (delta === 1 && lastMessageRole === "assistant") {
    return "last-message-top";
  }

  if (delta === 1) {
    return "bottom";
  }

  return "none";
}

export function scrollMessageTopIntoView(
  container: HTMLElement,
  message: HTMLElement
) {
  container.scrollTop = getMessageTopScrollPosition(container, message);
}
