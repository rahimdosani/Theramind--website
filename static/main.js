/******************************************************** 
 * Theramind Chat – main.js (Final Ready Version)
 ********************************************************/

let recognition = null;
let isListening = false;
let preferredVoice = null;
let isSpeaking = false;
let currentUtterance = null;
let waitingIndicator = null;
let assistantName = localStorage.getItem("assistantName") || "Theramind";

/* ======================================================
  🎤 SPEECH RECOGNITION
====================================================== */
function initRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return alert("⚠️ Speech recognition not supported.");

  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isListening = true;
    document.getElementById("voice-indicator").style.display = "block";
    document.getElementById("speak").textContent = "⏹️ Stop";
  };

  recognition.onend = () => {
    isListening = false;
    document.getElementById("voice-indicator").style.display = "none";
    document.getElementById("speak").textContent = "🎙️ Speak";
    const message = document.getElementById("user-input").value.trim();
    if (message) sendMessage();
  };

  recognition.onerror = e => { console.error(e); stopListening(); };

  recognition.onresult = event => {
    let interim = "", final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) final += event.results[i][0].transcript;
      else interim += event.results[i][0].transcript;
    }
    document.getElementById("user-input").value = final || interim;
  };
}

function startListening() {
  if (!recognition) initRecognition();
  if (!isListening) recognition.start();
  else stopListening();
}

function stopListening() {
  if (recognition && isListening) recognition.stop();
}

/* ======================================================
  🎙️ VOICE OUTPUT
====================================================== */
function getPreferredVoice() {
  const voices = speechSynthesis.getVoices();
  return (
    voices.find(v => v.name.toLowerCase().includes("female")) ||
    voices.find(v => v.lang.startsWith("en")) ||
    voices[0] || null
  );
}

function speakOut(text, btn = null) {
  if (!window.speechSynthesis) return;
  if (!preferredVoice) { 
    preferredVoice = getPreferredVoice(); 
    if (!preferredVoice) return setTimeout(() => speakOut(text, btn), 200); 
  }
  if (isSpeaking) speechSynthesis.cancel();

  currentUtterance = new SpeechSynthesisUtterance(text);
  currentUtterance.voice = preferredVoice;
  currentUtterance.lang = "en-GB";
  currentUtterance.pitch = 1.05;
  currentUtterance.rate = 0.95;

  currentUtterance.onend = () => { 
    isSpeaking = false; 
    if (btn) btn.textContent = "🔊"; 
  };
  isSpeaking = true;
  if (btn) btn.textContent = "⏹️";
  speechSynthesis.speak(currentUtterance);
}

