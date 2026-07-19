(function () {
  "use strict";

  const modeToggle = document.getElementById("modeToggle");
  const categorySelect = document.getElementById("categorySelect");
  const itemSelect = document.getElementById("itemSelect");
  const exampleChips = document.getElementById("exampleChips");
  const questionInput = document.getElementById("questionInput");
  const askBtn = document.getElementById("askBtn");
  const askIcon = document.getElementById("askIcon");
  const askSpinner = document.getElementById("askSpinner");
  const errorBanner = document.getElementById("errorBanner");
  const resultsArea = document.getElementById("resultsArea");
  const answerMeta = document.getElementById("answerMeta");
  const answerText = document.getElementById("answerText");
  const sourcesList = document.getElementById("sourcesList");
  const kgContainer = document.getElementById("kgContainer");
  const confidenceScore = document.getElementById("confidenceScore");
  const confidenceBand = document.getElementById("confidenceBand");
  const confidenceExplanation = document.getElementById("confidenceExplanation");
  const debugDetails = document.getElementById("debugDetails");
  const debugContent = document.getElementById("debugContent");

  let currentMode = "hybrid";

  function setMode(mode) {
    currentMode = mode;
    modeToggle.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.mode === mode));
    });
  }

  modeToggle.addEventListener("click", (e) => {
    const btn = e.target.closest(".mode-btn");
    if (btn) setMode(btn.dataset.mode);
  });

  function autoGrow() {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 200) + "px";
  }
  questionInput.addEventListener("input", autoGrow);

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.classList.remove("hidden");
  }
  function clearError() {
    errorBanner.classList.add("hidden");
    errorBanner.textContent = "";
  }

  let ENTITIES = { equipment: [], units: [] };

  function itemLabel(category, entity) {
    if (category === "equipment") {
      return entity.tag + " — " + entity.name + " (" + entity.unit_short + ")";
    }
    return entity.name + " (" + entity.short + ")";
  }

  function populateItemSelect() {
    const list = categorySelect.value === "unit" ? ENTITIES.units : ENTITIES.equipment;
    itemSelect.innerHTML = '<option value="">Select…</option>';
    list.forEach((entity) => {
      const opt = document.createElement("option");
      opt.value = entity.id;
      opt.textContent = itemLabel(categorySelect.value, entity);
      itemSelect.appendChild(opt);
    });
    renderSuggestions(null);
  }

  function buildSuggestions(category, entity) {
    if (category === "unit") {
      return [
        { question: "What equipment operates in the " + entity.name + " (" + entity.short + ")?", mode: "graph" },
        { question: "What incidents or inspection findings have been recorded in the " + entity.name + "?", mode: "hybrid" },
      ];
    }
    return [
      { question: "What is the design pressure and design temperature of equipment " + entity.tag + "?", mode: "vector" },
      { question: "Which SOP and safety procedure govern equipment " + entity.tag + " during maintenance?", mode: "graph" },
    ];
  }

  function renderSuggestions(entity) {
    exampleChips.innerHTML = "";
    if (!entity) return;
    buildSuggestions(categorySelect.value, entity).forEach((s) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "suggestion";
      chip.textContent = s.question;
      chip.addEventListener("click", () => {
        questionInput.value = s.question;
        autoGrow();
        setMode(s.mode);
        questionInput.focus();
      });
      exampleChips.appendChild(chip);
    });
  }

  categorySelect.addEventListener("change", populateItemSelect);
  itemSelect.addEventListener("change", () => {
    const category = categorySelect.value;
    const list = category === "unit" ? ENTITIES.units : ENTITIES.equipment;
    const entity = list.find((e) => e.id === itemSelect.value);
    renderSuggestions(entity || null);
  });

  async function loadEntities() {
    try {
      const res = await fetch("/api/entities");
      const data = await res.json();
      ENTITIES = { equipment: data.equipment || [], units: data.units || [] };
      populateItemSelect();
    } catch (err) {
      /* selectors are a nicety -- fail silently, the input still works */
    }
  }

  function renderSources(sources) {
    sourcesList.innerHTML = "";
    if (!sources || sources.length === 0) {
      const li = document.createElement("li");
      li.className = "empty-state";
      li.textContent = "No sources retrieved for this query.";
      sourcesList.appendChild(li);
      return;
    }
    sources.forEach((s) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.className = "source-card";
      a.href = s.url || "#";
      a.target = "_blank";
      a.rel = "noopener";
      a.innerHTML =
        '<span class="via-dot ' + s.via + '"></span>' +
        '<span class="doc-id">' + escapeHtml(s.doc_id || "unknown") + "</span>" +
        '<span class="source-path">' + escapeHtml(s.source_path || "") + "</span>";
      li.appendChild(a);
      sourcesList.appendChild(li);
    });
  }

  function renderConfidence(confidence) {
    confidenceScore.textContent = confidence.score;
    confidenceScore.className = "confidence-score " + confidence.band;
    confidenceBand.textContent = confidence.band;
    confidenceBand.className = "confidence-band " + confidence.band;
    confidenceExplanation.textContent = confidence.explanation;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function askQuestion() {
    const question = questionInput.value.trim();
    if (!question) {
      showError("Type a question first.");
      return;
    }
    clearError();
    resultsArea.classList.add("hidden");
    askBtn.disabled = true;
    askIcon.classList.add("hidden");
    askSpinner.classList.remove("hidden");

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          mode: currentMode,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.error || "Request failed (" + res.status + ")");
      }

      answerMeta.textContent =
        data.mode + "  ·  " + data.model + "  ·  " + data.timing.total_s + "s";
      answerText.textContent = data.answer;
      renderSources(data.sources);
      renderConfidence(data.confidence);
      window.FORGEGraph.render(kgContainer, data.graph);
      debugContent.textContent = JSON.stringify(
        { retrieval_meta: data.retrieval_meta, timing: data.timing }, null, 2
      );
      debugDetails.classList.remove("hidden");
      resultsArea.classList.remove("hidden");
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      askBtn.disabled = false;
      askIcon.classList.remove("hidden");
      askSpinner.classList.add("hidden");
    }
  }

  askBtn.addEventListener("click", askQuestion);
  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      askQuestion();
    }
  });

  setMode("hybrid");
  loadEntities();
})();
