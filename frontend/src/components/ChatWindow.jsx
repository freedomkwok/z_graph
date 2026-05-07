import { useEffect, useRef, useState } from "react";

import { withApiBase } from "../TaskStore/constants";

const CHAT_SESSION_STORAGE_KEY = "z_graph.chat_session_id";
const DEFAULT_CHAT_SIZE = { width: 360, height: 480 };
const MIN_CHAT_WIDTH = 280;
const MIN_CHAT_HEIGHT = 320;

export default function ChatWindow() {
  const [isVisible, setIsVisible] = useState(true);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [chatSize, setChatSize] = useState(DEFAULT_CHAT_SIZE);
  const [sessionId, setSessionId] = useState(() => {
    return window.sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY) || "";
  });
  const [messages, setMessages] = useState([
    {
      role: "bot",
      text: "Ask a question about your graph.",
    },
  ]);
  const [query, setQuery] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sessionError, setSessionError] = useState("");
  const messagesRef = useRef(null);
  const resizeRef = useRef(null);

  useEffect(() => {
    if (sessionId) return;
    let ignore = false;

    const createSession = async () => {
      try {
        const response = await fetch(withApiBase("/api/chat/session"), { method: "POST" });
        const payload = await response.json();
        if (!response.ok || !payload?.session_id) {
          throw new Error(payload?.detail || payload?.error || "Unable to create chat session");
        }
        if (ignore) return;
        window.sessionStorage.setItem(CHAT_SESSION_STORAGE_KEY, payload.session_id);
        setSessionId(payload.session_id);
        setSessionError("");
      } catch (error) {
        if (ignore) return;
        setSessionError(error instanceof Error ? error.message : "Unable to create chat session");
      }
    };

    createSession();
    return () => {
      ignore = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!messagesRef.current) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages, isCollapsed]);

  useEffect(() => {
    const stopChatResize = () => {
      if (!resizeRef.current) return;
      resizeRef.current = null;
      document.body.classList.remove("chat-resizing");
    };

    const onPointerMove = (event) => {
      const resize = resizeRef.current;
      if (!resize) return;
      const viewportWidth = window.innerWidth || resize.width;
      const viewportHeight = window.innerHeight || resize.height;
      const maxWidth = Math.max(MIN_CHAT_WIDTH, viewportWidth - 48);
      const maxHeight = Math.max(MIN_CHAT_HEIGHT, viewportHeight - 88);
      const nextWidth = resize.side.includes("left")
        ? resize.width + resize.clientX - event.clientX
        : resize.width;
      const nextHeight = resize.side.includes("top")
        ? resize.height + resize.clientY - event.clientY
        : resize.height;

      setChatSize({
        width: Math.min(Math.max(nextWidth, MIN_CHAT_WIDTH), maxWidth),
        height: Math.min(Math.max(nextHeight, MIN_CHAT_HEIGHT), maxHeight),
      });
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopChatResize);
    window.addEventListener("pointercancel", stopChatResize);
    window.addEventListener("blur", stopChatResize);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopChatResize);
      window.removeEventListener("pointercancel", stopChatResize);
      window.removeEventListener("blur", stopChatResize);
      document.body.classList.remove("chat-resizing");
    };
  }, []);

  const startChatResize = (side, event) => {
    resizeRef.current = {
      side,
      width: chatSize.width,
      height: chatSize.height,
      clientX: event.clientX,
      clientY: event.clientY,
    };
    document.body.classList.add("chat-resizing");
    event.preventDefault();
  };

  const sendMessage = async (event) => {
    event.preventDefault();
    const nextQuery = query.trim();
    if (!nextQuery || isSending) return;

    setQuery("");
    setIsSending(true);
    setMessages((current) => [...current, { role: "user", text: nextQuery }]);

    try {
      if (!sessionId) {
        throw new Error("Chat session is not ready yet");
      }
      const response = await fetch(withApiBase("/api/chat/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, query: nextQuery }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.error || "Chat request failed");
      }
      setMessages((current) => [
        ...current,
        { role: "bot", text: payload?.reply || "I received your message." },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "bot",
          text: error instanceof Error ? error.message : "Chat request failed",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  if (!isVisible) {
    return (
      <button
        className="chat-launcher"
        type="button"
        onClick={() => {
          setIsVisible(true);
          setIsCollapsed(false);
        }}
      >
        Chat
      </button>
    );
  }

  const chatWindowStyle = {
    width: `min(${chatSize.width}px, calc(100vw - 70px))`,
    height: `min(${chatSize.height}px, calc(100vh - 96px))`,
  };

  return (
    <aside className={`chat-window-wrap ${isCollapsed ? "collapsed" : ""}`} aria-label="Chat window">
      <button
        className="chat-side-toggle"
        type="button"
        onClick={() => setIsCollapsed((current) => !current)}
        title={isCollapsed ? "Expand chat" : "Collapse chat"}
        aria-label={isCollapsed ? "Expand chat" : "Collapse chat"}
      >
        {isCollapsed ? "<" : ">"}
      </button>
      {!isCollapsed && (
        <section className="chat-window" style={chatWindowStyle}>
          <div
            className="chat-resize-edge chat-resize-top"
            onPointerDown={(event) => startChatResize("top", event)}
            aria-hidden="true"
          />
          <div
            className="chat-resize-edge chat-resize-left"
            onPointerDown={(event) => startChatResize("left", event)}
            aria-hidden="true"
          />
          <div
            className="chat-resize-corner"
            onPointerDown={(event) => startChatResize("top-left", event)}
            aria-hidden="true"
          />
          <header className="chat-window-head">
            <div>
              <h2>Chat</h2>
            </div>
            <button
              className="chat-close-btn"
              type="button"
              onClick={() => setIsVisible(false)}
              aria-label="Close chat"
              title="Close chat"
            >
              X
            </button>
          </header>
          {sessionError && <div className="chat-session-error">{sessionError}</div>}
          <div className="chat-message-list" ref={messagesRef} aria-live="polite">
            {messages.map((message, index) => (
              <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                <span className="chat-message-author">{message.role === "user" ? "You" : "Bot"}</span>
                <p>{message.text}</p>
              </div>
            ))}
          </div>
          <form className="chat-input-row" onSubmit={sendMessage}>
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Type your query..."
              aria-label="Chat query"
            />
            <button
              className="chat-send-btn"
              type="submit"
              disabled={!query.trim() || isSending || !sessionId}
            >
              {isSending ? "Sending" : "Send"}
            </button>
          </form>
        </section>
      )}
    </aside>
  );
}