function speakOutButton(e) {
  const btn = e.target;
  const text = btn.getAttribute("data-text");
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
  const div = document.createElement("div");
  div.className = `message ${role}`;
  const label = role === "user" ? "You" : assistantName;
  const safeContent = content.replace(/"/g, '&quot;');
  const speakBtn = role === "bot" ? `<button class="speak-btn" data-text="${safeContent}" onclick="speakOutButton(event)">🔊</button>` : "";
  const time = timestamp || formatTimestamp(new Date());
  div.innerHTML = `${label}: <span class="chat-text">${safeContent}</span> ${speakBtn}<div class="timestamp">${time}</div>`;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function sanitizeText(text) {
  return text.replace(/[*_~`]/g,'').trim();
}

function showTyping() {
  if (!waitingIndicator) {
    waitingIndicator = document.createElement("div");
    waitingIndicator.className = "message bot typing-indicator";
    waitingIndicator.textContent = `${assistantName} is typing...`;
    document.getElementById("chat-box").appendChild(waitingIndicator);
    document.getElementById("chat-box").scrollTop = document.getElementById("chat-box").scrollHeight;
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
  const message = input.value.trim();
  if (!message) return;

  appendMessage("user", message);
  input.value = "";
  showTyping();

  fetch("/chat", { 
    method: "POST", 
    headers: { "Content-Type": "application/json" }, 
    body: JSON.stringify({ message }) 
  })
    .then(res => res.ok ? res.json() : Promise.reject("Network error"))
    .then(data => { 
      hideTyping(); 
      appendMessage("bot", sanitizeText(data.reply)); 
      saveToLocal(message, data.reply); 
    })
    .catch(err => { 
      hideTyping(); 
      console.error(err); 
      appendMessage("bot", "⚠️ Something went wrong. Try again."); 
    });
}

/* ======================================================
  🆕 CHAT CONTROLS
====================================================== */
function newChat() {
  document.getElementById("chat-box").innerHTML = '';
  localStorage.removeItem("chatHistory");
  localStorage.removeItem("activeChatId");
  appendMessage("bot", `Hello! I'm here for you. How are you feeling today?`);
}

function clearChat() { newChat(); }

/* ======================================================
  💾 SAVED CHATS & MODALS
====================================================== */
function toggleModal(modalId, show = true) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.toggle("active", show);
}

function closeSaveModal() { toggleModal("saveChatModal", false); }
function closeSavedChatsModal() { toggleModal("savedChatsModal", false); }

function showSaveModal() { 
  toggleModal("saveChatModal", true); 
  const input = document.getElementById("chatTitleInput");
  input.focus();
  input.addEventListener("keydown", handleSaveEnter);
}

function handleSaveEnter(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    saveChat();
    e.target.removeEventListener("keydown", handleSaveEnter);
  }
}

function saveChat() {
  const title = document.getElementById("chatTitleInput").value.trim();
  if (!title) return showToast("Enter a title for your chat!");

  const history = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  if (!history.length) return showToast("Cannot save empty chat.");

  fetch("/save_conversation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, history })
  })
    .then(res => res.ok ? res.json() : Promise.reject("Failed"))
    .then(() => { 
      showToast("✅ Chat saved!"); 
      closeSaveModal();
      showSavedChatsModal(); 
    })
    .catch(err => { 
      console.error(err); 
      showToast("⚠️ Failed to save chat."); 
    });
}

function showSavedChatsModal() {
  fetch("/get_conversations")
    .then(res => res.ok ? res.json() : Promise.reject("Failed"))
    .then(chats => {
      const list = document.getElementById("savedChatsList");
      if (!chats.length) {
        list.innerHTML = `<p style="text-align:center;color:var(--foreground);">No saved chats</p>`;
        toggleModal("savedChatsModal", true);
        return;
      }
      list.innerHTML = chats.map(c => `
        <div class="chat-item" data-id="${c.id}">
          <span class="chat-title" onclick="loadConversation(event, ${c.id})">${c.title}</span>
          <div class="chat-actions">
            <button class="rename-btn" onclick="renameChat(event, ${c.id})">✏️</button>
            <button class="delete-btn" onclick="deleteConversation(event, ${c.id})">🗑️</button>
          </div>
        </div>
      `).join('');
      toggleModal("savedChatsModal", true);
    })
    .catch(err => { 
      console.error(err); 
      showToast("⚠️ Failed to load saved chats."); 
    });
}

function loadConversation(e, id) {
  e.stopPropagation();
  document.getElementById("chat-box").innerHTML = '';
  localStorage.setItem("activeChatId", id);

  fetch(`/load_conversation/${id}`)
    .then(res => res.ok ? res.json() : Promise.reject("Failed"))
    .then(history => { 
      history.forEach(msg => appendMessage(msg.role, sanitizeText(msg.content), msg.timestamp)); 
      localStorage.setItem("chatHistory", JSON.stringify(history)); 
      closeSavedChatsModal(); 
    })
    .catch(err => { 
      console.error(err); 
      showToast("⚠️ Failed to load conversation."); 
    });
}

function deleteConversation(e, id) {
  e.stopPropagation();
  fetch(`/delete_conversation/${id}`, { method: "DELETE" })
    .then(res => res.ok ? res.json() : Promise.reject("Failed"))
    .then(() => { 
      showToast("🗑️ Chat deleted!"); 
      showSavedChatsModal(); 
    })
    .catch(err => { 
      console.error(err); 
      showToast("⚠️ Failed to delete chat."); 
    });
}

function renameChat(e, id) {
  e.stopPropagation();
  const newName = prompt("Enter new chat name:");
  if (!newName) return;
  
  fetch(`/rename_conversation/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: newName })
  })
    .then(res => res.ok ? res.json() : Promise.reject("Failed"))
    .then(() => { 
      showToast("✏️ Chat renamed!"); 
      showSavedChatsModal(); 
    })
    .catch(err => { 
      console.error(err); 
      showToast("⚠️ Failed to rename chat."); 
    });
}

/* ======================================================
  🚀 EXPORT CHAT
====================================================== */
function exportChat() {
  const history = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  if (!history.length) return showToast("No chat to export.");
  const blob = new Blob([JSON.stringify(history, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "chat_export.json";
  a.click();
  URL.revokeObjectURL(url);
  showToast("Chat exported!");
}

/* ======================================================
  📄 DOWNLOAD CHAT AS PDF
====================================================== */
function downloadChatPDF() {
  const history = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  if (!history.length) return showToast("No chat to export.");

  const { jsPDF } = window.jspdf || {};
  if (!jsPDF) return showToast("⚠️ jsPDF library not loaded.");

  const doc = new jsPDF();
  let y = 10;

  history.forEach(msg => {
    const label = msg.role === "user" ? "You" : assistantName;
    const text = `${label}: ${msg.content}`;
    const lines = doc.splitTextToSize(text, 180); // Wrap text
    lines.forEach(line => {
      doc.text(line, 10, y);
      y += 6;
      if (y > 280) { doc.addPage(); y = 10; }
    });
    y += 2;
  });

  doc.save("Theramind_Chat.pdf");
  showToast("✅ PDF downloaded!");
}

/* ======================================================
  ✏️ RENAME COMPANION
====================================================== */
function showRenameCompanionModal() {
  toggleModal("personaModal", true);
  document.getElementById("personaNameInput").value = assistantName;
  document.getElementById("personaNameInput").focus();
}

function closePersonaModal() { toggleModal("personaModal", false); }

document.getElementById("setPersonaName").addEventListener("click", () => {
  const nameInput = document.getElementById("personaNameInput").value.trim();
  if (!nameInput) return alert("Enter a name.");
  assistantName = nameInput;
  localStorage.setItem("assistantName", assistantName);
  closePersonaModal();
  showToast(`🤖 Companion renamed to "${assistantName}"`);
});

/* ======================================================
  🔔 TOAST
====================================================== */
function showToast(msg) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

/* ======================================================
  🌗 THEME TOGGLE + PARTICLES
====================================================== */
function setTheme(mode) {
  document.body.classList.toggle("dark-theme", mode === "dark");
  document.body.classList.toggle("light-theme", mode === "light");
  localStorage.setItem("theme", mode);
  document.querySelectorAll(".theme-toggle input").forEach(input => { 
    input.checked = input.value === mode; 
  });
  reloadParticlesForTheme();
}

function reloadParticlesForTheme() {
  tsParticles.domItem(0)?.destroy();
  initParticles(document.body.classList.contains("dark-theme") ? "dark" : "light");
}

function initParticles(theme = "light") {
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
      links: { enable: true, distance: 120, color, opacity: 0.3, width: 1 },
      move: { enable: true, speed: 0.8, outModes: { default: "bounce" } }
    },
    interactivity: {
      events: { onHover: { enable: false }, onClick: { enable: false }, resize: true }
    },
    detectRetina: true
  });
}

/* ======================================================
  ⏱️ UTILITIES
====================================================== */
function formatTimestamp(date) { 
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); 
}

function saveToLocal(userMsg, botMsg) {
  let history = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  history.push({ role: "user", content: userMsg, timestamp: formatTimestamp(new Date()) });
  history.push({ role: "bot", content: botMsg, timestamp: formatTimestamp(new Date()) });
  localStorage.setItem("chatHistory", JSON.stringify(history));
}

/* ======================================================
  🧩 SIDEBAR
====================================================== */
document.getElementById("sidebarToggle").addEventListener("click", () => { 
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.toggle("hidden"); 
});

/* ======================================================
  ✅ EVENT BINDINGS
====================================================== */
document.getElementById("send").addEventListener("click", sendMessage);
document.getElementById("user-input").addEventListener("keydown", e => { 
  if (e.key === "Enter" && !e.shiftKey) { 
    e.preventDefault(); 
    sendMessage(); 
  } 
});
document.getElementById("speak").addEventListener("click", startListening);
document.getElementById("new-chat").addEventListener("click", newChat);
document.getElementById("clear-chat").addEventListener("click", clearChat);
document.getElementById("save-chat").addEventListener("click", showSaveModal);
document.getElementById("view-saved").addEventListener("click", showSavedChatsModal);
document.getElementById("export-chat").addEventListener("click", exportChat);
document.getElementById("rename-companion").addEventListener("click", showRenameCompanionModal);
document.getElementById("cancel-save")?.addEventListener("click", closeSaveModal);
document.getElementById("close-saved-chats")?.addEventListener("click", closeSavedChatsModal);
document.getElementById("export-chat-pdf").addEventListener("click", downloadChatPDF);

document.querySelectorAll('.theme-toggle input').forEach(input =>
  input.addEventListener('change', () => setTheme(input.value))
);

/* ======================================================
  🚀 INIT APP
====================================================== */
(function initApp() {
  setTheme(localStorage.getItem("theme") || "light");
  assistantName = localStorage.getItem("assistantName") || "Theramind";

  const history = JSON.parse(localStorage.getItem("chatHistory") || "[]");
  if (history.length === 0) {
    appendMessage("bot", `Hello! I'm here for you. How are you feeling today?`);
  } else {
    history.forEach(msg => appendMessage(msg.role, msg.content, msg.timestamp));
  }

  initParticles(localStorage.getItem("theme") || "light");

  document.getElementById("voice-indicator").style.display = "none";

  const activeChatId = localStorage.getItem("activeChatId");
  if (activeChatId) loadConversation({ stopPropagation: () => {} }, activeChatId);
})();
// Hamburger toggle for mobile nav
  document.addEventListener("DOMContentLoaded", function() {
    const hamburger = document.querySelector('.tm-hamburger');
    const nav = document.querySelector('.tm-nav');

    if (hamburger && nav) {
      hamburger.addEventListener('click', function() {
        nav.classList.toggle('show-links');
      });
    }
  });


