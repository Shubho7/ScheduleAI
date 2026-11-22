const sessionId = Math.random().toString().substring(10);
const ws_scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws_url = ws_scheme + window.location.host + "/ws/" + sessionId;
let websocket = null;
let is_audio = false;
let currentMessageId = null; 
let typingIndicator = null;
let latestUserMessageElement = null;

const messageForm = document.getElementById("messageForm");
const messageInput = document.getElementById("message");
const messagesDiv = document.getElementById("messages");
const statusDot = document.getElementById("status-dot");
const connectionStatus = document.getElementById("connection-status");
const startAudioButton = document.getElementById("startAudioButton");
const stopAudioButton = document.getElementById("stopAudioButton");
const recordingContainer = document.getElementById("recording-container");

// Connection state. The server hands out a resume token so that after a dropped
// connection the page rejoins the same chat session and keeps its context.
let resumeToken = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
let heartbeatTimer = null;

// Send a small ping regularly so proxies never see the connection as idle
function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(function () {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
      websocket.send(JSON.stringify({ mime_type: "ping", data: "" }));
    }
  }, 20000);
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

// WebSocket handlers
function connectWebsocket() {
  // Keep exactly one socket: retire the old one without letting its onclose
  // trigger another reconnect (that used to leave duplicate connections open).
  clearTimeout(reconnectTimer);
  if (websocket) {
    const old = websocket;
    old.onopen = old.onmessage = old.onclose = old.onerror = null;
    old.close();
  }
  stopHeartbeat();

  // Connect websocket
  let wsUrl = ws_url + "?is_audio=" + is_audio;
  if (resumeToken) wsUrl += "&resume=" + encodeURIComponent(resumeToken);
  const thisSocket = new WebSocket(wsUrl);
  websocket = thisSocket;

  websocket.onopen = function () {
    console.log("WebSocket connection opened.");
    connectionStatus.textContent = "Connected";
    statusDot.classList.add("connected");
    reconnectAttempts = 0;
    startHeartbeat();

    document.getElementById("sendButton").disabled = false;
    addSubmitHandler();
  };

  // Handle incoming messages
  websocket.onmessage = function (event) {
    // Parse the incoming message
    const message_from_server = JSON.parse(event.data);

    // Connection housekeeping messages
    if (message_from_server.session_token) {
      resumeToken = message_from_server.session_token;
      return;
    }
    if (message_from_server.pong) return;

    console.log("[AGENT TO CLIENT] ", message_from_server);

    if (
      !message_from_server.turn_complete &&
      (message_from_server.mime_type === "text/plain" ||
        message_from_server.mime_type === "audio/pcm") &&
      !typingIndicator
    ) {
      insertTypingIndicatorAfter(latestUserMessageElement);
    }

    // Check if the turn is complete
    if (
      message_from_server.turn_complete &&
      message_from_server.turn_complete === true
    ) {
      currentMessageId = null;
      removeTypingIndicator();
      return;
    }

    // Handle audio messages
    if (message_from_server.mime_type === "audio/pcm" && audioPlayerNode) {
      audioPlayerNode.port.postMessage(base64ToArray(message_from_server.data));

      if (currentMessageId) {
        const messageElem = document.getElementById(currentMessageId);
        if (
          messageElem &&
          !messageElem.querySelector(".audio-icon") &&
          is_audio
        ) {
          const audioIcon = document.createElement("i");
          audioIcon.className = "fi fi-sr-circle-waveform-lines audio-icon";
          messageElem.prepend(audioIcon);
        }
      }
    }

    // Handle text messages
    if (message_from_server.mime_type === "text/plain") {
      removeTypingIndicator();

      const role = message_from_server.role || "model";

      if (currentMessageId && role === "model") {
        const existingMessage = document.getElementById(currentMessageId);
        if (existingMessage) {

          const textNode = document.createTextNode(message_from_server.data);
          existingMessage.appendChild(textNode);

          messagesDiv.scrollTop = messagesDiv.scrollHeight;
          return;
        }
      }

      const messageId = Math.random().toString(36).substring(7);
      const messageElem = document.createElement("p");
      messageElem.id = messageId;

      // Set class based on role
      messageElem.className =
        role === "user" ? "user-message" : "agent-message";

      
      if (is_audio && role === "model") {
        const audioIcon = document.createElement("i");
        audioIcon.className = "fi fi-sr-circle-waveform-lines audio-icon";
        messageElem.appendChild(audioIcon);
      }

      // Add the text content
      messageElem.appendChild(
        document.createTextNode(message_from_server.data)
      );

      // Add the message to the DOM
      messagesDiv.appendChild(messageElem);

      if (role === "model") {
        currentMessageId = messageId;
      } else if (role === "user") {
        latestUserMessageElement = messageElem;
      }

      messagesDiv.scrollTop = messagesDiv.scrollHeight;
      
      if (role === "user") {
        insertTypingIndicatorAfter(latestUserMessageElement);
      }
    }
  };

  // Handle connection close
  websocket.onclose = function () {
    // Ignore the close of a socket that has already been replaced
    if (websocket !== thisSocket) return;

    console.log("WebSocket connection closed.");
    stopHeartbeat();
    document.getElementById("sendButton").disabled = true;
    connectionStatus.textContent = "Disconnected. Reconnecting...";
    statusDot.classList.remove("connected");
    removeTypingIndicator();

    // Reconnect quickly at first, then back off (1s, 2s, 4s ... up to 10s)
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 10000);
    reconnectAttempts += 1;
    reconnectTimer = setTimeout(function () {
      console.log("Reconnecting...");
      connectWebsocket();
    }, delay);
  };

  websocket.onerror = function (e) {
    console.log("WebSocket error: ", e);
    connectionStatus.textContent = "Connection error";
    statusDot.classList.remove("connected");
    removeTypingIndicator();
  };
}
connectWebsocket();

