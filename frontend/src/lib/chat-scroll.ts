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

export function scrollMessageTopIntoView(
  container: HTMLElement,
  message: HTMLElement
) {
  container.scrollTop = getMessageTopScrollPosition(container, message);
}
