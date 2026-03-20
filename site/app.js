const DATA_URL = "/site_data/brackets.json";
const API_BASE = "/api";
const LOCAL_STORAGE_KEY = "march-madness-ground-truth-fallback-v2";
const REGION_NAMES = ["East", "West", "South", "Midwest"];
const ROUND_NAMES = ["round_of_64", "round_of_32", "sweet_16", "elite_8"];
const ROUND_LABELS = {
  round_of_64: "Round of 64",
  round_of_32: "Round of 32",
  sweet_16: "Sweet 16",
  elite_8: "Elite 8",
  final_four: "Final Four",
  championship: "Championship",
};
const ROUND_POINTS = {
  round_of_64: 1,
  round_of_32: 2,
  sweet_16: 4,
  elite_8: 8,
  final_four: 16,
  championship: 32,
};

const state = {
  data: null,
  selectedBracketId: null,
  results: null,
  activeFieldKey: null,
  persistenceMode: "connecting",
  saveState: "idle",
  saveMessage: "",
  groundTruthOpen: false,
};

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error(`Could not load bracket data (${response.status}).`);
    }

    state.data = await response.json();
    const firstFile = state.data.files[0] || null;
    state.activeFieldKey = firstFile ? firstFile.field_key : null;
    state.selectedBracketId = firstFile?.brackets?.[0]?.id || null;
    state.results = await loadResults(state.activeFieldKey);
    bindActions();
    render();
  } catch (error) {
    document.body.innerHTML = `<div class="fatal-error">${escapeHtml(error instanceof Error ? error.message : "Failed to load the app.")}</div>`;
  }
});

function bindActions() {
  document.getElementById("open-methodology").addEventListener("click", openMethodologyModal);
  document.getElementById("close-methodology").addEventListener("click", closeMethodologyModal);
  document.getElementById("methodology-backdrop").addEventListener("click", closeMethodologyModal);
  document.getElementById("open-summary-stats").addEventListener("click", openSummaryModal);
  document.getElementById("close-summary-stats").addEventListener("click", closeSummaryModal);
  document.getElementById("summary-backdrop").addEventListener("click", closeSummaryModal);
  document.getElementById("jump-ground-truth").addEventListener("click", () => setGroundTruthOpen(true));
  document.getElementById("toggle-ground-truth").addEventListener("click", () => setGroundTruthOpen(!state.groundTruthOpen));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMethodologyModal();
      closeSummaryModal();
    }
  });
}

async function loadResults(fieldKey) {
  if (!fieldKey) {
    state.persistenceMode = "none";
    return createEmptyResults(fieldKey);
  }

  try {
    const response = await fetch(`${API_BASE}/ground-truth/${encodeURIComponent(fieldKey)}`);
    if (response.status === 404) {
      state.persistenceMode = "server";
      state.saveMessage = "Server connected. No saved results yet.";
      return createEmptyResults(fieldKey);
    }
    if (!response.ok) {
      throw new Error(`Ground truth load failed (${response.status}).`);
    }
    const payload = await response.json();
    state.persistenceMode = "server";
    state.saveMessage = `Loaded from database. Updated ${new Date(payload.updatedAt).toLocaleString()}.`;
    return payload.results;
  } catch (_error) {
    state.persistenceMode = "local";
    state.saveMessage = "API unavailable. Using browser-local fallback storage.";
    return loadLocalResults(fieldKey) || createEmptyResults(fieldKey);
  }
}