// --- Google Calendar connection (each visitor connects their own account) ---
const calendarAuthDiv = document.getElementById("calendar-auth");

function authElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

function renderCalendarAuth(status, notice) {
  calendarAuthDiv.replaceChildren();

  if (notice) {
    calendarAuthDiv.appendChild(authElement("span", "auth-warning", notice));
  }

  if (!status.configured) {
    calendarAuthDiv.appendChild(
      authElement("span", "", "Calendar sign-in isn't set up on this server.")
    );
  } else if (status.connected) {
    calendarAuthDiv.appendChild(authElement("span", "", "Calendar connected"));
    if (status.email) {
      calendarAuthDiv.appendChild(authElement("span", "auth-email", status.email));
    }
    const disconnect = authElement("button", "auth-btn", "Disconnect");
    disconnect.type = "button";
    disconnect.addEventListener("click", async () => {
      disconnect.disabled = true;
      try {
        await fetch("/auth/disconnect", { method: "POST" });
      } finally {
        // Reload so the new chat session starts without the calendar login
        window.location.reload();
      }
    });
    calendarAuthDiv.appendChild(disconnect);
  } else {
    const connect = authElement("a", "auth-btn primary", "Connect Google Calendar");
    connect.href = "/auth/login";
    calendarAuthDiv.appendChild(connect);
  }
}

async function initCalendarAuth() {
  // The server sends users back to "/?auth=..." after the Google sign-in
  const params = new URLSearchParams(window.location.search);
  const result = params.get("auth");
  let notice = "";
  if (result === "denied") notice = "Access was not granted.";
  else if (result === "error") notice = "Sign-in failed. Please try again.";
  if (result) window.history.replaceState({}, "", window.location.pathname);

  try {
    const response = await fetch("/auth/status", { cache: "no-store" });
    renderCalendarAuth(await response.json(), notice);
  } catch (e) {
    console.error("Could not load calendar status", e);
  }
}

initCalendarAuth();

