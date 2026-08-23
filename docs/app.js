(() => {
  "use strict";

  const state = {
    data: null,
    activeTypes: new Set(),
    studio: "",
    day: "",
    freeOnly: false,
  };

  const els = {
    typeFilters: document.getElementById("type-filters"),
    studioFilter: document.getElementById("studio-filter"),
    dayFilter: document.getElementById("day-filter"),
    freeOnlyFilter: document.getElementById("free-only-filter"),
    resultCount: document.getElementById("result-count"),
    grid: document.getElementById("lessons-grid"),
    emptyState: document.getElementById("empty-state"),
    generatedAt: document.getElementById("generated-at"),
  };

  const DAY_LABELS = ["Ne", "Po", "Út", "St", "Čt", "Pá", "So"];

  function formatDay(isoDate) {
    const d = new Date(isoDate + "T00:00:00");
    if (Number.isNaN(d.getTime())) return isoDate;
    return `${DAY_LABELS[d.getDay()]} ${d.getDate()}. ${d.getMonth() + 1}.`;
  }

  function formatGeneratedAt(iso) {
    if (!iso) return "Data zatím nebyla načtena — první aktualizace proběhne po prvním běhu scraperu.";
    const d = new Date(iso);
    return `Data aktualizována: ${d.toLocaleString("cs-CZ", { dateStyle: "medium", timeStyle: "short" })}`;
  }

  function capacityBadge(lesson) {
    const { capacity_free, capacity_total } = lesson;
    if (capacity_free === null || capacity_free === undefined) {
      return { cls: "unknown", text: "Kapacita neznámá" };
    }
    if (capacity_free <= 0) {
      return { cls: "full", text: "Obsazeno" };
    }
    const totalText = capacity_total ? `/${capacity_total}` : "";
    return { cls: "free", text: `${capacity_free}${totalText} volných` };
  }

  function buildTypeChips(lessons) {
    const types = Array.from(new Set(lessons.map((l) => l.class_type))).sort();
    els.typeFilters.innerHTML = "";
    types.forEach((type) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = type;
      btn.setAttribute("aria-pressed", "false");
      btn.addEventListener("click", () => {
        if (state.activeTypes.has(type)) {
          state.activeTypes.delete(type);
          btn.classList.remove("active");
          btn.setAttribute("aria-pressed", "false");
        } else {
          state.activeTypes.add(type);
          btn.classList.add("active");
          btn.setAttribute("aria-pressed", "true");
        }
        render();
      });
      els.typeFilters.appendChild(btn);
    });
  }

  function buildStudioOptions(studios) {
    studios
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, "cs"))
      .forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = s.name;
        els.studioFilter.appendChild(opt);
      });
  }

  function buildDayOptions(lessons) {
    const days = Array.from(new Set(lessons.map((l) => l.date))).sort();
    days.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = formatDay(d);
      els.dayFilter.appendChild(opt);
    });
  }

  function matchesFilters(lesson) {
    if (state.activeTypes.size > 0 && !state.activeTypes.has(lesson.class_type)) return false;
    if (state.studio && lesson.studio_id !== state.studio) return false;
    if (state.day && lesson.date !== state.day) return false;
    if (state.freeOnly && !(lesson.capacity_free > 0)) return false;
    return true;
  }

  function renderCard(lesson) {
    const card = document.createElement("article");
    card.className = "lesson-card";

    const badge = capacityBadge(lesson);
    const timeLabel = lesson.start_time ? `${formatDay(lesson.date)} · ${lesson.start_time}` : formatDay(lesson.date);

    card.innerHTML = `
      <div class="lesson-card__top">
        <p class="lesson-card__name">${escapeHtml(lesson.class_name)}</p>
        <span class="tag">${escapeHtml(lesson.class_type)}</span>
      </div>
      <p class="lesson-card__studio">${escapeHtml(lesson.studio_name)}${lesson.address ? " · " + escapeHtml(lesson.address) : ""}</p>
      <p class="lesson-card__when">${escapeHtml(timeLabel)}${lesson.instructor ? " · " + escapeHtml(lesson.instructor) : ""}</p>
      <div class="lesson-card__meta">
        <span class="capacity ${badge.cls}">${badge.text}</span>
        ${lesson.booking_url ? `<a class="book-link" href="${escapeAttr(lesson.booking_url)}" target="_blank" rel="noopener">Rezervovat →</a>` : ""}
      </div>
    `;
    return card;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, "&quot;");
  }

  function render() {
    const lessons = state.data.lessons
      .filter(matchesFilters)
      .sort((a, b) => (a.date + (a.start_time || "")).localeCompare(b.date + (b.start_time || "")));

    els.grid.innerHTML = "";
    lessons.forEach((lesson) => els.grid.appendChild(renderCard(lesson)));

    els.resultCount.textContent = lessons.length
      ? `Zobrazeno ${lessons.length} ${lessons.length === 1 ? "lekce" : lessons.length < 5 ? "lekce" : "lekcí"}`
      : "";

    const noDataAtAll = state.data.lessons.length === 0;
    els.emptyState.hidden = lessons.length > 0;
    if (lessons.length === 0) {
      els.emptyState.textContent = noDataAtAll
        ? "Zatím tu nejsou žádná data. Aggregátor sbírá rozvrhy automaticky na pozadí — zkuste to prosím za chvíli."
        : "Žádná lekce neodpovídá zvoleným filtrům. Zkuste jiný typ, den nebo studio.";
    }
  }

  async function init() {
    try {
      const res = await fetch("./data/lessons.json", { cache: "no-store" });
      state.data = await res.json();
    } catch (err) {
      state.data = { generated_at: null, studios: [], lessons: [] };
    }

    buildTypeChips(state.data.lessons);
    buildStudioOptions(state.data.studios);
    buildDayOptions(state.data.lessons);
    els.generatedAt.textContent = formatGeneratedAt(state.data.generated_at);

    els.studioFilter.addEventListener("change", (e) => {
      state.studio = e.target.value;
      render();
    });
    els.dayFilter.addEventListener("change", (e) => {
      state.day = e.target.value;
      render();
    });
    els.freeOnlyFilter.addEventListener("change", (e) => {
      state.freeOnly = e.target.checked;
      render();
    });

    render();
  }

  init();
})();
