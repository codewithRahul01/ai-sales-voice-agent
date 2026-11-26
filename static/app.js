// Voice loop:  mic → browser STT (Web Speech API) → POST /turn → reply → browser TTS → mic again.
// Half-duplex on purpose: the mic is paused while the agent speaks so it does not transcribe itself.
// Pressing the mic while the agent is speaking interrupts it (barge-in).
const $ = (id) => document.getElementById(id);
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let callId = null, rec = null, listening = false, speaking = false, interimEl = null, busy = false;

const FIELDS = [["phone", "Phone"], ["city", "City"], ["property_type", "Property"], ["is_owner", "Owner"],
  ["monthly_bill_inr", "Monthly bill (₹)"], ["timeline", "Timeline"], ["email", "Email"]];

async function api(path, body) {
  const r = await fetch(path, { method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}

function addMsg(role, text, meta) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.textContent = text;
  if (meta) { const m = document.createElement("span"); m.className = "meta"; m.textContent = meta; el.appendChild(m); }
  $("transcript").appendChild(el);
  $("transcript").scrollTop = 1e9;
  return el;
}
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const status = (t) => ($("status").textContent = t);

// ---------------- TTS ----------------
let currentUtterance = null;   // keep a reference: Chrome drops onend for garbage-collected utterances
function pickVoice(lang) {
  const voices = speechSynthesis.getVoices();
  return voices.find(v => v.lang === lang) || voices.find(v => v.lang.startsWith(lang.split("-")[0]));
}
function speak(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    currentUtterance = u;
    u.lang = $("lang").value; u.rate = 1.05;
    const v = pickVoice(u.lang); if (v) u.voice = v;
    speaking = true; status("Agent speaking… (press 🎙 to interrupt)");
    let done = false;
    const finish = () => { if (done) return; done = true; speaking = false; clearTimeout(guard); resolve(); };
    // Safety net: if Chrome never fires onend, continue after the expected speaking time
    const guard = setTimeout(finish, 2500 + text.length * 90);
    u.onend = u.onerror = finish;
    speechSynthesis.speak(u);
  });
}
speechSynthesis?.addEventListener?.("voiceschanged", () => {});

// ---------------- STT ----------------
const MIC_ERRORS = {
  "not-allowed": "Microphone blocked. Click the 🔒 icon in the address bar → Microphone → Allow, then reload. " +
                 "On a Mac also check System Settings → Privacy & Security → Microphone → enable your browser.",
  "service-not-allowed": "Speech recognition is blocked in this browser. Use Google Chrome.",
  "audio-capture": "No microphone found. Check System Settings → Sound → Input, and the macOS microphone permission.",
  "network": "Speech service unreachable. Brave/Arc/Opera don't support it - use Google Chrome, and check your internet.",
  "language-not-supported": "This language isn't supported for voice input in this browser. Try English or Hindi.",
};
function startListening() {
  if (!SR) { status("This browser has no voice input (Safari/Firefox). Open the page in Google Chrome, or type below."); return; }
  if (!callId || listening || busy) return;
  if (speaking) { speechSynthesis.cancel(); speaking = false; }   // barge-in
  rec = new SR();
  rec.lang = $("lang").value; rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
  let finalText = "", interimText = "", errored = false;
  rec.onresult = (e) => {
    interimText = "";
    for (const r of e.results) (r.isFinal ? (finalText = r[0].transcript) : (interimText += r[0].transcript));
    if (!interimEl) interimEl = addMsg("user interim", "");
    interimEl.textContent = finalText || interimText;
  };
  rec.onerror = (e) => {
    console.warn("SpeechRecognition error:", e.error, e.message);
    errored = true;
    status(e.error === "no-speech" ? "Didn't hear anything. Press 🎙 and speak." :
           e.error === "aborted" ? "Stopped listening." : (MIC_ERRORS[e.error] || "Mic error: " + e.error));
  };
  rec.onend = () => {
    listening = false; $("mic").classList.remove("listening");
    if (interimEl) { interimEl.remove(); interimEl = null; }
    const text = (finalText || interimText).trim();     // use the interim text if Chrome ended without a final result
    if (text) sendTurn(text);
    else if (!errored) status("Press 🎙 to talk.");
  };
  try {
    rec.start(); listening = true; $("mic").classList.add("listening"); status("Listening… speak now");
  } catch (err) { status("Could not start the microphone: " + err.message); }
}