// Add submit handler to the form
function addSubmitHandler() {
  messageForm.onsubmit = function (e) {
    e.preventDefault();
    const message = messageInput.value;
    if (message) {
      const p = document.createElement("p");
      p.textContent = message;
      p.className = "user-message";
      messagesDiv.appendChild(p);
      messageInput.value = "";
      
      latestUserMessageElement = p;
      
      insertTypingIndicatorAfter(latestUserMessageElement);
      
      // Send the message to the server
      sendMessage({
        mime_type: "text/plain",
        data: message,
        role: "user",
      });
      console.log("[CLIENT TO AGENT] " + message);
      
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
    return false;
  };
}

// Send a message to the server as a JSON string
function sendMessage(message) {
  if (websocket && websocket.readyState == WebSocket.OPEN) {
    const messageJson = JSON.stringify(message);
    websocket.send(messageJson);
  }
}

// Decode Base64 data to Array
function base64ToArray(base64) {
  const binaryString = window.atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Audio handling
 */

let audioPlayerNode;
let audioPlayerContext;
let audioRecorderNode;
let audioRecorderContext;
let micStream;
let isRecording = false;

// Import the audio worklets
import { startAudioPlayerWorklet } from "./audio-player.js";
import { startAudioRecorderWorklet } from "./audio-recorder.js";

// Start audio
function startAudio() {
  // Start audio output
  startAudioPlayerWorklet().then(([node, ctx]) => {
    audioPlayerNode = node;
    audioPlayerContext = ctx;
  });
  // Start audio input
  startAudioRecorderWorklet(audioRecorderHandler).then(
    ([node, ctx, stream]) => {
      audioRecorderNode = node;
      audioRecorderContext = ctx;
      micStream = stream;
      isRecording = true;
    }
  );
}

// Stop audio recording
function stopAudio() {
  if (audioRecorderNode) {
    audioRecorderNode.disconnect();
    audioRecorderNode = null;
  }

  if (audioRecorderContext) {
    audioRecorderContext
      .close()
      .catch((err) => console.error("Error closing audio context:", err));
    audioRecorderContext = null;
  }

  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }

  isRecording = false;
}

startAudioButton.addEventListener("click", () => {
  startAudioButton.disabled = true;
  startAudioButton.textContent = "Voice Enabled";
  startAudioButton.style.display = "none";
  stopAudioButton.style.display = "inline-block";
  recordingContainer.style.display = "flex";
  startAudio();
  is_audio = true;

  messagesDiv.classList.add("audio-enabled");

  connectWebsocket(); 
});

// Stop audio recording when stop button is clicked
stopAudioButton.addEventListener("click", () => {
  stopAudio();
  stopAudioButton.style.display = "none";
  startAudioButton.style.display = "inline-block";
  startAudioButton.disabled = false;
  startAudioButton.innerHTML = '<i class="fi fi-br-waveform-path" style="font-size: 20px;"></i>';
  recordingContainer.style.display = "none";

  messagesDiv.classList.remove("audio-enabled");

  // Reconnect without audio mode (connectWebsocket retires the voice socket)
  is_audio = false;
  connectWebsocket();
});

// Audio recorder handler.
// The microphone worklet produces a tiny chunk every ~8 ms (125 per second).
// Sending each one as its own message floods the server, so collect about
// 100 ms of audio (16 kHz, 16-bit = 3200 bytes) and send it as one message.
const AUDIO_BATCH_BYTES = 3200;
let pendingAudioChunks = [];
let pendingAudioBytes = 0;

function audioRecorderHandler(pcmData) {
  if (!isRecording) {
    pendingAudioChunks = [];
    pendingAudioBytes = 0;
    return;
  }

  pendingAudioChunks.push(new Uint8Array(pcmData));
  pendingAudioBytes += pcmData.byteLength;
  if (pendingAudioBytes < AUDIO_BATCH_BYTES) return;

  // Join the collected chunks into one buffer
  const batch = new Uint8Array(pendingAudioBytes);
  let offset = 0;
  for (const chunk of pendingAudioChunks) {
    batch.set(chunk, offset);
    offset += chunk.byteLength;
  }
  pendingAudioChunks = [];
  pendingAudioBytes = 0;

  // Send the pcm data as base64
  sendMessage({
    mime_type: "audio/pcm",
    data: arrayBufferToBase64(batch.buffer),
  });
}

// Encode an array buffer with Base64
function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

function insertTypingIndicatorAfter(element) {
  removeTypingIndicator();
  typingIndicator = document.createElement("div");
  typingIndicator.id = "typing-indicator";
  typingIndicator.className = "typing-indicator visible";
  typingIndicator.innerHTML = '<span></span><span></span><span></span>';
  
  // If element is provided and exists in the DOM, insert after it
  if (element && element.parentNode) {
    element.parentNode.insertBefore(typingIndicator, element.nextSibling);
  } else {
    // Fallback: append to messagesDiv if no valid element is provided
    messagesDiv.appendChild(typingIndicator);
  }
  
  if (messagesDiv.scrollHeight - messagesDiv.scrollTop <= messagesDiv.clientHeight + 100) {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }
}

function removeTypingIndicator() {
  if (typingIndicator && typingIndicator.parentNode) {
    typingIndicator.parentNode.removeChild(typingIndicator);
    typingIndicator = null;
  }
}