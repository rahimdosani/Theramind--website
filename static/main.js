let recognition = null;
let isListening = false;
let preferredVoice = null;
let isSpeaking = false;
let currentUtterance = null;
let waitingIndicator = null;
let assistantName = localStorage.getItem("assistantName") || "Theramind";

/* ======================================================
  🔒 SMALL HELPERS
====================================================== */
function escapeHTML(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sanitizeText(text) {
  return String(text || "").replace(/[*_~`]/g, "").trim();
}

function formatTimestamp(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ======================================================
  🎤 SPEECH RECOGNITION
====================================================== */
function initRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    showToast("⚠️ Speech recognition not supported in this browser.");
    const speakBtn = document.getElementById("speak");
    if (speakBtn) {
      speakBtn.disabled = true;
      speakBtn.textContent = "🎙️ N/A";
    }
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isListening = true;
    const indicator = document.getElementById("voice-indicator");
    const speakBtn = document.getElementById("speak");
    if (indicator) indicator.style.display = "block";
    if (speakBtn) speakBtn.textContent = "⏹️ Stop";
  };

  recognition.onend = () => {
    isListening = false;
    const indicator = document.getElementById("voice-indicator");
    const speakBtn = document.getElementById("speak");
    if (indicator) indicator.style.display = "none";
    if (speakBtn) speakBtn.textContent = "🎙️ Speak";

    const message = document.getElementById("user-input").value.trim();
    if (message) sendMessage();
  };

  recognition.onerror = (e) => {
    console.error(e);
    stopListening();
    showToast("⚠️ Voice input stopped due to an error.");
  };

  recognition.onresult = (event) => {
    let interim = "",
      final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal)
        final += event.results[i][0].transcript;
      else interim += event.results[i][0].transcript;
    }
    document.getElementById("user-input").value = final || interim;
  };
}

function startListening() {
  if (!recognition) initRecognition();
  if (!recognition) return; // not supported
  if (!isListening) recognition.start();
  else stopListening();
}

function stopListening() {
  if (recognition && isListening) recognition.stop();
}

/* ======================================================
  🎙️ NATURAL HUMAN VOICE ENGINE
====================================================== */

let availableVoices = [];
let voicesLoaded = false;

function loadVoices() {
  availableVoices = speechSynthesis.getVoices();
  if (availableVoices.length > 0) {
    voicesLoaded = true;
  }
}

speechSynthesis.onvoiceschanged = loadVoices;
loadVoices();

/* -------- Detect Hindi vs English -------- */
function detectLanguage(text) {
  for (let ch of text) {
    const code = ch.charCodeAt(0);
    if (code >= 0x0900 && code <= 0x097F) {
      return "hi-IN";
    }
  }
  return "en-US";
}

/* -------- Select Best Female Voice -------- */
function selectBestVoice(lang) {
  if (!voicesLoaded) return null;

  let filtered = availableVoices.filter(v =>
    v.lang.toLowerCase().includes(lang.split("-")[0].toLowerCase())
  );

  if (!filtered.length) filtered = availableVoices;

  const preferred = filtered.find(v =>
    v.name.toLowerCase().includes("google") ||
    v.name.toLowerCase().includes("zira") ||
    v.name.toLowerCase().includes("samantha") ||
    v.name.toLowerCase().includes("female")
  );

  return preferred || filtered[0] || null;
}

/* -------- Add Natural Human Pauses -------- */
function addNaturalPauses(text) {
  return text
    .replace(/\./g, "... ")
    .replace(/,/g, ", ")
    .replace(/\?/g, "? ")
    .replace(/!/g, "! ");
}

/* -------- Main Speak Function -------- */
function speakOut(text, btn = null) {
  if (!window.speechSynthesis) return;

  if (isSpeaking) {
    speechSynthesis.cancel();
    isSpeaking = false;
  }

  const lang = detectLanguage(text);
  const selectedVoice = selectBestVoice(lang);
  const processedText = addNaturalPauses(text);

  const utterance = new SpeechSynthesisUtterance(processedText);

  if (selectedVoice) {
    utterance.voice = selectedVoice;
    utterance.lang = selectedVoice.lang;
  } else {
    utterance.lang = lang;
  }

  /* 🔥 Human Warmth Tuning */
  if (lang.startsWith("hi")) {
    utterance.rate = 0.90;
    utterance.pitch = 1.05;
  } else {
    utterance.rate = 0.93;
    utterance.pitch = 1.07;
  }

  utterance.volume = 1;

  utterance.onend = () => {
    isSpeaking = false;
    if (btn) btn.textContent = "🔊";
  };

  isSpeaking = true;
  if (btn) btn.textContent = "⏹️";

  speechSynthesis.speak(utterance);
}

/* -------- Speak Button Toggle -------- */
function speakOutButton(e) {
  const btn = e.target;
  const text = btn.getAttribute("data-text");
  if (!text) return;

  if (isSpeaking) {
    speechSynthesis.cancel();
    isSpeaking = false;
    btn.textContent = "🔊";
  } else {
    speakOut(text, btn);
  }
}


/* ======================================================
  💬 CHAT MESSAGES
====================================================== */
function appendMessage(role, content, timestamp = null) {
  const chatBox = document.getElementById("chat-box");
  if (!chatBox) return;

  const safeContent = escapeHTML(content);
  const div = document.createElement("div");
  div.className = `message ${role}`;

  const label = role === "user" ? "You" : assistantName;
  const time = timestamp || formatTimestamp(new Date());

  const speakBtnHTML =
    role === "bot"
      ? `<button class="speak-btn" data-text="${safeContent}" onclick="speakOutButton(event)">🔊</button>`
      : "";

  div.innerHTML = `
    <strong>${escapeHTML(label)}:</strong>
    <span class="chat-text"> ${safeContent}</span>
    ${speakBtnHTML}
    <div class="timestamp">${escapeHTML(time)}</div>
  `.trim();

  chatBox.appendChild(div);
  requestAnimationFrame(() => {
  chatBox.scrollTop = chatBox.scrollHeight;
});

}

function showTyping() {
  const chatBox = document.getElementById("chat-box");
  if (!chatBox) return;
  if (!waitingIndicator) {
    waitingIndicator = document.createElement("div");
    waitingIndicator.className = "message bot typing-indicator";
    waitingIndicator.textContent = `${assistantName} is typing...`;
    chatBox.appendChild(waitingIndicator);
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

function hideTyping() {
  if (waitingIndicator) {
    waitingIndicator.remove();
    waitingIndicator = null;
  }
}

/* ======================================================
  📝 SEND MESSAGE
====================================================== */


function sendMessage() {
  const input = document.getElementById("user-input");
  if (!input) return;

  const message = input.value.trim();
  if (!message) return;

  appendMessage("user", message);
  input.value = "";
  showTyping();

  fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  })
    .then((res) => (res.ok ? res.json() : Promise.reject("Network error")))
    .then((data) => {
      hideTyping();
      const reply = data && data.reply ? sanitizeText(data.reply) : "";
      appendMessage("bot", reply || "I’m here with you.");
    
    })
    .catch((err) => {
      console.error(err);
      hideTyping();
      appendMessage(
        "bot",
        "⚠️ Something went wrong on my side. Could you try again?"
      );
    });
}

/* ======================================================
  🆕 CHAT CONTROLS
====================================================== */
function getPersonalizedGreeting() {
  const name = window.THERAMIND_USER?.name;

  if (name && typeof name === "string" && name.trim().length > 0) {
    return `Hello ${name}, how are you feeling today?`;
  }

  return "Hello! I'm here for you. How are you feeling today?";
}
function newChat() {
  fetch("/reset_session")
    .then(() => {
      const chatBox = document.getElementById("chat-box");
      if (chatBox) chatBox.innerHTML = "";
      appendMessage(
  "bot",
  getPersonalizedGreeting()
);

      showToast("New chat started");
    })
    .catch(() => showToast("Could not start new chat", "error"));
}

function clearChat() {
  newChat();
}

/* ======================================================
  💾 SAVED CHATS & MODALS
====================================================== */
function toggleModal(modalId, show = true) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  if (show) modal.classList.add("active");
  else modal.classList.remove("active");
}

function closeSaveModal() {
  toggleModal("saveChatModal", false);
}

function closeSavedChatsModal() {
  toggleModal("savedChatsModal", false);
}

function showSaveModal() {
  toggleModal("saveChatModal", true);
  const input = document.getElementById("chatTitleInput");
  if (!input) return;
  input.value = "";
  input.focus();
  input.removeEventListener("keydown", handleSaveEnter);
  input.addEventListener("keydown", handleSaveEnter);
}

function handleSaveEnter(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    saveChat();
  }
}

function saveChat() {
  const titleInput = document.getElementById("chatTitleInput");
  if (!titleInput) return;

  const title = titleInput.value.trim();
  if (!title) return showToast("Please enter a title for your chat.");

  const chatBox = document.getElementById("chat-box");
if (!chatBox || !chatBox.children.length) {
  return showToast("Nothing to save yet.");
}


  fetch("/save_conversation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title}),
  })
    .then((res) => (res.ok ? res.json() : Promise.reject("Failed")))
    .then(() => {
      showToast("Chat saved!");
      closeSaveModal();
      showSavedChatsModal();
    })
    .catch((err) => {
      console.error(err);
      showToast("⚠️ Failed to save chat.");
    });
}

function showSavedChatsModal() {
  fetch("/get_conversations")
    .then((res) => (res.ok ? res.json() : Promise.reject("Failed")))
    .then((data) => {
      const list = document.getElementById("savedChatsList");
      if (!list) return;

      // ✅ Backend returns { ok: true, chats: [...] }
      if (!data.ok || !Array.isArray(data.chats) || data.chats.length === 0) {
        list.innerHTML =
          '<p style="text-align:center;color:var(--foreground);">No saved chats</p>';
        toggleModal("savedChatsModal", true);
        return;
      }

      list.innerHTML = data.chats
        .map(
          (c) => `
        <div class="chat-item" data-id="${c.id}">
          <span class="chat-title" onclick="loadConversation(event, ${c.id})">
            ${escapeHTML(c.title || "Untitled Chat")}
          </span>
          <div class="chat-actions">
            <button class="rename-btn" onclick="renameChat(event, ${c.id})">✏️</button>
            <button class="delete-btn" onclick="deleteConversation(event, ${c.id})">🗑️</button>
          </div>
        </div>
      `
        )
        .join("");

      toggleModal("savedChatsModal", true);
    })
    .catch((err) => {
      console.error(err);
      showToast("Failed to load saved chats");
    });
}

function loadConversation(e, id) {
  if (e && e.stopPropagation) e.stopPropagation();

  const chatBox = document.getElementById("chat-box");
  if (chatBox) chatBox.innerHTML = "";

  fetch(`/load_conversation/${id}`)
    .then((res) => (res.ok ? res.json() : Promise.reject("Failed")))
    .then((res) => {
  if (!res.ok || !Array.isArray(res.history)) {
    showToast("Failed to load conversation.");
    return;
  }

  res.history.forEach((msg) =>
    appendMessage(
      msg.role,
      sanitizeText(msg.content),
      msg.timestamp || null
    )
  );

      
      closeSavedChatsModal();
    })
    .catch((err) => {
      console.error(err);
      showToast("⚠️ Failed to load conversation.");
    });
}

function deleteConversation(e, id) {
  if (e && e.stopPropagation) e.stopPropagation();
  fetch(`/delete_conversation/${id}`, { method: "DELETE" })
    .then((res) => (res.ok ? res.json() : Promise.reject("Failed")))
    .then(() => {
      showToast("🗑️ Chat deleted.");
      showSavedChatsModal();
    })
    .catch((err) => {
      console.error(err);
      showToast("⚠️ Failed to delete chat.");
    });
}

function renameChat(e, id) {
  if (e && e.stopPropagation) e.stopPropagation();
  const newName = prompt("Enter new chat name:");
  if (!newName) return;

  fetch(`/rename_conversation/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: newName }),
  })
    .then((res) => (res.ok ? res.json() : Promise.reject("Failed")))
    .then(() => {
      showToast("✏️ Chat renamed.");
      showSavedChatsModal();
    })
    .catch((err) => {
      console.error(err);
      showToast("⚠️ Failed to rename chat.");
    });
}

