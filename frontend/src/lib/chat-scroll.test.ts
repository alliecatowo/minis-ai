import { describe, expect, it } from "vitest";
import { getMessageTopScrollPosition } from "./chat-scroll";

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