// ---------------- Call flow ----------------
async function startCall() {
  $("transcript").innerHTML = ""; $("summarycard").hidden = true; $("booking").textContent = "Not booked yet.";
  $("sentiment").textContent = "–"; $("rag").textContent = "–";
  const r = await api("/api/calls", { phone: $("phone").value, language: $("lang").value });
  callId = r.call_id;
  $("brain").textContent = r.brain;
  renderLead(r.lead, r.lead.score, []);
  setActive(true);
  addMsg("assistant", r.greeting, r.returning_caller ? "returning caller: loaded CRM profile and past call summaries" : "");
  await speak(r.greeting);
  if ($("autolisten").checked) startListening();
}

async function sendTurn(text) {
  if (!callId || busy) return;
  busy = true;
  const userEl = addMsg("user", text);
  status("Thinking…");
  const t0 = performance.now();
  try {
    const r = await api(`/api/calls/${callId}/turn`, { text });
    const ms = Math.round(performance.now() - t0);
    userEl.appendChild(Object.assign(document.createElement("span"),
      { className: "meta", textContent: `${r.sentiment} · ${r.intent}` }));
    addMsg("assistant", r.reply, `${ms} ms`);
    renderLead(r.lead, r.score, r.score_reasons);
    renderSentiment(r);
    $("rag").innerHTML = r.retrieved.map(t => `<span class="pill">${esc(t)}</span>`).join(" ") || "–";
    if (r.booking) $("booking").innerHTML = `<span class="pill booked">Booked</span> Free site survey · <b>${esc(r.booking.label)}</b>`;
    busy = false;
    await speak(r.reply);
    if (r.ended) return finish(r.summary);
    if ($("autolisten").checked) startListening(); else status("Press 🎙 to talk.");
  } catch (e) { busy = false; status("Error: " + e.message); }
}

async function endCall() {
  if (!callId) return;
  speechSynthesis.cancel(); rec?.abort();
  status("Summarising call…");
  finish(await api(`/api/calls/${callId}/end`, {}));
}

function finish(s) {
  setActive(false); callId = null;
  status("Call ended. Summary saved to CRM.");
  $("summarycard").hidden = false;
  $("summary").innerHTML = `<p>${esc(s.summary)}</p>
    <p><b>Outcome:</b> <span class="pill ${s.outcome === "booked" ? "booked" : ""}">${s.outcome}</span>
       &nbsp;<b>Avg sentiment:</b> ${s.sentiment_score}</p>
    <p><b>Objections:</b> ${esc((s.objections || []).join(", ") || "none")}</p>
    <p><b>Next steps:</b> ${esc(s.next_steps)}</p>`;
}

const sentLog = [];
function renderSentiment(r) {
  sentLog.push(r.sentiment);
  $("sentiment").innerHTML = `Last turn: <span class="pill ${r.sentiment}">${r.sentiment}</span>
    intent <span class="pill">${r.intent}</span><br><span style="letter-spacing:2px">` +
    sentLog.slice(-20).map(s => s === "positive" ? "🟢" : s === "negative" ? "🔴" : "🟡").join("") + "</span>";
}

function renderLead(lead, score, reasons) {
  $("leadname").textContent = lead.name || "Unknown caller";
  $("leadstatus").textContent = lead.status; $("leadstatus").className = "pill " + lead.status;
  $("score").textContent = score; $("scorebar").style.width = score + "%";
  $("leadtable").innerHTML = FIELDS.map(([k, label]) => {
    let v = lead[k]; if (k === "is_owner") v = v === 1 ? "Yes" : v === 0 ? "No (tenant)" : null;
    return `<tr><th>${label}</th><td>${v == null ? "<span class='small'>–</span>" : esc(v)}</td></tr>`;
  }).join("");
  $("reasons").innerHTML = reasons.map(r => `<li>${esc(r)}</li>`).join("");
}

function setActive(on) {
  $("start").disabled = on; $("end").disabled = !on; $("mic").disabled = !on;
  $("text").disabled = !on; $("send").disabled = !on; $("phone").disabled = on; $("lang").disabled = on;
}

// ---------------- wiring ----------------
$("start").onclick = () => startCall().catch(e => status("Error: " + e.message));
$("end").onclick = endCall;
$("mic").onclick = () => (listening ? rec.stop() : startListening());
$("textform").onsubmit = (e) => { e.preventDefault(); const t = $("text").value.trim(); if (t) { $("text").value = ""; sendTurn(t); } };
api("/api/languages").then(l => $("lang").innerHTML = Object.entries(l).map(([k, v]) => `<option value="${k}">${v}</option>`).join(""));
api("/health").then(h => $("brain").textContent = h.brain);