async function persistResults() {
  state.saveState = "saving";
  renderSyncStatus();

  if (state.persistenceMode === "server") {
    try {
      const response = await fetch(`${API_BASE}/ground-truth/${encodeURIComponent(state.activeFieldKey)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ results: state.results }),
      });
      if (!response.ok) {
        throw new Error(`Save failed (${response.status}).`);
      }
      const payload = await response.json();
      state.saveState = "saved";
      state.saveMessage = `Saved to database at ${new Date(payload.updatedAt).toLocaleTimeString()}.`;
      renderSyncStatus();
      return;
    } catch (_error) {
      state.persistenceMode = "local";
      state.saveMessage = "Database save failed. Switched to browser-local fallback.";
    }
  }

  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(state.results));
  state.saveState = "saved";
  renderSyncStatus();
}

function loadLocalResults(fieldKey) {
  const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  const parsed = JSON.parse(raw);
  return parsed.fieldKey === fieldKey ? parsed : null;
}

function render() {
  renderSyncStatus();
  renderHero();
  renderLegend();
  renderSummaryStats();
  renderLeaderboard();
  renderSelectedBracket();
}

function renderSyncStatus() {
  const node = document.getElementById("sync-status");
  if (!node) {
    return;
  }
  const modeLabel = {
    connecting: "Connecting",
    server: "Database-backed",
    local: "Local fallback",
    none: "Unavailable",
  }[state.persistenceMode] || "Unknown";
  const suffix = state.saveState === "saving" ? "Saving changes…" : state.saveMessage;
  node.textContent = `${modeLabel}: ${suffix || "Ready."}`;
}

function openMethodologyModal() {
  const modal = document.getElementById("methodology-modal");
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeMethodologyModal() {
  const modal = document.getElementById("methodology-modal");
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

function openSummaryModal() {
  const modal = document.getElementById("summary-modal");
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeSummaryModal() {
  const modal = document.getElementById("summary-modal");
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

function renderHero() {
  const allBrackets = getAllBrackets();
  const completedGames = countCompletedGames(state.results);
  document.getElementById("hero-stats").innerHTML = [
    statCard("Files", state.data.files.length),
    statCard("Brackets", allBrackets.length),
    statCard("Games entered", `${completedGames}/63`),
    statCard("Field", humanizeFieldKey(state.activeFieldKey)),
  ].join("");
}

function renderLegend() {
  document.getElementById("score-legend").textContent = Object.entries(ROUND_POINTS)
    .map(([roundName, points]) => `${ROUND_LABELS[roundName]} ${points}`)
    .join(" / ");
}

function renderSummaryStats() {
  const groups = [
    { label: "All brackets", brackets: getAllBrackets(), showAllChampions: true },
    ...state.data.files.map((file) => ({
      label: file.group_name || file.file_name,
      brackets: file.brackets,
      showAllChampions: false,
    })),
  ];

  document.getElementById("summary-stats").innerHTML = groups.map((group) => {
    const scores = group.brackets.map((bracket) => scoreBracket(bracket));
    const variance = calculateVariance(scores);
    const averageScore = average(scores);
    const champions = championSummary(group.brackets, { limit: group.showAllChampions ? null : 3 });
    const selectionVariance = computeSelectionVariance(group.brackets);
    return `
      <div class="summary-card">
        <div class="summary-card-header">
          <div class="summary-card-title">${escapeHtml(group.label)}</div>
          <div class="summary-card-count">${group.brackets.length}</div>
        </div>
        <div class="summary-card-meta">Avg score ${averageScore.toFixed(1)} · Variance ${variance.toFixed(1)}</div>
        <div class="summary-card-meta">Pick disagreement ${(selectionVariance.disagreementRate * 100).toFixed(1)}% · Unique champions ${selectionVariance.uniqueChampions}</div>
        <div class="summary-card-meta">Avg game consensus ${(selectionVariance.averageConsensus * 100).toFixed(1)}% · Champion consensus ${(selectionVariance.championConsensus * 100).toFixed(1)}%</div>
        <div class="summary-card-label">${group.showAllChampions ? "Champions picked across all brackets" : "Most-picked champions"}</div>
        <div class="summary-card-winners">${champions}</div>
      </div>
    `;
  }).join("");
}

function setGroundTruthOpen(open) {
  state.groundTruthOpen = open;
  const toggle = document.getElementById("toggle-ground-truth");
  if (toggle) {
    toggle.textContent = state.groundTruthOpen ? "View bracket" : "Enter ground truth";
  }
  renderSelectedBracket();
}

function renderLeaderboard() {
  const rows = getAllBrackets()
    .map((bracket) => ({ bracket, score: scoreBracket(bracket) }))
    .sort((left, right) => right.score - left.score || left.bracket.title.localeCompare(right.bracket.title));

  document.getElementById("leaderboard").innerHTML = rows.map((entry, index) => `
    <button class="leaderboard-card ${entry.bracket.id === state.selectedBracketId ? "active" : ""}" data-bracket-id="${escapeAttribute(entry.bracket.id)}">
      <div class="leaderboard-card-top">
        <div class="leaderboard-rank">#${index + 1}</div>
        <div class="leaderboard-score">${entry.score}</div>
      </div>
      <div class="leaderboard-title">${escapeHtml(entry.bracket.title)}</div>
      <div class="leaderboard-subtitle">${escapeHtml(entry.bracket.champion || "Unknown")}</div>
    </button>
  `).join("");

  document.querySelectorAll(".leaderboard-card[data-bracket-id]").forEach((button) => {
    button.addEventListener("click", () => selectBracket(button.dataset.bracketId));
  });
}

function selectBracket(bracketId) {
  state.selectedBracketId = bracketId;
  renderLeaderboard();
  renderSelectedBracket();
}

function renderSelectedBracket() {
  const bracket = getSelectedBracket();
  const titleNode = document.getElementById("selected-bracket-title");
  const metaNode = document.getElementById("selected-bracket-meta");
  const summaryNode = document.getElementById("selected-bracket-summary");
  const viewNode = document.getElementById("selected-bracket-view");

  if (!bracket) {
    titleNode.textContent = "Choose a bracket";
    metaNode.textContent = "";
    summaryNode.textContent = "";
    viewNode.className = "selected-bracket-view empty-state";
    viewNode.textContent = "Pick a bracket to see the full board.";
    return;
  }

  if (state.groundTruthOpen) {
    const mode = state.persistenceMode === "server" ? "database" : "browser";
    titleNode.textContent = "Ground truth editor";
    metaNode.textContent = `Click the team that won each game. Double-click the selected winner to clear it. Saving to ${mode}.`;
    summaryNode.textContent = "Later rounds unlock automatically as earlier winners are entered, and downstream rounds reset when you change or clear an earlier result.";
  } else {
    titleNode.textContent = bracket.title;
    metaNode.textContent = `Champion ${bracket.champion} · ${scoreBracket(bracket)} points`;
    summaryNode.textContent = bracket.summary || "";
  }
  viewNode.className = "selected-bracket-view";
  viewNode.innerHTML = state.groundTruthOpen ? renderGroundTruthBoard() : renderBracketBoard(bracket);
  if (state.groundTruthOpen) {
    bindGroundTruthBoardActions();
  }
}

function renderBracketBoard(bracket) {
  return `
    <div class="bracket-board">
      <div class="region-board board-east">${renderRegionBoard(bracket, "East")}</div>
      <div class="region-board board-west">${renderRegionBoard(bracket, "West")}</div>
      <div class="region-board board-south">${renderRegionBoard(bracket, "South")}</div>
      <div class="region-board board-midwest">${renderRegionBoard(bracket, "Midwest")}</div>
      <div class="finals-board">${renderFinalsBoard(bracket)}</div>
    </div>
  `;
}

function renderRegionBoard(bracket, regionName) {
  const isMirrored = regionName === "West" || regionName === "Midwest";
  const rounds = isMirrored ? [...ROUND_NAMES].reverse() : ROUND_NAMES;
  return `
    <div class="region-board-header">
      <h3>${regionName}</h3>
    </div>
    <div class="region-columns ${isMirrored ? "mirrored" : ""}">
      ${rounds.map((roundName) => `
        <div class="round-column">
          <div class="round-column-label">${ROUND_LABELS[roundName]}</div>
          <div class="pick-stack">
            ${(bracket.regions?.[regionName]?.[roundName] || []).map((pick, index) => renderPickChip(pick, getTruthWinner(regionName, roundName, index))).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderFinalsBoard(bracket) {
  const semifinalPicks = getBracketSemifinals(bracket);
  const titlePick = getBracketChampionship(bracket);
  return `
    <div class="finals-header">
      <p class="kicker">Final path</p>
      <h3>${escapeHtml(bracket.champion || "TBD")}</h3>
    </div>
    <div class="finals-section">
      <div class="round-column-label">${ROUND_LABELS.final_four}</div>
      <div class="pick-stack">
        ${semifinalPicks.map((pick, index) => renderPickChip(pick, getTruthWinner("Finals", "final_four", index))).join("")}
      </div>
    </div>
    <div class="finals-section">
      <div class="round-column-label">${ROUND_LABELS.championship}</div>
      <div class="pick-stack">${renderPickChip(titlePick, getTruthWinner("Finals", "championship", 0))}</div>
    </div>
    <div class="champion-lockup">
      <span class="champion-label">Champion</span>
      <span class="champion-name">${escapeHtml(bracket.champion || "TBD")}</span>
      <span class="champion-runner-up">Runner-up: ${escapeHtml(bracket.runner_up || "TBD")}</span>
    </div>
  `;
}

function renderGroundTruthBoard() {
  return `
    <div class="bracket-board ground-truth-board">
      <div class="region-board board-east">${renderGroundTruthRegionBoard("East")}</div>
      <div class="region-board board-west">${renderGroundTruthRegionBoard("West")}</div>
      <div class="region-board board-south">${renderGroundTruthRegionBoard("South")}</div>
      <div class="region-board board-midwest">${renderGroundTruthRegionBoard("Midwest")}</div>
      <div class="finals-board">${renderGroundTruthFinalsBoard()}</div>
    </div>
  `;
}

function renderGroundTruthRegionBoard(regionName) {
  const isMirrored = regionName === "West" || regionName === "Midwest";
  const rounds = isMirrored ? [...ROUND_NAMES].reverse() : ROUND_NAMES;
  return `
    <div class="region-board-header">
      <h3>${regionName}</h3>
    </div>
    <div class="region-columns ${isMirrored ? "mirrored" : ""}">
      ${rounds.map((roundName) => `
        <div class="round-column">
          <div class="round-column-label">${ROUND_LABELS[roundName]}</div>
          <div class="pick-stack">
            ${buildRegionGames(regionName, roundName).map((game, index) => renderGroundTruthGameChip(regionName, roundName, index, game)).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderGroundTruthFinalsBoard() {
  const finalGames = buildFinalFourGames();
  return `
    <div class="finals-header">
      <p class="kicker">Ground truth</p>
      <h3>Final rounds</h3>
    </div>
    <div class="finals-section">
      <div class="round-column-label">${ROUND_LABELS.final_four}</div>
      <div class="pick-stack">
        ${finalGames.semifinals.map((game, index) => renderGroundTruthGameChip("Finals", "final_four", index, game)).join("")}
      </div>
    </div>
    <div class="finals-section">
      <div class="round-column-label">${ROUND_LABELS.championship}</div>
      <div class="pick-stack">${renderGroundTruthGameChip("Finals", "championship", 0, finalGames.championship)}</div>
    </div>
  `;
}

function renderGroundTruthGameChip(regionName, roundName, index, game) {
  const selectedWinner = getTruthWinner(regionName, roundName, index);
  const enabled = game.teams.length === 2;
  return `
    <div class="pick-chip ground-truth-chip">
      <div class="pick-chip-teams">
        ${renderGroundTruthTeamSlot(regionName, roundName, index, game.teams[0], selectedWinner, enabled)}
        <div class="pick-chip-vs">vs</div>
        ${renderGroundTruthTeamSlot(regionName, roundName, index, game.teams[1], selectedWinner, enabled)}
      </div>
    </div>
  `;
}

function renderGroundTruthTeamSlot(regionName, roundName, index, teamLabel, selectedWinner, enabled) {
  const selected = teamLabel && normalizeTeamLabel(teamLabel) === normalizeTeamLabel(selectedWinner);
  return `
    <button
      class="team-slot ground-truth-team-slot ${selected ? "team-slot-selected" : ""}"
      data-gt-path="${escapeAttribute(`${regionName}|${roundName}|${index}`)}"
      data-team="${escapeAttribute(teamLabel || "")}"
      type="button"
      ${!enabled || !teamLabel ? "disabled" : ""}
    >
      ${escapeHtml(teamLabel || "TBD")}
    </button>
  `;
}

function bindGroundTruthBoardActions() {
  document.querySelectorAll("[data-gt-path][data-team]").forEach((button) => {
    button.addEventListener("click", onGroundTruthTeamClick);
    button.addEventListener("dblclick", onGroundTruthTeamDoubleClick);
  });
}

async function onGroundTruthTeamClick(event) {
  const button = event.currentTarget;
  const [regionName, roundName, rawIndex] = button.dataset.gtPath.split("|");
  const index = Number(rawIndex);
  const team = button.dataset.team || null;
  setTruthWinner(regionName, roundName, index, team);
  clearDependentResults(regionName, roundName);
  await rerenderAndPersistResults();
}

async function onGroundTruthTeamDoubleClick(event) {
  const button = event.currentTarget;
  const [regionName, roundName, rawIndex] = button.dataset.gtPath.split("|");
  const index = Number(rawIndex);
  const team = button.dataset.team || null;
  const currentWinner = getTruthWinner(regionName, roundName, index);
  if (!team || normalizeTeamLabel(team) !== normalizeTeamLabel(currentWinner)) {
    return;
  }

  setTruthWinner(regionName, roundName, index, null);
  clearDependentResults(regionName, roundName);
  await rerenderAndPersistResults();
}

async function rerenderAndPersistResults() {
  renderHero();
  renderLeaderboard();
  renderSummaryStats();
  renderSelectedBracket();
  await persistResults();
}

function renderPickChip(pick, truthWinner) {
  const status = getPickStatus(pick?.winner, truthWinner);
  const matchup = parseMatchup(pick?.matchup);
  return `
    <div class="pick-chip ${status.className}">
      <div class="pick-chip-teams">
        ${renderTeamSlot(matchup.top, pick?.winner)}
        <div class="pick-chip-vs">vs</div>
        ${renderTeamSlot(matchup.bottom, pick?.winner)}
      </div>
      <div class="pick-chip-footer">
        ${pick?.reason ? `<span class="pick-chip-info" tabindex="0">Why<span class="pick-chip-tooltip">${escapeHtml(pick.reason)}</span></span>` : ""}
      </div>
    </div>
  `;
}

function renderTeamSlot(teamLabel, winner) {
  const selected = teamLabel && normalizeTeamLabel(teamLabel) === normalizeTeamLabel(winner);
  return `
    <div class="team-slot ${selected ? "team-slot-selected" : ""}">
      ${escapeHtml(teamLabel || "TBD")}
    </div>
  `;
}

function parseMatchup(matchup) {
  if (!matchup || !matchup.includes(" vs ")) {
    return { top: matchup || "TBD", bottom: "TBD" };
  }
  const [top, bottom] = matchup.split(" vs ", 2);
  return { top, bottom };
}

function normalizeTeamLabel(label) {
  if (!label) {
    return "";
  }
  const trimmed = String(label).trim();
  const seedStripped = trimmed.replace(/^\d+\s+/, "");
  return seedStripped.replace(/\s+/g, " ").toLowerCase();
}

function getSelectedBracket() {
  return getAllBrackets().find((bracket) => bracket.id === state.selectedBracketId) || null;
}

function getAllBrackets() {
  return state.data.files.flatMap((file) => file.brackets);
}

function getActiveField() {
  return state.data.fields[state.activeFieldKey] || null;
}

function createEmptyResults(fieldKey) {
  return {
    fieldKey,
    regions: Object.fromEntries(REGION_NAMES.map((regionName) => [regionName, {
      round_of_64: Array(8).fill(null),
      round_of_32: Array(4).fill(null),
      sweet_16: Array(2).fill(null),
      elite_8: Array(1).fill(null),
    }])),
    finals: {
      final_four: Array(2).fill(null),
      championship: Array(1).fill(null),
    },
  };
}

function buildRegionGames(regionName, roundName) {
  const field = getActiveField();
  if (!field) {
    return [];
  }

  if (roundName === "round_of_64") {
    return field.regions[regionName].map((game) => ({
      teams: [game.team, game.opponent],
      label: `${game.seed} ${game.team} vs ${game.matchup_seed} ${game.opponent}`,
    }));
  }

  const previousRound = ROUND_NAMES[ROUND_NAMES.indexOf(roundName) - 1];
  const previousGames = buildRegionGames(regionName, previousRound);
  const games = [];
  for (let index = 0; index < previousGames.length; index += 2) {
    const teams = [getTruthWinner(regionName, previousRound, index), getTruthWinner(regionName, previousRound, index + 1)].filter(Boolean);
    games.push({
      teams,
      label: teams.length === 2 ? `${teams[0]} vs ${teams[1]}` : "Waiting on prior winners",
    });
  }
  return games;
}

function buildFinalFourGames() {
  const semifinalTeams = [
    [getTruthWinner("East", "elite_8", 0), getTruthWinner("West", "elite_8", 0)].filter(Boolean),
    [getTruthWinner("South", "elite_8", 0), getTruthWinner("Midwest", "elite_8", 0)].filter(Boolean),
  ];
  const championshipTeams = [getTruthWinner("Finals", "final_four", 0), getTruthWinner("Finals", "final_four", 1)].filter(Boolean);
  return {
    semifinals: semifinalTeams.map((teams) => ({
      teams,
      label: teams.length === 2 ? `${teams[0]} vs ${teams[1]}` : "Waiting on regional champions",
    })),
    championship: {
      teams: championshipTeams,
      label: championshipTeams.length === 2 ? `${championshipTeams[0]} vs ${championshipTeams[1]}` : "Waiting on semifinal winners",
    },
  };
}

function getTruthWinner(regionName, roundName, index) {
  if (regionName === "Finals") {
    return state.results.finals[roundName][index];
  }
  return state.results.regions[regionName][roundName][index];
}

function setTruthWinner(regionName, roundName, index, winner) {
  if (regionName === "Finals") {
    state.results.finals[roundName][index] = winner;
  } else {
    state.results.regions[regionName][roundName][index] = winner;
  }
}

function clearDependentResults(regionName, roundName) {
  if (regionName === "Finals") {
    if (roundName === "final_four") {
      state.results.finals.championship = [null];
    }
    return;
  }

  const roundIndex = ROUND_NAMES.indexOf(roundName);
  for (let index = roundIndex + 1; index < ROUND_NAMES.length; index += 1) {
    state.results.regions[regionName][ROUND_NAMES[index]] = state.results.regions[regionName][ROUND_NAMES[index]].map(() => null);
  }
  state.results.finals.final_four = [null, null];
  state.results.finals.championship = [null];
}

function scoreBracket(bracket) {
  let total = 0;
  REGION_NAMES.forEach((regionName) => {
    ROUND_NAMES.forEach((roundName) => {
      (bracket.regions?.[regionName]?.[roundName] || []).forEach((pick, index) => {
        if (pick.winner && pick.winner === getTruthWinner(regionName, roundName, index)) {
          total += ROUND_POINTS[roundName];
        }
      });
    });
  });
  getBracketSemifinals(bracket).forEach((pick, index) => {
    if (pick.winner && pick.winner === getTruthWinner("Finals", "final_four", index)) {
      total += ROUND_POINTS.final_four;
    }
  });
  const titlePick = getBracketChampionship(bracket);
  if (titlePick.winner && titlePick.winner === getTruthWinner("Finals", "championship", 0)) {
    total += ROUND_POINTS.championship;
  }
  return total;
}

function getBracketSemifinals(bracket) {
  const finalFour = bracket.final_four || [];
  const champion = bracket.champion;
  const runnerUp = bracket.runner_up;
  return [finalFour.slice(0, 2), finalFour.slice(2, 4)].map((teams) => ({
    matchup: teams.length === 2 ? `${teams[0]} vs ${teams[1]}` : "TBD",
    winner: teams.includes(champion) ? champion : teams.includes(runnerUp) ? runnerUp : null,
    reason: "Derived from Final Four and title-game picks.",
  }));
}

function getBracketChampionship(bracket) {
  return {
    matchup: bracket.champion && bracket.runner_up ? `${bracket.champion} vs ${bracket.runner_up}` : "TBD",
    winner: bracket.champion || null,
    reason: "Champion pick.",
  };
}

function getPickStatus(predictedWinner, truthWinner) {
  if (!truthWinner) {
    return { label: "Pending", className: "status-pending" };
  }
  if (predictedWinner === truthWinner) {
    return { label: "Correct", className: "status-correct" };
  }
  return { label: "Wrong", className: "status-wrong" };
}

function countCompletedGames(results) {
  let total = 0;
  REGION_NAMES.forEach((regionName) => {
    ROUND_NAMES.forEach((roundName) => {
      total += results.regions[regionName][roundName].filter(Boolean).length;
    });
  });
  total += results.finals.final_four.filter(Boolean).length;
  total += results.finals.championship.filter(Boolean).length;
  return total;
}

function humanizeFieldKey(fieldKey) {
  if (!fieldKey) {
    return "Unknown";
  }
  const [year, gender] = fieldKey.split("-");
  return `${year} ${gender}`;
}

function statCard(label, value) {
  return `
    <div class="stat-card">
      <span class="stat-label">${escapeHtml(label)}</span>
      <span class="stat-value">${escapeHtml(String(value))}</span>
    </div>
  `;
}

function average(values) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function calculateVariance(values) {
  if (!values.length) {
    return 0;
  }
  const mean = average(values);
  return values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
}

function championSummary(brackets, { limit = 3 } = {}) {
  const counts = new Map();
  brackets.forEach((bracket) => {
    const champion = bracket.champion || "Unknown";
    counts.set(champion, (counts.get(champion) || 0) + 1);
  });
  let entries = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  if (typeof limit === "number") {
    entries = entries.slice(0, limit);
  }
  return entries
    .map(([champion, count]) => `${escapeHtml(champion)} ${count}`)
    .join(" · ");
}

function computeSelectionVariance(brackets) {
  if (!brackets.length) {
    return {
      disagreementRate: 0,
      averageConsensus: 0,
      uniqueChampions: 0,
      championConsensus: 0,
    };
  }

  const gameBuckets = [];
  REGION_NAMES.forEach((regionName) => {
    ROUND_NAMES.forEach((roundName) => {
      const gameCount = brackets[0].regions?.[regionName]?.[roundName]?.length || 0;
      for (let index = 0; index < gameCount; index += 1) {
        gameBuckets.push(brackets.map((bracket) => bracket.regions?.[regionName]?.[roundName]?.[index]?.winner || ""));
      }
    });
  });

  const semifinalCount = 2;
  for (let index = 0; index < semifinalCount; index += 1) {
    gameBuckets.push(brackets.map((bracket) => getBracketSemifinals(bracket)[index]?.winner || ""));
  }
  gameBuckets.push(brackets.map((bracket) => bracket.champion || ""));

  const consensusValues = gameBuckets
    .map((bucket) => bucketConsensus(bucket))
    .filter((value) => value > 0);
  const averageConsensus = consensusValues.length ? average(consensusValues) : 0;

  const championCounts = new Map();
  brackets.forEach((bracket) => {
    const champion = bracket.champion || "Unknown";
    championCounts.set(champion, (championCounts.get(champion) || 0) + 1);
  });
  const championConsensus = bucketConsensus(brackets.map((bracket) => bracket.champion || ""));

  return {
    disagreementRate: 1 - averageConsensus,
    averageConsensus,
    uniqueChampions: championCounts.size,
    championConsensus,
  };
}

function bucketConsensus(values) {
  if (!values.length) {
    return 0;
  }
  const counts = new Map();
  values.forEach((value) => {
    counts.set(value, (counts.get(value) || 0) + 1);
  });
  let maxCount = 0;
  counts.forEach((count) => {
    if (count > maxCount) {
      maxCount = count;
    }
  });
  return maxCount / values.length;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
