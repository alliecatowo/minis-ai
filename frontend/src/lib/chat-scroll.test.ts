import { describe, expect, it } from "vitest";
import { getChatScrollAction, getMessageTopScrollPosition } from "./chat-scroll";

function setRect(element: HTMLElement, top: number) {
  element.getBoundingClientRect = () =>
    ({
      x: 0,
      y: top,
      top,
      bottom: top,
      left: 0,
      right: 0,
      width: 0,
      height: 0,
      toJSON: () => ({}),
    }) as DOMRect;
}

describe("getMessageTopScrollPosition", () => {
  it("aligns a message top relative to the scroll container and preserves top padding", () => {
    const container = document.createElement("div");
    const message = document.createElement("div");
    container.style.paddingTop = "16px";
    container.scrollTop = 120;

    setRect(container, 40);
    setRect(message, 220);

    expect(getMessageTopScrollPosition(container, message)).toBe(284);
  });

  it("does not return negative scroll positions", () => {
    const container = document.createElement("div");
    const message = document.createElement("div");
    container.style.paddingTop = "24px";
    container.scrollTop = 0;

    setRect(container, 100);
    setRect(message, 110);

    expect(getMessageTopScrollPosition(container, message)).toBe(0);
  });
});

describe("getChatScrollAction", () => {
  it("returns last-message-top for bulk-loaded history", () => {
    expect(
      getChatScrollAction({
        prevCount: 0,
        currCount: 4,
        lastMessageRole: "assistant",
      })
    ).toBe("last-message-top");
  });

  it("returns last-message-top when first assistant response arrives", () => {
    expect(
      getChatScrollAction({
        prevCount: 1,
        currCount: 2,
        lastMessageRole: "assistant",
      })
    ).toBe("last-message-top");
  });

  it("returns bottom when a new user message arrives", () => {
    expect(
      getChatScrollAction({
        prevCount: 0,
        currCount: 1,
        lastMessageRole: "user",
      })
    ).toBe("bottom");
  });

  it("returns none for streaming updates with no message-count delta", () => {
    expect(
      getChatScrollAction({
        prevCount: 2,
        currCount: 2,
        lastMessageRole: "assistant",
      })
    ).toBe("none");
  });
});