/* ======================================================
  🚀 EXPORT CHAT (BACKEND SOURCE OF TRUTH)
====================================================== */
function exportChat() {
  fetch("/get_current_conversation")
    .then((r) => r.json())
    .then((res) => {
      if (!res.ok || !Array.isArray(res.history)) {
        showToast(res.message || "Nothing to export");
        return;
      }

      const text = res.history
        .map((m) => {
          const role = m.role === "user" ? "You" : assistantName;
          return `${role}: ${m.content}`;
        })
        .join("\n\n");

      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);

      const a = document.createElement("a");
      a.href = url;
      a.download = "Theramind_Chat.txt";
      a.click();

      URL.revokeObjectURL(url);
      showToast("Chat exported");
    })
    .catch(() => showToast("Export failed", "error"));
}

function downloadChatPDF() {
  fetch("/get_current_conversation")
    .then((r) => r.json())
    .then((res) => {
      if (!res.ok || !Array.isArray(res.history)) {
        showToast(res.message || "Nothing to export");
        return;
      }

      const { jsPDF } = window.jspdf;
      if (!jsPDF) {
        showToast("PDF export not available", "error");
        return;
      }

      const doc = new jsPDF();
      let y = 10;

      res.history.forEach((msg) => {
        const label = msg.role === "user" ? "You" : assistantName;
        const text = `${label}: ${msg.content}`;
        const lines = doc.splitTextToSize(text, 180);

        lines.forEach((line) => {
          doc.text(line, 10, y);
          y += 7;
          if (y > 270) {
            doc.addPage();
            y = 10;
          }
        });

        y += 4;
      });

      doc.save("Theramind_Chat.pdf");
      showToast("PDF downloaded");
    })
    .catch(() => showToast("PDF export failed", "error"));
}

