let currentCardId = null;
const statusEls = {
  upload: document.getElementById("uploadStatus"),
  context: document.getElementById("contextStatus"),
};

const detailEls = {
  firstName: document.getElementById("firstName"),
  lastName: document.getElementById("lastName"),
  company: document.getElementById("company"),
  logo: document.getElementById("logo"),
  email: document.getElementById("email"),
  phone: document.getElementById("phone"),
  address: document.getElementById("address"),
  timestamp: document.getElementById("cardTimestamp"),
  currentCardName: document.getElementById("currentCardName"),
  summaryContext: document.getElementById("summaryContext"),
  summaryPriorities: document.getElementById("summaryPriorities"),
  summaryNotes: document.getElementById("summaryNotes"),
  summaryImage: document.getElementById("summaryImage"),
};

const forms = {
  upload: document.getElementById("uploadForm"),
  context: document.getElementById("contextForm"),
};

function setStatus(el, message, tone = "muted") {
  if (!el) return;
  el.textContent = message;
  el.className = `status ${tone}`;
}

function renderValue(el, value) {
  if (!el) return;
  el.textContent = value || "—";
  if (value) {
    el.classList.remove("muted");
  } else {
    el.classList.add("muted");
  }
}

function renderCard(card) {
  currentCardId = card.id;
  renderValue(detailEls.firstName, card.first_name);
  renderValue(detailEls.lastName, card.last_name);
  renderValue(detailEls.company, card.company);
  renderValue(detailEls.logo, card.company_logo_description);
  renderValue(detailEls.email, card.email);
  renderValue(detailEls.phone, card.phone);
  renderValue(detailEls.address, card.address);
  renderValue(detailEls.timestamp, card.captured_at);
  detailEls.currentCardName.textContent = `${card.first_name || "Contact"} ${
    card.last_name || ""
  }`;

  document.getElementById("meetingContext").value = card.meeting_context || "";
  document.getElementById("priorities").value = card.priorities || "";
  document.getElementById("personalNotes").value = card.personal_notes || "";

  renderValue(detailEls.summaryContext, card.meeting_context);
  renderValue(detailEls.summaryPriorities, card.priorities);
  renderValue(detailEls.summaryNotes, card.personal_notes);

  if (card.summary_image_url) {
    detailEls.summaryImage.src = card.summary_image_url;
    detailEls.summaryImage.alt = `Summary portrait for ${card.first_name || "contact"}`;
  } else {
    detailEls.summaryImage.removeAttribute("src");
    detailEls.summaryImage.alt = "Summary portrait";
  }
}

async function uploadCard(event) {
  event.preventDefault();
  const fileInput = document.getElementById("cardFile");
  if (!fileInput.files.length) {
    setStatus(statusEls.upload, "Please choose a photo.", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  setStatus(statusEls.upload, "Extracting details…", "muted");

  try {
    const res = await fetch("/api/cards", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderCard(data);
    setStatus(statusEls.upload, "Card processed successfully.", "success");
    await refreshTable();
  } catch (error) {
    console.error(error);
    setStatus(statusEls.upload, "Upload failed. Please try again.", "error");
  }
}

async function submitContext(event) {
  event.preventDefault();
  if (!currentCardId) {
    setStatus(statusEls.context, "Upload a card first.", "error");
    return;
  }
  setStatus(statusEls.context, "Saving and generating portrait…", "muted");

  const payload = {
    meeting_context: document.getElementById("meetingContext").value,
    priorities: document.getElementById("priorities").value,
    personal_notes: document.getElementById("personalNotes").value,
  };

  try {
    const res = await fetch(`/api/cards/${currentCardId}/context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderCard(data);
    setStatus(statusEls.context, "Notes saved and image generated.", "success");
    await refreshTable();
  } catch (error) {
    console.error(error);
    setStatus(statusEls.context, "Could not save notes. Try again.", "error");
  }
}

async function refreshTable() {
  const tbody = document.getElementById("cardsTableBody");
  tbody.innerHTML = "";
  try {
    const res = await fetch("/api/cards");
    if (!res.ok) throw new Error(await res.text());
    const cards = await res.json();
    if (!cards.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="muted">No contacts yet.</td></tr>`;
      return;
    }
    cards.forEach((card) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${[card.first_name, card.last_name].filter(Boolean).join(" ") || "Unknown"}</td>
        <td>${card.company || "—"}</td>
        <td>${card.captured_at || "—"}</td>
        <td><button class="secondary" data-id="${card.id}">Load</button></td>
      `;
      row.querySelector("button").addEventListener("click", async () => {
        const selected = await fetch(`/api/cards/${card.id}`);
        if (selected.ok) {
          const data = await selected.json();
          renderCard(data);
        }
      });
      tbody.appendChild(row);
    });
  } catch (error) {
    console.error(error);
    tbody.innerHTML = `<tr><td colspan="4" class="muted">Unable to load contacts.</td></tr>`;
  }
}

forms.upload.addEventListener("submit", uploadCard);
forms.context.addEventListener("submit", submitContext);
refreshTable();
