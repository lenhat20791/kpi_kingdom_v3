(() => {
    const API = "/api/study-spire/pvp";
    const token = localStorage.getItem("access_token") || localStorage.getItem("token");
    const state = { roomCode: null, rankedMatchId: null, rankedBatch: 0, spectator: false, pollTimer: null, lobbyPollTimer: null, pollBusy: false };
    const byId = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[char]);

    async function api(path, options = {}) {
        const response = await fetch(`${API}${path}`, {
            ...options,
            headers: {
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
                ...(options.headers || {}),
            },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.message || `Máy chủ trả lỗi ${response.status}.`);
        return data;
    }

    async function rankedApi(path, options = {}) {
        const response = await fetch(`/api/study-spire/ranked${path}`, {
            ...options,
            headers: {
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
                ...(options.headers || {}),
            },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.message || `Máy chủ trả lỗi ${response.status}.`);
        return data;
    }

    function setStatus(message, kind = "") {
        const status = byId("pvp-status");
        status.textContent = message || "";
        status.className = `inline-status ${kind}`.trim();
    }

    function suddenDeathNoticeKey(snapshot) {
        const playerId = snapshot.viewer_role === "guest"
            ? snapshot.room.guest_player_id
            : snapshot.room.host_player_id;
        return `${snapshot.match_id || snapshot.room.room_code}:${playerId}`;
    }

    function renderRankedBoard(board) {
        const content = byId("pvp-content");
        const player = board.player;
        const ownRank = player.rank_position;
        const canStartMatch = !board.active_match_id && !board.rank_locked_by_match;
        const opponentRows = board.opponents.map(opponent => `<article class="ranked-opponent">
            <img src="${escapeHtml(opponent.avatar_url || "/assets/images/avatars/default.png")}" alt="" loading="lazy">
            <div class="ranked-player-info"><strong>${escapeHtml(opponent.name)}</strong><small>${opponent.rank_position ? `Hạng #${opponent.rank_position}` : "Chưa xếp hạng"}</small></div>
            <button class="primary-button compact" type="button" data-rank-challenge="${opponent.player_id}" ${canStartMatch ? "" : "disabled"}>THÁCH ĐẤU</button>
        </article>`).join("");
        const topRows = board.top_players.map(entry => {
            const isSelf = entry.player_id === player.player_id;
            const canChallenge = ownRank && canStartMatch && !entry.rank_busy && !isSelf && ownRank - entry.rank_position > 0 && ownRank - entry.rank_position <= board.opponent_batch_size;
            return `<article class="ranked-board-row ${isSelf ? "is-self" : ""}">
            <span class="ranked-place">${entry.rank_position}</span>
            <img src="${escapeHtml(entry.avatar_url || "/assets/images/avatars/default.png")}" alt="" loading="lazy">
            <strong>${escapeHtml(entry.name)}${isSelf ? " · BẠN" : ""}</strong>
            <button class="secondary-button compact" type="button" data-rank-challenge="${entry.player_id}" ${canChallenge ? "" : "disabled"} title="${canChallenge ? "Thách đấu người ở hạng này" : isSelf ? "Đây là hạng của bạn" : "Chỉ có thể đấu ba người ngay phía trên"}>${isSelf ? "BẠN" : "THÁCH ĐẤU"}</button>
        </article>`;
        }).join("");
        const placement = board.placement_required
            ? `<section class="ranked-challenge-panel"><div class="ranked-panel-heading"><div><p class="eyebrow">BƯỚC KHỞI ĐẦU</p><h2>Trận phân hạng · ${player.placement_matches}/${board.placement_matches_required}</h2></div></div>
                <p>Hoàn thành ${board.placement_matches_required} trận với bot dùng deck người chơi khác để vào bảng. ${board.placement_uses_score ? "Khi giai đoạn phân hạng đầu tiên còn diễn ra, số trận thắng quyết định thứ tự xuất phát; nếu bằng nhau, người hoàn thành trước đứng trên." : "Sau khi bảng xếp hạng đã bắt đầu, người mới vào bảng ở cuối danh sách."}</p>
                <div class="ranked-opponent-list">${opponentRows || `<p class="pvp-empty-state">Chưa có người chơi khác để phân hạng.</p>`}</div>
                ${board.has_next_opponent_batch ? `<button class="secondary-button compact" id="ranked-next-opponents" type="button">ĐỔI NGƯỜI ↻</button>` : ""}
            </section>`
            : `<section class="ranked-challenge-panel"><div class="ranked-panel-heading"><div><p class="eyebrow">HẠNG CỦA BẠN</p><h2>${ownRank ? `#${ownRank}` : "Chưa xếp hạng"}</h2></div></div>
                ${board.rank_locked_by_match ? `<p>Đang có trận đấu ảnh hưởng tới thứ hạng của bạn.</p>` : ownRank === 1 ? `<p>Bạn đang dẫn đầu bảng xếp hạng!</p>` : `<p>Chọn một trong ba người đứng ngay phía trên. Thắng sẽ đổi hạng với đối thủ; thua không làm thay đổi thứ hạng.</p>`}
                <div class="ranked-opponent-list">${opponentRows || (ownRank === 1 || board.rank_locked_by_match ? "" : `<p class="pvp-empty-state">Hiện chưa có đối thủ phía trên phù hợp.</p>`)}</div>
                ${board.has_next_opponent_batch ? `<button class="secondary-button compact" id="ranked-next-opponents" type="button">ĐỔI NGƯỜI ↻</button>` : ""}
            </section>`;
        content.innerHTML = `<div class="ranked-toolbar"><div><p class="eyebrow">HỌC GIẢ ĐẠI CHIẾN · LEADERBOARD</p><h2>Bảng xếp hạng</h2><p>Đang có ${board.ranked_player_count} người đã phân hạng · Hiển thị Top 20</p></div>
                <button class="secondary-button compact" id="ranked-open-rooms" type="button">ĐẤU PHÒNG PvP</button></div>
            ${board.active_match_id ? `<div class="ranked-active-match"><span>Bạn có trận xếp hạng chưa hoàn tất.</span><button class="primary-button compact" id="ranked-resume" type="button">TIẾP TỤC</button></div>` : board.rank_locked_by_match ? `<div class="ranked-active-match"><span>Hạng của bạn đang được thách đấu. Bạn có thể xem bảng nhưng chưa thể mở trận leo hạng khác.</span></div>` : ""}
            <div class="ranked-layout"><section class="ranked-board"><div class="ranked-board-heading"><span>HẠNG</span><span>NGƯỜI CHƠI</span></div>${topRows || `<p class="pvp-empty-state">Chưa có người chơi hoàn thành phân hạng.</p>`}</section>${placement}</div>`;
        content.querySelectorAll("[data-rank-challenge]").forEach(button => button.addEventListener("click", () => startRankedMatch(Number(button.dataset.rankChallenge))));
        content.querySelector("#ranked-next-opponents")?.addEventListener("click", () => openRankedBoard(state.rankedBatch + 1));
        content.querySelector("#ranked-open-rooms")?.addEventListener("click", openRoomsLobby);
        content.querySelector("#ranked-resume")?.addEventListener("click", () => openRankedMatch(board.active_match_id));
    }

    function stopPolling() {
        if (state.pollTimer) clearInterval(state.pollTimer);
        if (state.lobbyPollTimer) clearInterval(state.lobbyPollTimer);
        state.pollTimer = null;
        state.lobbyPollTimer = null;
        state.pollBusy = false;
    }

    function renderSeat(seat, snapshot, viewerId) {
        const isViewer = seat.player_id === viewerId;
        const hand = seat.hand;
        const handHtml = Array.isArray(hand)
            ? hand.map((card) => `<button type="button" class="pvp-hand-card" data-pvp-card="${escapeHtml(card.instance_id)}" ${!snapshot.can_act || !isViewer ? "disabled" : ""}>${window.renderCard({ id: card.instance_id, name: card.name, cost: card.mana_cost, type: card.type, rarity: card.rarity, artUrl: card.image_url, description: card.description, effect_tooltips: card.effect_tooltips })}</button>`).join("")
            : `<div class="pvp-hidden-hand" aria-label="Bài đối thủ được ẩn">${Array.from({ length: Math.min(seat.hand_count, 5) }, () => `<span class="pvp-card-back">▧</span>`).join("")}<small>${seat.hand_count} lá trên tay</small></div>`;
        const effects = (seat.active_effects || []).map(effect => effect.type === "poison" ? `☠ ${effect.stacks} Độc` : effect.type === "vulnerable" ? `◇ ${effect.stacks} Yếu Đuối` : effect.type).join(" · ");
        const relics = (seat.relics || []).map(relic => `<span class="pvp-seat-relic" title="${escapeHtml(relic.name)}"><img src="${escapeHtml(relic.image_url)}" alt="">${escapeHtml(relic.name)}</span>`).join("");
        return `<article class="pvp-seat ${seat.is_active ? "is-active" : ""}">
            <header><div><span class="pvp-seat-role">${isViewer ? "BẠN" : snapshot.spectator ? "NGƯỜI CHƠI" : "ĐỐI THỦ"}</span><h3>${escapeHtml(seat.name)}</h3></div><span class="pvp-turn-badge">${seat.is_active ? "ĐANG ĐI LƯỢT" : "CHỜ LƯỢT"}</span></header>
            <div class="pvp-vitals"><span>♥ ${seat.hp}/${seat.hp_max}</span><span>🛡 ${seat.shield}</span><span>✦ ${seat.mana}/${seat.mana_max}</span><span>Deck ${seat.draw_count}</span></div>
            <p class="pvp-effects">${escapeHtml(effects || "Không có hiệu ứng")}</p>
            ${relics ? `<div class="pvp-seat-relics">${relics}</div>` : ""}
            <div class="pvp-hand">${handHtml || `<span class="pvp-hidden-hand">Không có lá trên tay</span>`}</div>
        </article>`;
    }

    function renderBattleRoom(snapshot) {
        const battle = snapshot.battle;
        const currentUserId = snapshot.viewer_role === "host"
            ? snapshot.room.host_player_id
            : snapshot.viewer_role === "guest"
                ? snapshot.room.guest_player_id
                : null;
        const canControl = snapshot.can_act && !snapshot.spectator;
        const winnerSeat = battle.winner_player_id ? battle.players.find(seat => Number(seat.player_id) === Number(battle.winner_player_id)) : null;
        const suddenDeathAcknowledged = state.suddenDeathAcknowledgedFor === suddenDeathNoticeKey(snapshot);
        const seats = battle.players.map(seat => renderSeat(seat, snapshot, currentUserId)).join("");
        const logs = (battle.log || []).slice(-8).reverse().map(entry => `<li>${entry.type === "card_played"
            ? `${escapeHtml(entry.card_name)} · ${escapeHtml(battle.players.find(seat => seat.player_id === entry.player_id)?.name || "Người chơi")}`
            : entry.type === "sudden_death_started"
                ? "Cái chết bất ngờ bắt đầu · sát thương được nhân đôi"
                : `${escapeHtml(battle.players.find(seat => seat.player_id === entry.player_id)?.name || "Người chơi")} bị bỏ lượt`}</li>`).join("");
        const rankResult = snapshot.rank_result || {};
        const resultDetails = snapshot.match_type === "PLACEMENT"
            ? ` · Phân hạng ${rankResult.placement_matches || 0}/${3}${rankResult.rank_changed ? ` · Bạn vào bảng ở hạng #${rankResult.new_rank}` : ""}`
            : rankResult.rank_changed ? ` · Bạn hiện ở hạng #${rankResult.player_rank}` : "";
        const viewerWon = currentUserId !== null && winnerSeat && Number(winnerSeat.player_id) === Number(currentUserId);
        const resultScreen = winnerSeat ? `<section class="pvp-result-screen ${currentUserId === null ? "is-spectator" : viewerWon ? "is-win" : "is-lose"}" role="status" aria-live="polite">
            <p class="eyebrow">KẾT QUẢ TRẬN ĐẤU</p>
            <h2>${currentUserId === null ? `${escapeHtml(winnerSeat.name)} CHIẾN THẮNG` : viewerWon ? "CHIẾN THẮNG" : "THẤT BẠI"}</h2>
            <p>${currentUserId === null ? "Bạn đang xem kết quả trận đấu." : viewerWon ? "Bạn đã thắng trận đấu này." : `${escapeHtml(winnerSeat.name)} đã thắng trận đấu.`}${escapeHtml(resultDetails)}</p>
        </section>` : "";
        const suddenDeathNotice = battle.sudden_death && !snapshot.spectator && !suddenDeathAcknowledged
            ? `<div class="result-modal" role="alertdialog" aria-modal="true" aria-labelledby="pvp-sudden-death-title" aria-describedby="pvp-sudden-death-message">
                <section class="result-panel pvp-sudden-death-panel">
                    <p class="eyebrow">LUẬT TRẬN ĐẤU THAY ĐỔI</p>
                    <h2 id="pvp-sudden-death-title">Cái chết bất ngờ</h2>
                    <p id="pvp-sudden-death-message">Sau 20 lượt chưa phân thắng thua. Từ lượt này, sát thương từ đòn đánh và hiệu ứng gây lên đối thủ được nhân đôi.</p>
                    <button class="primary-button" type="button" data-pvp-sudden-death-confirm>ĐÃ RÕ, TIẾP TỤC</button>
                </section>
            </div>`
            : "";
        return `<div class="pvp-battle-view">
            <div class="pvp-room-header"><div><p class="eyebrow">${snapshot.match_id ? "ĐẤU BOT · DECK ĐỐI THỦ ĐÃ LƯU" : `PHÒNG #${escapeHtml(snapshot.room.room_code)} · ${snapshot.spectator ? "GÓC NHÌN QUAN CHIẾN" : "ĐANG ĐẤU"}`}</p><h2>${escapeHtml(snapshot.room.room_name)}</h2></div><button class="secondary-button compact" data-pvp-leave>${snapshot.match_id ? snapshot.status === "FINISHED" ? "VỀ BẢNG XẾP HẠNG" : "ĐẦU HÀNG / THOÁT" : snapshot.spectator ? "RỜI QUAN CHIẾN" : snapshot.status === "FINISHED" ? "RỜI PHÒNG" : "ĐẦU HÀNG / THOÁT"}</button></div>
            ${snapshot.spectator ? `<p class="pvp-spectator-banner">Bạn đang ở góc nhìn thượng đế: thấy hand của cả hai bên, không thể tác động trận đấu.</p>` : ""}
            ${battle.sudden_death ? `<p class="pvp-sudden-death-banner" role="status">CÁI CHẾT BẤT NGỜ · SÁT THƯƠNG x2</p>` : ""}
            ${resultScreen}
            <div class="pvp-battle-board">${seats}</div>
            <div class="pvp-battle-controls">${winnerSeat ? `<span>Trận đấu đã kết thúc.</span>` : snapshot.spectator ? `<span>Đang quan chiến · Lượt ${battle.turn_number}</span>` : canControl ? `<span>Lượt ${battle.turn_number} của bạn</span><button class="primary-button" data-pvp-end-turn>KẾT THÚC LƯỢT <span>→</span></button>` : `<span>Đang chờ đối thủ thực hiện lượt…</span>`}</div>
            <details class="pvp-battle-log"><summary>Nhật ký trận</summary><ol>${logs || "<li>Trận đấu vừa bắt đầu.</li>"}</ol></details>
            ${suddenDeathNotice}
        </div>`;
    }

    function renderRoom(snapshot) {
        const content = byId("pvp-content");
        const room = snapshot.room;
        if (snapshot.battle?.sudden_death && !snapshot.spectator) {
            const noticeKey = suddenDeathNoticeKey(snapshot);
            if (state.suddenDeathAcknowledgedFor !== noticeKey) {
                if (state.suddenDeathNoticeShownFor === noticeKey) return;
                state.suddenDeathNoticeShownFor = noticeKey;
            }
        }
        if (snapshot.status === "ACTIVE" || snapshot.status === "FINISHED") {
            if (snapshot.status === "FINISHED" && state.pollTimer) {
                clearInterval(state.pollTimer);
                state.pollTimer = null;
            }
            content.innerHTML = renderBattleRoom(snapshot);
            content.querySelectorAll("[data-pvp-card]").forEach(button => button.addEventListener("click", () => playCard(button.dataset.pvpCard, snapshot)));
            content.querySelector("[data-pvp-end-turn]")?.addEventListener("click", () => endTurn(snapshot));
            content.querySelector("[data-pvp-leave]")?.addEventListener("click", () => state.rankedMatchId ? forfeitRankedMatch(snapshot) : leaveRoom(snapshot));
            content.querySelector("[data-pvp-sudden-death-confirm]")?.addEventListener("click", () => {
                state.suddenDeathAcknowledgedFor = suddenDeathNoticeKey(snapshot);
                renderRoom(snapshot);
            });
            return;
        }

        const host = `<div class="pvp-player-slot ${room.host_ready ? "is-ready" : ""}"><span>CHỦ PHÒNG</span><strong>${escapeHtml(room.host_name)}</strong><small>${room.host_ready ? "✓ Sẵn sàng" : "Đang chờ sẵn sàng"}</small></div>`;
        const guest = room.guest_name
            ? `<div class="pvp-player-slot ${room.guest_ready ? "is-ready" : ""}"><span>ĐỐI THỦ</span><strong>${escapeHtml(room.guest_name)}</strong><small>${room.guest_ready ? "✓ Sẵn sàng" : "Đang chờ sẵn sàng"}</small></div>`
            : `<div class="pvp-player-slot is-empty"><span>ĐỐI THỦ</span><strong>Đang đợi người vào phòng…</strong><small>Chia sẻ mã phòng để mời đối thủ</small></div>`;
        const viewerReady = snapshot.viewer_role === "host" ? room.host_ready : room.guest_ready;
        const bothReady = room.host_ready && room.guest_ready && room.guest_player_id;
        content.innerHTML = `<div class="pvp-waiting-room">
            <div class="pvp-room-header"><div><p class="eyebrow">PHÒNG CHỜ · MÃ ${escapeHtml(room.room_code)}</p><h2>${escapeHtml(room.room_name)}</h2></div><button class="secondary-button compact" data-pvp-copy>Sao chép ID</button></div>
            <p class="pvp-room-options">${room.has_password ? "🔒 Phòng có mật khẩu" : "Phòng công khai"} · ${room.spectators_allowed ? "Cho phép quan chiến" : "Không cho quan chiến"}</p>
            <div class="pvp-player-slots">${host}<span class="pvp-versus">VS</span>${guest}</div>
            <div class="pvp-waiting-actions">
                ${snapshot.viewer_role === "host" || snapshot.viewer_role === "guest" ? `<button class="secondary-button" data-pvp-ready>${viewerReady ? "HỦY SẴN SÀNG" : "SẴN SÀNG"}</button>` : `<span>Vào phòng bằng ID để tham gia.</span>`}
                ${snapshot.viewer_role === "host" ? `<button class="primary-button" data-pvp-start ${bothReady ? "" : "disabled"}>BẮT ĐẦU <span>→</span></button>` : ""}
                ${snapshot.viewer_role === "host" || snapshot.viewer_role === "guest" ? `<button class="pvp-text-button" data-pvp-leave>RỜI PHÒNG</button>` : ""}
            </div>
        </div>`;
        content.querySelector("[data-pvp-copy]")?.addEventListener("click", copyRoomCode);
        content.querySelector("[data-pvp-ready]")?.addEventListener("click", () => setReady(!viewerReady, snapshot));
        content.querySelector("[data-pvp-start]")?.addEventListener("click", () => startRoom(snapshot));
        content.querySelector("[data-pvp-leave]")?.addEventListener("click", () => leaveRoom(snapshot));
    }

    async function refreshRoom() {
        if ((!state.roomCode && !state.rankedMatchId) || state.pollBusy) return;
        state.pollBusy = true;
        try {
            if (state.rankedMatchId) {
                renderRoom(await rankedApi(`/matches/${encodeURIComponent(state.rankedMatchId)}`));
            } else {
                if (state.spectator) await api(`/rooms/${encodeURIComponent(state.roomCode)}/spectate`, { method: "POST" });
                renderRoom(await api(`/rooms/${encodeURIComponent(state.roomCode)}/state`));
            }
        } catch (error) {
            setStatus(error.message, "error");
            stopPolling();
        } finally {
            state.pollBusy = false;
        }
    }

    function startRoomPolling() {
        stopPolling();
        state.pollTimer = setInterval(refreshRoom, 1400);
    }

    async function createRoom(event) {
        event.preventDefault();
        try {
            const roomName = byId("pvp-room-name").value.trim();
            const password = byId("pvp-room-password").value;
            const result = await api("/rooms", { method: "POST", body: JSON.stringify({
                room_name: roomName,
                password: password || null,
                spectators_allowed: byId("pvp-spectators-allowed").checked,
            }) });
            await openRoom(result.room.room_code, false);
            setStatus(`Phòng #${result.room.room_code} đã tạo. Mời đối thủ vào phòng rồi cả hai sẵn sàng.`, "success");
        } catch (error) {
            setStatus(error.message, "error");
        }
    }

    async function joinRoom(code, password) {
        const roomCode = String(code || "").trim().toUpperCase();
        if (!roomCode) return setStatus("Nhập mã phòng trước.", "error");
        try {
            await api(`/rooms/${encodeURIComponent(roomCode)}/join`, { method: "POST", body: JSON.stringify({ password: password || null }) });
            await openRoom(roomCode, false);
        } catch (error) {
            setStatus(error.message, "error");
        }
    }

    async function openRoom(roomCode, spectator) {
        stopPolling();
        state.rankedMatchId = null;
        state.roomCode = String(roomCode).trim().toUpperCase();
        state.spectator = spectator;
        try {
            const snapshot = spectator
                ? await api(`/rooms/${encodeURIComponent(state.roomCode)}/spectate`, { method: "POST" })
                : await api(`/rooms/${encodeURIComponent(state.roomCode)}/state`);
            renderRoom(snapshot);
            startRoomPolling();
        } catch (error) {
            state.roomCode = null;
            setStatus(error.message, "error");
            await openLobby();
        }
    }

    async function setReady(ready, snapshot) {
        try {
            await api(`/rooms/${encodeURIComponent(state.roomCode)}/ready`, { method: "POST", body: JSON.stringify({ ready }) });
            await refreshRoom();
        } catch (error) { setStatus(error.message, "error"); }
    }

    async function startRoom(snapshot) {
        try {
            const result = await api(`/rooms/${encodeURIComponent(state.roomCode)}/start`, { method: "POST", body: JSON.stringify({
                expected_state_version: snapshot.room.state_version,
                action_key: crypto.randomUUID(),
            }) });
            renderRoom(result);
            startRoomPolling();
        } catch (error) { setStatus(error.message, "error"); }
    }

    async function playCard(instanceId, snapshot) {
        const button = byId("pvp-content").querySelector(`[data-pvp-card="${CSS.escape(instanceId)}"]`);
        if (button) button.disabled = true;
        try {
            if (state.rankedMatchId) {
                const result = await rankedApi(`/matches/${encodeURIComponent(state.rankedMatchId)}/play-card`, { method: "POST", body: JSON.stringify({
                    expected_state_version: snapshot.state_version,
                    instance_id: instanceId,
                }) });
                renderRoom(result);
                return;
            }
            const result = await api(`/rooms/${encodeURIComponent(state.roomCode)}/play-card`, { method: "POST", body: JSON.stringify({
                expected_state_version: snapshot.state_version,
                action_key: crypto.randomUUID(),
                instance_id: instanceId,
            }) });
            renderRoom(result);
        } catch (error) {
            setStatus(error.message, "error");
            await refreshRoom();
        }
    }

    async function endTurn(snapshot) {
        try {
            if (state.rankedMatchId) {
                const result = await rankedApi(`/matches/${encodeURIComponent(state.rankedMatchId)}/end-turn`, { method: "POST", body: JSON.stringify({
                    expected_state_version: snapshot.state_version,
                }) });
                renderRoom(result);
                return;
            }
            const result = await api(`/rooms/${encodeURIComponent(state.roomCode)}/end-turn`, { method: "POST", body: JSON.stringify({
                expected_state_version: snapshot.state_version,
                action_key: crypto.randomUUID(),
            }) });
            renderRoom(result);
        } catch (error) {
            setStatus(error.message, "error");
            await refreshRoom();
        }
    }

    async function leaveRoom(snapshot) {
        if (snapshot.spectator) {
            await openLobby();
            return;
        }
        if (snapshot.status === "ACTIVE" && !snapshot.spectator && !window.confirm("Rời trận đang đấu sẽ bị xử thua. Tiếp tục?")) return;
        try {
            await api(`/rooms/${encodeURIComponent(state.roomCode)}/leave`, { method: "POST" });
            await openLobby();
        } catch (error) { setStatus(error.message, "error"); }
    }

    async function openRankedBoard(batch = 0) {
        stopPolling();
        state.roomCode = null;
        state.rankedMatchId = null;
        state.spectator = false;
        state.rankedBatch = batch;
        setStatus("");
        try {
            const board = await rankedApi(`/board?batch=${batch}`);
            renderRankedBoard(board);
        } catch (error) {
            byId("pvp-content").innerHTML = `<p class="inline-status error">${escapeHtml(error.message)}</p>`;
        }
    }

    async function startRankedMatch(opponentId) {
        try {
            const match = await rankedApi("/matches", { method: "POST", body: JSON.stringify({ opponent_player_id: opponentId }) });
            state.rankedMatchId = match.match_id;
            state.roomCode = null;
            renderRoom(match);
            startRoomPolling();
            setStatus(match.match_type === "PLACEMENT" ? "Trận phân hạng bắt đầu!" : "Thách đấu xếp hạng bắt đầu!", "success");
        } catch (error) {
            setStatus(error.message, "error");
            await openRankedBoard(state.rankedBatch);
        }
    }

    async function openRankedMatch(matchId) {
        stopPolling();
        try {
            state.roomCode = null;
            state.rankedMatchId = matchId;
            const match = await rankedApi(`/matches/${encodeURIComponent(matchId)}`);
            renderRoom(match);
            startRoomPolling();
        } catch (error) {
            state.rankedMatchId = null;
            setStatus(error.message, "error");
            await openRankedBoard(state.rankedBatch);
        }
    }

    async function forfeitRankedMatch(snapshot) {
        if (snapshot.status === "ACTIVE" && !window.confirm("Rời trận xếp hạng sẽ tính là thua. Tiếp tục?")) return;
        try {
            if (snapshot.status === "ACTIVE") {
                await rankedApi(`/matches/${encodeURIComponent(state.rankedMatchId)}/forfeit`, {
                    method: "POST",
                    body: JSON.stringify({ expected_state_version: snapshot.state_version }),
                });
            }
            await openRankedBoard(state.rankedBatch);
        } catch (error) {
            setStatus(error.message, "error");
            await refreshRoom();
        }
    }

    async function copyRoomCode() {
        try {
            await navigator.clipboard.writeText(state.roomCode);
            setStatus(`Đã sao chép mã phòng ${state.roomCode}.`, "success");
        } catch {
            setStatus(`Mã phòng: ${state.roomCode}`, "success");
        }
    }

    async function openRoomsLobby() {
        stopPolling();
        state.roomCode = null;
        state.rankedMatchId = null;
        state.spectator = false;
        setStatus("");
        const content = byId("pvp-content");
        content.innerHTML = `<div class="pvp-lobby-toolbar"><div><h2>Sảnh chờ PvP</h2><p>Đấu theo lượt bằng deck Study Spire đã lưu.</p></div><div><button class="secondary-button compact" id="pvp-open-ranked">BẢNG XẾP HẠNG</button> <button class="primary-button" id="pvp-show-create">TẠO PHÒNG <span>＋</span></button></div></div>
            <form id="pvp-create-form" class="pvp-create-panel hidden"><label>Tên phòng<input id="pvp-room-name" maxlength="48" required placeholder="Ví dụ: Thử deck Sinh học"></label><label>Mật khẩu tùy chọn<input id="pvp-room-password" type="password" maxlength="64" placeholder="Để trống nếu phòng công khai"></label><label class="pvp-check-field"><input id="pvp-spectators-allowed" type="checkbox" checked> Cho phép quan chiến</label><div class="pvp-create-actions"><button type="button" class="secondary-button" id="pvp-cancel-create">HỦY</button><button type="submit" class="primary-button">TẠO PHÒNG <span>→</span></button></div></form>
            <form id="pvp-join-form" class="pvp-join-panel"><label for="pvp-join-code">Vào phòng bằng ID</label><input id="pvp-join-code" maxlength="6" placeholder="MÃ PHÒNG"><input id="pvp-join-password" type="password" maxlength="64" placeholder="Mật khẩu nếu có"><button class="secondary-button compact" type="submit">VÀO PHÒNG</button></form>
            <div class="pvp-section-heading"><h2>Phòng công khai</h2><button class="icon-button" id="pvp-refresh-lobby" type="button" aria-label="Tải lại phòng">↻</button></div><div class="pvp-room-grid" id="pvp-room-list"><p>Đang tải phòng…</p></div>`;
        byId("pvp-show-create").addEventListener("click", () => byId("pvp-create-form").classList.toggle("hidden"));
        byId("pvp-open-ranked").addEventListener("click", () => openRankedBoard(0));
        byId("pvp-cancel-create").addEventListener("click", () => byId("pvp-create-form").classList.add("hidden"));
        byId("pvp-create-form").addEventListener("submit", createRoom);
        byId("pvp-join-form").addEventListener("submit", event => {
            event.preventDefault();
            joinRoom(byId("pvp-join-code").value, byId("pvp-join-password").value);
        });
        byId("pvp-refresh-lobby").addEventListener("click", refreshLobbyRooms);
        await refreshLobbyRooms();
        state.lobbyPollTimer = setInterval(refreshLobbyRooms, 3000);
    }

    async function refreshLobbyRooms() {
        const list = byId("pvp-room-list");
        if (!list || state.roomCode || state.pollBusy) return;
        state.pollBusy = true;
        try {
            const result = await api("/lobby");
            list.innerHTML = result.rooms.length ? result.rooms.map(room => `<article class="pvp-room-card"><div class="pvp-room-card-heading"><div><p class="eyebrow">${room.status === "WAITING" ? "PHÒNG CHỜ" : "ĐANG ĐẤU"} · #${escapeHtml(room.room_code)}</p><h3>${escapeHtml(room.room_name)}</h3></div><span>${room.has_password ? "🔒 Có pass" : "Công khai"}</span></div><div class="pvp-room-meta"><span>Host: ${escapeHtml(room.host_name)}</span><span>${escapeHtml(room.guest_name || "Đang đợi đối thủ")}</span></div><div class="pvp-room-card-footer"><span>${room.spectators_allowed ? "Quan chiến bật" : "Quan chiến tắt"}</span>${room.status === "WAITING" ? `<button class="secondary-button compact" data-join="${escapeHtml(room.room_code)}">VÀO PHÒNG</button>` : room.spectators_allowed ? `<button class="secondary-button compact" data-watch="${escapeHtml(room.room_code)}">QUAN CHIẾN</button>` : "<span>Quan chiến đóng</span>"}</div></article>`).join("") : `<p class="pvp-empty-state">Chưa có phòng. Tạo phòng mới hoặc nhập mã được chia sẻ.</p>`;
            list.querySelectorAll("[data-join]").forEach(button => button.addEventListener("click", () => {
                const room = result.rooms.find(item => item.room_code === button.dataset.join);
                byId("pvp-join-code").value = button.dataset.join;
                if (room?.has_password) byId("pvp-join-password").focus();
                else joinRoom(button.dataset.join, "");
            }));
            list.querySelectorAll("[data-watch]").forEach(button => button.addEventListener("click", () => openRoom(button.dataset.watch, true)));
        } catch (error) {
            list.innerHTML = `<p class="inline-status error">${escapeHtml(error.message)}</p>`;
        } finally {
            state.pollBusy = false;
        }
    }

    const chat = { socket: null, retryTimer: null, wanted: false, seen: new Set() };

    function appendChatMessage(message) {
        const list = byId("pvp-chat-messages");
        if (!list) return;
        const system = message.role === "SYSTEM";
        const item = document.createElement("div");
        item.className = `pvp-chat-message${system ? " is-system" : ""}`;
        const meta = document.createElement("small");
        meta.textContent = `${message.player_name || "Ẩn danh"} · ${message.time || ""}`;
        const body = document.createElement("p");
        body.textContent = message.content;
        item.append(meta, body);
        const stick = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
        list.appendChild(item);
        while (list.children.length > 80) list.firstElementChild.remove();
        if (stick) list.scrollTop = list.scrollHeight;
    }

    function setChatState(text) {
        const label = byId("pvp-chat-state");
        if (label) label.textContent = text;
    }

    async function loadChatHistory() {
        try {
            const response = await fetch("/api/chat/history");
            if (!response.ok) return;
            const history = await response.json();
            const list = byId("pvp-chat-messages");
            if (list) list.innerHTML = "";
            history.forEach(appendChatMessage);
        } catch { /* lịch sử chỉ là phần phụ */ }
    }

    function connectChat() {
        if (!token || !byId("pvp-chat-messages")) return;
        if (chat.socket && chat.socket.readyState <= WebSocket.OPEN) return;
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const socket = new WebSocket(`${protocol}://${window.location.host}/api/chat/ws?token=${encodeURIComponent(token)}`);
        chat.socket = socket;
        setChatState("Đang kết nối…");
        socket.onopen = () => setChatState("Đang trực tuyến");
        socket.onmessage = (event) => {
            let message;
            try { message = JSON.parse(event.data); } catch { return; }
            if (message.type === "error") {
                const notice = byId("pvp-chat-notice");
                if (notice) notice.textContent = message.content;
            } else if (message.type === "chat") {
                appendChatMessage(message);
            }
        };
        socket.onclose = () => {
            if (chat.socket === socket) chat.socket = null;
            setChatState("Mất kết nối");
            if (chat.wanted) chat.retryTimer = setTimeout(connectChat, 3000);
        };
    }

    async function openChat() {
        chat.wanted = true;
        await loadChatHistory();
        connectChat();
    }

    function closeChat() {
        chat.wanted = false;
        clearTimeout(chat.retryTimer);
        if (chat.socket) chat.socket.close();
        chat.socket = null;
    }

    function initChatForm() {
        const form = byId("pvp-chat-form");
        if (!form || form.dataset.bound) return;
        form.dataset.bound = "1";
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const input = byId("pvp-chat-input");
            const text = input.value.trim();
            const notice = byId("pvp-chat-notice");
            if (!text) return;
            if (!chat.socket || chat.socket.readyState !== WebSocket.OPEN) {
                notice.textContent = "Chưa kết nối khung chat.";
                connectChat();
                return;
            }
            notice.textContent = "";
            chat.socket.send(text.slice(0, 300));
            input.value = "";
        });
    }

    const snow = { raf: null, flakes: [] };

    function startSnow() {
        const canvas = byId("pvp-chat-snow");
        if (!canvas || snow.raf || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        const ctx = canvas.getContext("2d");
        const resize = () => {
            canvas.width = canvas.clientWidth;
            canvas.height = canvas.clientHeight;
        };
        resize();
        snow.flakes = Array.from({ length: 45 }, () => ({
            x: Math.random() * canvas.width, y: Math.random() * canvas.height,
            r: 1 + Math.random() * 2.2, speed: 0.25 + Math.random() * 0.55,
            drift: Math.random() * Math.PI * 2, alpha: 0.35 + Math.random() * 0.5,
        }));
        const frame = () => {
            if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) resize();
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (const flake of snow.flakes) {
                flake.y += flake.speed;
                flake.drift += 0.01;
                flake.x += Math.sin(flake.drift) * 0.35;
                if (flake.y > canvas.height + 4) { flake.y = -4; flake.x = Math.random() * canvas.width; }
                ctx.beginPath();
                ctx.fillStyle = `rgba(255, 255, 255, ${flake.alpha})`;
                ctx.arc(flake.x, flake.y, flake.r, 0, Math.PI * 2);
                ctx.fill();
            }
            snow.raf = requestAnimationFrame(frame);
        };
        snow.raf = requestAnimationFrame(frame);
    }

    function stopSnow() {
        if (snow.raf) cancelAnimationFrame(snow.raf);
        snow.raf = null;
    }

    function openLobby() {
        initChatForm();
        startSnow();
        openChat();
        return openRankedBoard(0);
    }

    window.StudySpirePvp = { openLobby, close() { stopPolling(); closeChat(); stopSnow(); } };
})();