/* ======================================================
  ✏️ RENAME COMPANION
====================================================== */
function showRenameCompanionModal() {
  toggleModal("personaModal", true);
  const input = document.getElementById("personaNameInput");
  if (input) {
    input.value = assistantName;
    input.focus();
  }
}

function closePersonaModal() {
  toggleModal("personaModal", false);
}

/* Companion save button */
const personaSaveBtn = document.getElementById("setPersonaName");
if (personaSaveBtn) {
  personaSaveBtn.addEventListener("click", () => {
    const nameInput = document
      .getElementById("personaNameInput")
      .value.trim();
    if (!nameInput) return alert("Enter a name.");
    assistantName = nameInput;
    localStorage.setItem("assistantName", assistantName);
    closePersonaModal();
    showToast(`🤖 Companion renamed to "${assistantName}".`);
  });
}

/* ======================================================
  🔔 TOAST
====================================================== */
function showToast(msg) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;

  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}


function reloadParticlesForTheme() {
  if (window.tsParticles && tsParticles.domItem(0)) {
    tsParticles.domItem(0).destroy();
  }
  setTimeout(() => {
    initParticles(
      document.body.classList.contains("dark-theme") ? "dark" : "light"
    );
  }, 50);
}

function initParticles(theme = "light") {
  if (!window.tsParticles) return;
  const container = document.getElementById("particles-js");
  if (!container) return;

  const color = theme === "dark" ? "#8ab4f8" : "#6078ea";

  tsParticles.load("particles-js", {
    fullScreen: { enable: false },
    background: { color: { value: "transparent" } },
    particles: {
      number: { value: 80, density: { enable: true, area: 900 } },
      color: { value: color },
      shape: { type: "circle" },
      opacity: { value: 0.6, random: true },
      size: { value: { min: 1, max: 4 } },
      links: {
        enable: true,
        distance: 120,
        color: color,
        opacity: 0.3,
        width: 1,
      },
      move: {
        enable: true,
        speed: 0.8,
        outModes: { default: "bounce" },
      },
    },
    interactivity: {
      events: {
        onHover: { enable: false },
        onClick: { enable: false },
        resize: true,
      },
    },
    detectRetina: true,
  });
}

function toggleSidebarBackdrop(show) {
  let backdrop = document.querySelector(".sidebar-backdrop");

  if (show) {
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.className = "sidebar-backdrop";
      backdrop.addEventListener("click", () => {
        document.getElementById("sidebar").classList.add("hidden");
        document.getElementById("sidebar").classList.remove("show");
        document.body.classList.remove("sidebar-open");
        document.getElementById("sidebarToggle")
          ?.setAttribute("aria-expanded", "false");
        backdrop.remove();
      });
      document.body.appendChild(backdrop);
    }
  } else {
    if (backdrop) backdrop.remove();
  }
}

/* ======================================================
  🧩 SIDEBAR & NAV
====================================================== */
function setupSidebarAndNav() {
  const sidebar = document.getElementById("sidebar");
  const sidebarToggle = document.getElementById("sidebarToggle");

  if (!sidebar || !sidebarToggle) return;

  function syncSidebarWithViewport() {
    toggleSidebarBackdrop(false);
    sidebarToggle.setAttribute("aria-expanded", "false");
    if (window.innerWidth > 1024) {
      // Desktop: sidebar always visible
      sidebar.classList.remove("hidden");
      sidebar.classList.add("show");
      document.body.classList.remove("sidebar-open");
    } else {
      // Mobile / tablet: sidebar hidden by default
      sidebar.classList.add("hidden");
      sidebar.classList.remove("show");
      document.body.classList.remove("sidebar-open");
    }
  }

  // Toggle sidebar on button click
sidebarToggle.addEventListener("click", () => {
  const isMobile = window.innerWidth <= 1024;
  const willShow = sidebar.classList.contains("hidden");

  sidebar.classList.toggle("hidden", !willShow);
  sidebar.classList.toggle("show", willShow);

  sidebarToggle.setAttribute("aria-expanded", willShow);

  if (isMobile) {
    document.body.classList.toggle("sidebar-open", willShow);
    toggleSidebarBackdrop(willShow);
  }
});


  // Initial sync + resize handling
  syncSidebarWithViewport();
  window.addEventListener("resize", syncSidebarWithViewport);
}
/* ======================================================
  ✅ EVENT BINDINGS
====================================================== */
function bindCoreEvents() {
  const sendBtn = document.getElementById("send");
  const userInput = document.getElementById("user-input");
  const speakBtn = document.getElementById("speak");

  if (sendBtn) sendBtn.addEventListener("click", sendMessage);

  if (userInput) {
    userInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (speakBtn) speakBtn.addEventListener("click", startListening);

  const newChatBtn = document.getElementById("new-chat");
  const clearChatBtn = document.getElementById("clear-chat");
  const saveChatBtn = document.getElementById("save-chat");
  const viewSavedBtn = document.getElementById("view-saved");
  const exportChatBtn = document.getElementById("export-chat");
  const exportPDFBtn = document.getElementById("export-chat-pdf");
  const renameCompanionBtn = document.getElementById("rename-companion");

  if (newChatBtn) newChatBtn.addEventListener("click", newChat);
  if (clearChatBtn) clearChatBtn.addEventListener("click", clearChat);
  if (saveChatBtn) saveChatBtn.addEventListener("click", showSaveModal);
  if (viewSavedBtn) viewSavedBtn.addEventListener("click", showSavedChatsModal);
  if (exportChatBtn) exportChatBtn.addEventListener("click", exportChat);
  if (exportPDFBtn) exportPDFBtn.addEventListener("click", downloadChatPDF);
  if (renameCompanionBtn)
    renameCompanionBtn.addEventListener(
      "click",
      showRenameCompanionModal
    );
}
  // Theme toggle
const themeToggle = document.getElementById("themeToggle");

function applyThemeFromStorage() {
  const isDark = localStorage.getItem("theme") === "dark";
  document.body.classList.toggle("dark-theme", isDark);
  document.body.classList.toggle("light-theme", !isDark);
  if (themeToggle) {
    themeToggle.textContent = isDark ? "☀️ Theme" : "🌙 Theme";
  }
}

function toggleTheme() {
  const isDark = document.body.classList.toggle("dark-theme");
  document.body.classList.toggle("light-theme", !isDark);
  localStorage.setItem("theme", isDark ? "dark" : "light");
  if (themeToggle) {
    themeToggle.textContent = isDark ? "☀️ Theme" : "🌙 Theme";
  }
  reloadParticlesForTheme();
}


/* ======================================================
  🚀 INIT APP
====================================================== */
(function initApp() {
  applyThemeFromStorage();
if (themeToggle) {
  themeToggle.addEventListener("click", toggleTheme);
}


  assistantName = localStorage.getItem("assistantName") || "Theramind";

  // Initialize particles
initParticles(
  document.body.classList.contains("dark-theme") ? "dark" : "light"
);

  // Hide voice indicator initially
  const voiceIndicator = document.getElementById("voice-indicator");
  if (voiceIndicator) voiceIndicator.style.display = "none";



  // Core wiring
  bindCoreEvents();
  setupSidebarAndNav();

  // Initial welcome message
  const chatBox = document.getElementById("chat-box");
  if (chatBox && chatBox.children.length === 0) {
    appendMessage("bot", getPersonalizedGreeting());
  }

})();
