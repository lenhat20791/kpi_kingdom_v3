(() => {
    const API = "/api/study-spire";
    const state = { run: null, deck: null, inventory: null, catalog: null, profile: null, deckTab: "deck", deckReadOnly: false, pendingPackReward: null, pendingDrawVfx: null, spriteAnimator: null, monsterAnimator: null, actionLocked: false };
    const token = localStorage.getItem("access_token") || localStorage.getItem("token");
    const username = localStorage.getItem("kpi_username") || localStorage.getItem("username") || "";
    const pendingResolutionStorageKey = `study_spire_pending_resolution:${username}`;

    const byId = (id) => document.getElementById(id);
    function selectGuideTab(name) {
        document.querySelectorAll("[data-guide-tab]").forEach((tab) => {
            const active = tab.dataset.guideTab === name;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll("[data-guide-panel]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.guidePanel !== name));
        byId("screen-guide").querySelector(".guide-body").scrollTop = 0;
    }

    async function openGuide() {
        showScreen("screen-guide");
        selectGuideTab("overview");
        const list = byId("guide-relic-list");
        if (list.dataset.loaded) return;
        try {
            const data = await api("/relics");
            list.innerHTML = data.relics.map((relic) => `<div class="guide-relic"><img src="${escapeHtml(relic.image_url)}" alt="" loading="lazy"><span><strong>${escapeHtml(relic.name)}</strong><small>${escapeHtml(relic.description)}</small></span></div>`).join("");
            list.dataset.loaded = "1";
        } catch (error) {
            list.innerHTML = `<p class="inline-status">Không tải được danh sách relic.</p>`;
        }
    }

    const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[char]);
    const requestKey = () => crypto.randomUUID();
    const cardTypeLabels = { attack: "Tấn công", defense: "Phòng thủ", spell: "Phép" };
    const subjectLabels = { ly: "Vật lý", hoa: "Hóa học", sinh: "Sinh học", starter: "Khởi đầu" };

    function effectiveCardCost(battle, instanceId, baseCost) {
        const modifier = battle.cost_modifiers?.[instanceId] || {};
        if (modifier.cost !== undefined) return Math.max(0, Number(modifier.cost));
        return Math.max(Number(modifier.minimum || 0), Math.floor(Number(baseCost) * Number(modifier.multiplier || 1)) + Number(modifier.delta || 0));
    }

    function openCardPreview(instanceId) {
        const card = state.inventory?.cards.find((item) => item.instance_id === instanceId);
        if (!card) return;
        const template = state.catalog?.cards.find((item) => item.card_id === card.card_id);
        const type = card.type || template?.type || "spell";
        const typeLabel = card.type_label_vi || template?.type_label_vi || cardTypeLabels[type] || "Phép";
        const cost = state.run?.battle
            ? effectiveCardCost(state.run.battle, instanceId, card.mana_cost)
            : card.mana_cost;
        byId("card-preview-content").innerHTML = `
            ${window.renderCard({
                id: instanceId,
                name: card.name,
                cost,
                type,
                type_label_vi: typeLabel,
                rarity: card.rarity,
                artUrl: card.image_url,
                description: card.description,
                effect_tooltips: card.effect_tooltips || template?.effect_tooltips,
            })}
            <section class="card-preview-details">
                <p class="eyebrow">${escapeHtml(subjectLabels[card.subject] || "Vật lý")} · ${escapeHtml(card.rarity_label_vi || template?.rarity_label_vi || "Hiếm")} · ${escapeHtml(typeLabel)}</p>
                <h2 id="card-preview-title">${escapeHtml(card.name)}</h2>
                <p>${escapeHtml(card.description)}</p>
                <p><strong>Trí tuệ tiêu thụ:</strong> ${escapeHtml(cost)}</p>
                ${state.pendingPackReward?.instanceId === instanceId ? `<p class="pack-reward-note">Đóng cửa sổ này để thêm lá vào bộ bài. Nếu bộ bài đã có 2 bản sao, lá mới sẽ được giữ trong kho.</p>` : ""}
            </section>`;
        byId("card-preview-modal").classList.remove("hidden");
        byId("card-preview-close").focus();
    }

    function bindCardPreviewHandlers(root) {
        root.querySelectorAll("[data-preview-card]").forEach((element) => {
            element.addEventListener("click", (event) => {
                if (event.target.closest("button") && !element.classList.contains("preview-card-button")) return;
                openCardPreview(element.dataset.previewCard);
            });
            element.addEventListener("keydown", (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                openCardPreview(element.dataset.previewCard);
            });
        });
    }

    async function closeCardPreview() {
        const pendingReward = state.pendingPackReward;
        if (!pendingReward) {
            byId("card-preview-modal").classList.add("hidden");
            return;
        }
        const closeButton = byId("card-preview-close");
        closeButton.disabled = true;
        setStatus("deck-status", "Đang chuyển thẻ vào bộ bài hoặc kho...");
        try {
            const result = await api("/deck/add-earned", {
                method: "POST",
                body: JSON.stringify({
                    instance_id: pendingReward.instanceId,
                    expected_state_version: state.deck.state_version,
                    idempotency_key: requestKey(),
                }),
            });
            state.pendingPackReward = null;
            byId("card-preview-modal").classList.add("hidden");
            [state.deck, state.inventory] = await Promise.all([api("/deck"), api("/inventory")]);
            renderDeck();
            setStatus("deck-status", result.added_to_deck ? "Đã thêm lá bài vào bộ bài." : result.message, result.added_to_deck ? "success" : "");
        } catch (error) {
            setStatus("deck-status", error.message, "error");
        } finally {
            closeButton.disabled = false;
        }
    }

    function pileRect(selector) {
        const element = byId("run-content")?.querySelector(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
    }

    function capturePileOrigins() {
        return { draw: pileRect(".draw-pile"), discard: pileRect(".discard-pile") };
    }

    function queueDrawVfx(battle, origins = null) {
        const events = battle?.draw_events || [];
        if (events.some((event) => event.reshuffled || event.card_instance_ids?.length)) {
            state.pendingDrawVfx = { events: structuredClone(events), origins };
        }
    }

    function getCardVfxLayer() {
        let layer = byId("card-vfx-layer");
        if (!layer) {
            layer = document.createElement("div");
            layer.id = "card-vfx-layer";
            layer.setAttribute("aria-hidden", "true");
            document.body.appendChild(layer);
        }
        return layer;
    }

    function flyCardBack(fromRect, toRect, className, delay = 0, duration = 620) {
        if (!fromRect || !toRect) return Promise.resolve();
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const layer = getCardVfxLayer();
        const fromX = fromRect.left + fromRect.width / 2;
        const fromY = fromRect.top + fromRect.height / 2;
        const toX = toRect.left + toRect.width / 2;
        const toY = toRect.top + toRect.height / 2;
        const width = Math.min(82, Math.max(54, toRect.width * 0.56));
        const height = width * 1.42;
        const card = document.createElement("div");
        card.className = `draw-vfx-card ${className}`;
        card.innerHTML = `<img src="/assets/card/back.png" alt=""><span class="draw-vfx-trail"></span>`;
        card.style.width = `${width}px`;
        card.style.height = `${height}px`;
        card.style.left = `${fromX - width / 2}px`;
        card.style.top = `${fromY - height / 2}px`;
        layer.appendChild(card);
        return new Promise((resolve) => {
            window.setTimeout(() => {
                const durationMs = reducedMotion ? 260 : duration;
                const animation = card.animate([
                    { transform: "translate3d(0, 0, 0) rotate(-9deg) scale(.58)", opacity: reducedMotion ? .65 : .15 },
                    { transform: `translate3d(${(toX - fromX) * .48}px, ${(toY - fromY) * .48 - 62}px, 0) rotate(8deg) scale(.94)`, opacity: 1, offset: .56 },
                    { transform: `translate3d(${toX - fromX}px, ${toY - fromY}px, 0) rotate(0) scale(.42)`, opacity: 0 }
                ], { duration: durationMs, easing: "cubic-bezier(.2,.75,.25,1)", fill: "forwards" });
                animation.onfinish = () => {
                    card.remove();
                    resolve();
                };
                animation.oncancel = () => {
                    card.remove();
                    resolve();
                };
            }, delay);
        });
    }

    async function playDrawVfx(pending) {
        const content = byId("run-content");
        const drawPile = content?.querySelector(".draw-pile");
        const discardPile = content?.querySelector(".discard-pile");
        if (!drawPile) return;
        const drawRect = pending.origins?.draw || drawPile.getBoundingClientRect();
        const discardRect = pending.origins?.discard || discardPile?.getBoundingClientRect();
        const hand = content.querySelector(".hand-fan");
        const cards = [...content.querySelectorAll("[data-card]")];

        if (pending.events.some((event) => event.reshuffled) && discardRect) {
            await Promise.all([0, 1, 2].map((index) => flyCardBack(discardRect, drawRect, "draw-vfx-shuffle", index * 70, 360)));
            drawPile.classList.add("pile-shuffle-arrival");
            window.setTimeout(() => drawPile.classList.remove("pile-shuffle-arrival"), 520);
        }

        const drawnIds = [...new Set(pending.events.flatMap((event) => event.card_instance_ids || []))];
        if (!hand || !drawnIds.length) return;
        await Promise.all(drawnIds.map(async (instanceId, index) => {
            const target = cards.find((button) => button.dataset.card === instanceId);
            if (!target) return;
            const targetRect = target.getBoundingClientRect();
            if (!Number.isFinite(targetRect.left)) return;
            await flyCardBack(drawRect, targetRect, "draw-vfx-flight", index * 96);
            target.classList.add("draw-card-arrival");
            window.setTimeout(() => target.classList.remove("draw-card-arrival"), 420);
        }));
    }

    async function api(path, options = {}) {
        const headers = {
            Authorization: `Bearer ${token}`,
            ...(options.headers || {})
        };
        if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
        const response = await fetch(`${API}${path}`, {
            ...options,
            headers
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (response.status === 401) window.location.href = "/index.html";
            throw new Error(data.detail || data.message || `Lỗi máy chủ (${response.status})`);
        }
        return data;
    }

    function setStatus(elementId, message, type = "") {
        const element = byId(elementId);
        element.textContent = message || "";
        element.className = `inline-status ${type}`.trim();
    }

    function showScreen(screenId) {
        document.body.classList.remove("battle-mode");
        document.body.classList.toggle("entry-screen-active", screenId === "screen-entry");
        document.querySelectorAll(".screen").forEach((screen) => screen.classList.add("hidden"));
        byId(screenId).classList.remove("hidden");
        setStatus("entry-status", "");
        setStatus("run-status", "");
        setStatus("deck-status", "");
    }

    function setRun(run) {
        state.run = run;
        if (run) {
            byId("run-hp").textContent = `HP ${run.player_core.hp} / ${run.player_core.hp_max}`;
            const stage = run.player_core.stage || 1;
            byId("run-heading").textContent = run.run_status === "CHOOSING_ROUTE" ? `Chọn đường · Ải ${stage} · Tầng ${run.current_floor}` : `Ải ${stage} · Tầng ${run.current_floor}`;
            byId("footer-run-id").textContent = `RUN ${run.run_id.slice(0, 8).toUpperCase()}`;
        }
    }

    async function refreshActiveRun() {
        const run = await api("/run/active");
        if (run.run) {
            setRun(run.run);
            await renderRun();
        } else {
            state.run = null;
            showScreen("screen-entry");
            byId("start-run").classList.remove("hidden");
            byId("resume-run").classList.add("hidden");
        }
    }

    function openStartRunDialog() {
        byId("start-run-modal").classList.remove("hidden");
        byId("grade-select").focus();
    }

    async function startRun() {
        byId("start-run-modal").classList.add("hidden");
        setStatus("entry-status", "Đang chuẩn bị hành trình...");
        try {
            const run = await api("/run/start", {
                method: "POST",
                body: JSON.stringify({ grade: Number(byId("grade-select").value), idempotency_key: requestKey() })
            });
            queueDrawVfx(run.battle);
            setRun(run);
            await renderRun();
        } catch (error) {
            setStatus("entry-status", error.message, "error");
        }
    }

    function routeIcon(roomType) {
        return ({ monster: "⚔", inn: "⌂", chest: "▣", elite: "☠", event: "✦", boss: "♜" })[roomType] || "◇";
    }

    function roomName(roomType) {
        return ({ monster: "Hang quái vật", inn: "Nhà trọ", chest: "Rương báu", elite: "Quái vật tinh anh", event: "Sự kiện", boss: "Phòng Boss" })[roomType] || "Phòng lạ";
    }

    async function renderRouteChoices() {
        const content = byId("run-content");
        const choices = state.run.pending_pack_choices || [];
        if (choices.length) {
            const catalog = state.catalog || await api("/catalog");
            const packsById = Object.fromEntries(catalog.packs.map((pack) => [pack.pack_id, pack]));
            const availableChoices = choices.filter((packId) => packsById[packId]);
            content.innerHTML = `
                <div class="map-intro"><div><h2>Phần thưởng: pack bài ngẫu nhiên</h2><p>Mỗi chiến thắng luôn tặng ngẫu nhiên 1 trong 3 pack bài: Vật Lý, Hóa Học hoặc Sinh Học. Bấm để nhận và xem bạn trúng pack nào.</p></div></div>
                <div class="route-grid ${availableChoices.length === 1 ? "single" : ""}">${availableChoices.map((packId, index) => {
                    const pack = packsById[packId];
                    return `<button class="route-card" data-pack="${escapeHtml(packId)}"><span class="route-index">PACK 0${index + 1}</span><span class="route-icon">▧</span><span><strong class="route-name">Pack ngẫu nhiên</strong><small class="route-direction">1 trong 3: Vật Lý · Hóa Học · Sinh Học</small></span></button>`;
                }).join("")}</div>`;
            content.querySelectorAll("[data-pack]").forEach((button) => button.addEventListener("click", () => claimPack(button.dataset.pack)));
            return;
        }

        const history = state.run.history_path || [];
        const previousNode = history[history.length - 1];
        const options = state.run.map_graph.edges.filter((edge) => edge.from_node_id === previousNode);
        const single = options.length === 1;
        content.innerHTML = `
            <div class="map-intro"><div><h2>${single ? "Chặng cuối" : "Chọn hướng đi"}</h2><p>${single ? "Một cánh cửa duy nhất dẫn tới đối thủ cuối cùng." : "Ba ngả đường đang mở ra phía trước."}</p></div></div>
            <div class="route-grid ${single ? "single" : ""}">${options.map((edge, index) => {
                const node = state.run.map_graph.nodes[edge.target_node_id];
                return `<button class="route-card" data-node="${escapeHtml(edge.target_node_id)}"><span class="route-index">TẦNG ${node.floor} · 0${index + 1}</span><span class="route-icon">${routeIcon(node.room_type)}</span><span><strong class="route-name">${escapeHtml(roomName(node.room_type))}</strong><small class="route-direction">${escapeHtml(edge.direction)}</small></span></button>`;
            }).join("")}</div>`;
        content.querySelectorAll("[data-node]").forEach((button) => button.addEventListener("click", () => selectNode(button.dataset.node)));
    }

    function healthBar(label, hp, maxHp, kind = "") {
        const percent = Math.max(0, Math.min(100, maxHp ? hp / maxHp * 100 : 0));
        return `<div class="health-label"><span>${label}</span><span>${hp} / ${maxHp}</span></div><div class="health-line ${kind}"><span style="width:${percent}%"></span></div>`;
    }

    let activeEffectTooltip = null;

    function hideEffectTooltip() {
        activeEffectTooltip?.remove();
        activeEffectTooltip = null;
    }

    function attachEffectTooltips(root) {
        root.querySelectorAll("[data-effect-tooltip]").forEach((icon) => {
            const showTooltip = () => {
                hideEffectTooltip();
                const tooltip = document.createElement("div");
                tooltip.className = "effect-tooltip";
                tooltip.setAttribute("role", "tooltip");
                tooltip.textContent = icon.dataset.effectTooltip;
                document.body.appendChild(tooltip);

                const iconRect = icon.getBoundingClientRect();
                const tooltipRect = tooltip.getBoundingClientRect();
                const left = Math.max(8, Math.min(
                    iconRect.left + iconRect.width / 2 - tooltipRect.width / 2,
                    window.innerWidth - tooltipRect.width - 8,
                ));
                const above = iconRect.top - tooltipRect.height - 8;
                const top = above >= 8
                    ? above
                    : Math.min(window.innerHeight - tooltipRect.height - 8, iconRect.bottom + 8);
                tooltip.style.left = `${left}px`;
                tooltip.style.top = `${Math.max(8, top)}px`;
                activeEffectTooltip = tooltip;
            };

            icon.addEventListener("mouseenter", showTooltip);
            icon.addEventListener("mouseleave", hideEffectTooltip);
            icon.addEventListener("focus", showTooltip);
            icon.addEventListener("blur", hideEffectTooltip);
        });
    }

    function renderEffectIndicators(entity) {
        const indicators = [];
        const descriptions = {
            shield: (value) => `${value} Khiên: Chặn sát thương nhận vào. Thường mất cuối lượt, trừ khi được hiệu ứng giữ lại.`,
            strength: (value) => `Sức mạnh +${value}: Tăng ${value} sát thương cho tất cả các đòn tấn công.`,
            poison: (value) => `${value} Độc: Nhận ${value} sát thương khi kết thúc lượt, sau đó giảm 1 stack (còn ${value} lượt).`,
            vulnerable: (value) => `Yếu Đuối ${value} tầng: Đòn đánh kế tiếp nhận thêm ${value} sát thương, sau đó xóa trạng thái.`,
            regeneration: (value, turns) => `Hồi phục: Hồi ${value} HP mỗi lượt trong ${turns} lượt tiếp theo.`
        };
        const append = (icon, effectType, value, detail = 0) => {
            if (Number(value) <= 0) return;
            const count = effectType === "regeneration" ? `${value}·${detail}` : value;
            const description = descriptions[effectType](value, detail);
            indicators.push(`<span class="effect-stack" data-effect-tooltip="${escapeHtml(description)}" tabindex="0" aria-label="${escapeHtml(description)}"><img src="/assets/icon/${icon}.png" alt=""><b>${escapeHtml(count)}</b></span>`);
        };

        append("shield", "shield", entity.shield || 0);
        append("sword", "strength", entity.strength || 0);
        for (const effect of entity.active_effects || []) {
            if (effect.type === "poison") append("skull", "poison", effect.stacks || 0);
            if (effect.type === "vulnerable") append("sword", "vulnerable", effect.stacks || 0);
            if (effect.type === "regeneration") append("heart", "regeneration", effect.amount || 0, effect.turns_left || 0);
        }

        return `<div class="effect-stack-row" aria-label="Hiệu ứng đang có">${indicators.join("")}</div>`;
    }

    function sumEffect(entity, type, field) {
        return (entity.active_effects || [])
            .filter((effect) => effect.type === type)
            .reduce((total, effect) => total + Math.max(0, Number(effect[field] || 0)), 0);
    }

    function spawnCombatFeedback(target, kind, amount) {
        const numericAmount = Math.max(0, Math.round(Number(amount) || 0));
        const sprite = byId(target === "player" ? "player-sprite" : "monster-sprite");
        if (!sprite || numericAmount <= 0) return;

        const rect = sprite.getBoundingClientRect();
        const burst = document.createElement("div");
        burst.className = `combat-feedback combat-feedback-${kind}`;
        burst.style.left = `${rect.left + rect.width / 2}px`;
        burst.style.top = `${rect.top + Math.max(8, rect.height * 0.12)}px`;

        const number = document.createElement("span");
        number.className = "combat-feedback-number";
        number.textContent = kind === "heal" ? `+${numericAmount}` : `-${numericAmount}`;
        burst.appendChild(number);

        const particleRange = kind === "poison" ? [8, 12] : kind === "heal" ? [10, 15] : [0, 0];
        const particleCount = particleRange[0] + Math.floor(Math.random() * (particleRange[1] - particleRange[0] + 1));
        for (let index = 0; index < particleCount; index += 1) {
            const particle = document.createElement("i");
            particle.className = `combat-feedback-particle combat-feedback-particle-${kind}`;
            particle.style.setProperty("--particle-x", `${Math.round((Math.random() - 0.5) * 110)}px`);
            particle.style.setProperty("--particle-y", `${Math.round(22 + Math.random() * 66)}px`);
            particle.style.setProperty("--particle-delay", `${Math.round(Math.random() * 100)}ms`);
            particle.style.setProperty("--particle-size", `${Math.round(5 + Math.random() * (kind === "poison" ? 8 : 5))}px`);
            burst.appendChild(particle);
        }

        document.body.appendChild(burst);
        window.setTimeout(() => burst.remove(), 1000);
    }

    function spawnBlockedPopup(target) {
        const sprite = byId(target === "player" ? "player-sprite" : "monster-sprite");
        if (!sprite) return;
        const rect = sprite.getBoundingClientRect();
        const popup = document.createElement("div");
        popup.className = "combat-feedback combat-feedback-block";
        popup.style.left = `${rect.left + rect.width / 2}px`;
        popup.style.top = `${rect.top + Math.max(8, rect.height * 0.12)}px`;
        const label = document.createElement("span");
        label.className = "combat-feedback-number";
        label.textContent = "Chặn đòn";
        popup.appendChild(label);
        document.body.appendChild(popup);
        window.setTimeout(() => popup.remove(), 1000);
    }

    function estimateEndTurnFeedback(battle) {
        const events = [];
        const player = battle.player;
        const enemy = battle.enemy;

        const playerRegen = sumEffect(player, "regeneration", "amount");
        const playerBeforeAttack = Math.min(player.hp_max, player.hp + playerRegen);
        if (playerBeforeAttack > player.hp) events.push({ target: "player", kind: "heal", amount: playerBeforeAttack - player.hp });

        const incomingAttack = Math.max(0, Number(battle.next_intent?.damage || 0) + Number(enemy.strength || 0) + sumEffect(player, "vulnerable", "stacks"));
        const absorbedByShield = Math.min(Math.max(0, player.shield), incomingAttack);
        const shieldAfterAttack = Math.max(0, player.shield - absorbedByShield);
        const hpDamage = Math.min(playerBeforeAttack, Math.max(0, incomingAttack - absorbedByShield));
        if (hpDamage > 0) events.push({ target: "player", kind: "normal", amount: hpDamage });

        const hpAfterAttack = Math.max(0, playerBeforeAttack - hpDamage);
        const playerPoisonDamage = Math.min(hpAfterAttack, Math.max(0, sumEffect(player, "poison", "stacks") - shieldAfterAttack));
        if (playerPoisonDamage > 0) events.push({ target: "player", kind: "poison", amount: playerPoisonDamage });

        const enemyBeforePoison = Math.min(enemy.max_hp, enemy.hp + sumEffect(enemy, "regeneration", "amount"));
        const enemyPoisonDamage = Math.min(enemyBeforePoison, Math.max(0, sumEffect(enemy, "poison", "stacks") - enemy.shield));
        if (enemyPoisonDamage > 0) events.push({ target: "enemy", kind: "poison", amount: enemyPoisonDamage });
        if (enemyBeforePoison > enemy.hp) events.push({ target: "enemy", kind: "heal", amount: enemyBeforePoison - enemy.hp });

        return events;
    }

    function rarityImage(url, fallback) {
        return escapeHtml(url || fallback || "/assets/card/back.png");
    }

    async function renderBattle() {
        hideEffectTooltip();
        const battle = state.run.battle;
        const player = battle.player;
        const enemy = battle.enemy;
        const handIds = battle.hand;
        const inventory = state.inventory || (state.inventory = await api("/inventory"));
        const cardByInstance = Object.fromEntries(inventory.cards.map((card) => [card.instance_id, card]));
        const node = state.run.map_graph.nodes[state.run.current_node_id];
        const background = enemy.arena_background || "/assets/background/hg.png";
        const monsterType = enemy.sprite_set || ["Rat", "Bat", "Slime", "Mimic"][(node.floor - 1) % 4];
        const resolving = battle.phase === "RESOLVING";
        const content = byId("run-content");
        content.innerHTML = `
            <div class="battle-layout battle-layout-board">
                <section class="battle-arena" style="background-image:url('${background}')">
                    <header class="battle-hud">
                        <div class="battle-hud-left">
                            <span class="hud-floor">ẢI ${state.run.player_core.stage || 1} · TẦNG ${node.floor} / ${state.run.map_graph.final_floor || 10}</span>
                            <span class="hud-stat hud-health"><b>♥</b> ${player.hp}<small>/${player.hp_max}</small></span>
                            <span class="hud-stat hud-counter"><b>♧</b> ${battle.turn_number}</span>
                        </div>
                        <div class="battle-hud-right">
                            <button id="open-battle-menu" class="hud-icon-button" type="button" aria-label="Menu trận đấu" title="Menu">☰</button>
                        </div>
                    </header>
                    <div class="combatants">
                        <div class="combatant player"><div id="player-sprite" class="fighter-sprite" data-animation="${player.hp <= 0 ? "death" : "idle"}" role="img" aria-label="Nhà thám hiểm"></div><h3>${escapeHtml(state.profile?.name || username || "Nhà thám hiểm")}</h3>${healthBar("HP NGƯỜI CHƠI", player.hp, player.hp_max, "player")}${renderEffectIndicators(player)}</div>
                        <div class="combatant enemy"><div id="monster-sprite" class="monster-sprite" data-animation="${enemy.hp <= 0 ? "death" : "idle"}" role="img" aria-label="${escapeHtml(enemy.name || "Quái vật")}"></div><h3>${escapeHtml(enemy.name || "Quái vật")}</h3>${healthBar("HP QUÁI", enemy.hp, enemy.max_hp)}${renderEffectIndicators(enemy)}</div>
                    </div>
                    <div class="battle-piles">
                        <div class="battle-pile draw-pile"><span class="pile-symbol">▧</span><b>${battle.draw_pile.length}</b><small>RÚT</small></div>
                        <div class="battle-pile discard-pile"><span class="pile-symbol">▤</span><b>${battle.discard_pile.length}</b><small>BỎ</small></div>
                    </div>
                </section>
                <aside class="battle-overlay-controls">
                    <div class="battle-mana" aria-label="Trí tuệ ${player.mana} trên ${player.mana_max || 3}"><span class="mana-orb">${player.mana}<small>/${player.mana_max || 3}</small></span><span class="mana-caption">TRÍ TUỆ</span></div>
                    <div class="hand-list hand-fan">${handIds.map((instanceId, index) => {
                        const card = cardByInstance[instanceId];
                        if (!card) return "";
                        const cardTemplate = state.catalog?.cards.find((template) => template.card_id === card.card_id);
                        const effectiveCost = effectiveCardCost(battle, instanceId, card.mana_cost);
                        const compactLayout = window.innerWidth <= 700;
                        const centerIndex = (handIds.length - 1) / 2;
                        const cardWidth = compactLayout
                            ? Math.min(128, window.innerWidth * 0.33)
                            : Math.min(168, window.innerWidth * 0.18);
                        const fanCenterRatio = compactLayout ? 0.5 : 0.44;
                        const availableRadius = Math.min(window.innerWidth * fanCenterRatio, window.innerWidth * (1 - fanCenterRatio)) - cardWidth / 2;
                        const maxSpread = centerIndex > 0 ? Math.max(24, availableRadius / centerIndex) : 0;
                        const spread = Math.min(cardWidth * 0.55, maxSpread);
                        const fanOffset = Math.round((index - centerIndex) * spread);
                        const fanAngle = Math.round((index - centerIndex) * (handIds.length > 6 ? 4 : 7));
                        const cardMarkup = window.renderCard({
                            id: instanceId,
                            name: card.name,
                            cost: effectiveCost,
                            type: cardTemplate?.type || card.type || "spell",
                            type_label_vi: cardTemplate?.type_label_vi || card.type_label_vi || cardTypeLabels[card.type] || "Phép",
                            rarity: card.rarity,
                            artUrl: card.image_url,
                            description: card.description,
                            effect_tooltips: card.effect_tooltips || cardTemplate?.effect_tooltips
                        });
                        return `<button class="hand-card" data-card="${escapeHtml(instanceId)}" style="--card-offset:${fanOffset}px;--card-angle:${fanAngle}deg;--card-index:${index}" aria-label="${escapeHtml(card.name)}, ${escapeHtml(cardTypeLabels[card.type] || "Phép")}, ${effectiveCost} Trí tuệ" ${resolving || state.actionLocked || player.mana < effectiveCost ? "disabled" : ""}>${cardMarkup}</button>`;
                    }).join("")}</div>
                    <div class="end-turn-button battle-end-turn">${resolving ? `<button id="resolve-battle" class="primary-button">KẾT TOÁN TRẬN <span>→</span></button>` : `<button id="end-turn" class="secondary-button" ${state.actionLocked ? "disabled" : ""}>KẾT THÚC LƯỢT</button>`}</div>
                </aside>
            </div>`;
        state.spriteAnimator = new window.StudySpireAnimator(byId("player-sprite"), player.hp <= 0 ? "death" : "idle");
        state.monsterAnimator = new window.StudyMonsterAnimator(byId("monster-sprite"), monsterType, enemy.hp <= 0 ? "death" : "idle");
        byId("open-battle-menu")?.addEventListener("click", openBattleMenu);
        attachEffectTooltips(content);
        content.querySelectorAll("[data-card]").forEach((button) => button.addEventListener("click", () => playCard(button.dataset.card)));
        byId("end-turn")?.addEventListener("click", endTurn);
        byId("resolve-battle")?.addEventListener("click", resolveBattle);
        const pendingDrawVfx = state.pendingDrawVfx;
        if (pendingDrawVfx) {
            state.pendingDrawVfx = null;
            requestAnimationFrame(() => playDrawVfx(pendingDrawVfx));
        }
    }

    function openBattleMenu() {
        setStatus("battle-menu-status", "");
        byId("battle-menu-modal").classList.remove("hidden");
    }

    async function saveBattleAndExit() {
        setStatus("battle-menu-status", "Đang xác nhận tiến trình đã lưu...");
        try {
            const active = await api("/run/active");
            if (!active.run) throw new Error("Không tìm thấy tiến trình đang lưu.");
            window.location.href = "/player_dashboard.html";
        } catch (error) {
            setStatus("battle-menu-status", error.message, "error");
        }
    }

    async function viewBattleDeck() {
        byId("battle-menu-modal").classList.add("hidden");
        await openDeck(true);
    }

    async function renderChallenge() {
        const node = state.run.map_graph.nodes[state.run.current_node_id];
        const challenge = await api("/node/challenge");
        const content = byId("run-content");
        const imageUrl = node.room_type === "inn" ? "/assets/background/nha_tro.png" : node.room_type === "chest" ? "/study-spire-assets/ruong.png" : "";
        const retryNotice = challenge.reward_forfeited ? "Bạn đã sai ở lượt trước; chỉ các câu chưa đúng còn được chọn lại và lần này sẽ không có thưởng." : "";
        const intro = retryNotice || (node.room_type === "inn" ? "Trả lời đúng 5 câu để hồi 30% HP." : node.room_type === "chest" ? "Gõ lại đoạn học liệu với độ chính xác từ 80% trở lên để mở rương." : "Trả lời đúng 3 câu để nhận hiệu ứng sự kiện.");
        let challengeHtml = "";
        if (challenge.questions) {
            const lockedAnswers = challenge.locked_answers || {};
            challengeHtml = challenge.questions.map((question, index) => {
                const lockedAnswer = lockedAnswers[String(question.id)];
                return `<article class="quiz-question${lockedAnswer ? " is-locked-correct" : ""}"><h3>${index + 1}. ${escapeHtml(question.content)}${lockedAnswer ? ` <span class="quiz-locked-label">ĐÃ ĐÚNG</span>` : ""}</h3>${question.choices.map((choice) => {
                    const isLocked = Boolean(lockedAnswer);
                    const isSelected = lockedAnswer === choice.key;
                    return `<label class="quiz-choice${isSelected ? " is-locked-choice" : ""}"><input type="radio" name="q-${question.id}" value="${escapeHtml(choice.key)}"${isSelected ? " checked" : ""}${isLocked ? " disabled" : ""}><span>${escapeHtml(choice.text)}</span></label>`;
                }).join("")}</article>`;
            }).join("");
        } else {
            challengeHtml = `<div class="quiz-question"><p>${escapeHtml(challenge.passage.content)}</p><textarea id="typing-answer" class="challenge-text" rows="5" placeholder="Nhập lại nội dung tại đây..."></textarea></div>`;
        }
        content.innerHTML = `<div class="room-stage">${imageUrl ? `<img class="room-art" src="${imageUrl}" alt="${escapeHtml(roomName(node.room_type))}" onerror="this.src='/assets/background/hg.png'">` : `<div class="room-art room-art-event" aria-hidden="true"></div>`}<div class="room-panel"><p class="eyebrow">TẦNG ${node.floor}</p><h2>${escapeHtml(roomName(node.room_type))}</h2><p>${intro}</p><form id="challenge-form">${challengeHtml}<button class="primary-button" type="submit">${node.room_type === "chest" ? "MỞ RƯƠNG" : "XÁC NHẬN"}<span>→</span></button></form></div></div>`;
        byId("challenge-form").addEventListener("submit", submitChallenge);
        if (challenge.retry_feedback?.length) showQuizFeedback(challenge.retry_feedback);
    }

    async function renderRun() {
        setRun(state.run);
        showScreen("screen-run");
        try {
            if (state.run.run_status === "CHOOSING_ROUTE") return await renderRouteChoices();
            if (state.run.battle) {
                document.body.classList.add("battle-mode");
                return await renderBattle();
            }
            return await renderChallenge();
        } catch (error) {
            setStatus("run-status", error.message, "error");
        }
    }

    async function selectNode(targetNodeId) {
        setStatus("run-status", "Đang xác nhận tuyến đường...");
        try {
            const previousBattleId = state.run.battle_id;
            const selectedRun = await api("/route/select", { method: "POST", body: JSON.stringify({ target_node_id: targetNodeId, expected_state_version: state.run.state_version, idempotency_key: requestKey() }) });
            if (selectedRun.battle && selectedRun.battle_id !== previousBattleId) queueDrawVfx(selectedRun.battle);
            state.run = selectedRun;
            state.inventory = null;
            await renderRun();
        } catch (error) {
            await refreshActiveRun().catch(() => {});
            setStatus("run-status", error.message, "error");
        }
    }

    async function claimPack(packId) {
        try {
            const result = await api("/pack/claim", { method: "POST", body: JSON.stringify({ chosen_pack_id: packId, expected_state_version: state.run.state_version, idempotency_key: requestKey() }) });
            state.inventory = null;
            await refreshActiveRun();
            setStatus("run-status", `Bạn nhận được ${result.claimed_pack.name}!`, "success");
        } catch (error) { setStatus("run-status", error.message, "error"); }
    }

    async function playCard(cardInstanceId) {
        if (state.actionLocked) return;
        const pileOrigins = capturePileOrigins();
        const instance = state.inventory?.cards.find((card) => card.instance_id === cardInstanceId);
        const template = state.catalog?.cards.find((card) => card.card_id === instance?.card_id);
        const effects = template?.effects || [];
        const hasAttackEffect = effects.some((effect) => ["attack", "attack_from_shield", "attack_bonus_per_prior_tag"].includes(effect.op || effect.type));
        const hasShieldEffect = effects.some((effect) => ["shield", "gain_shield"].includes(effect.op || effect.type));
        const animation = hasAttackEffect ? "attack" : hasShieldEffect ? "shield" : null;
        state.actionLocked = true;
        byId("run-content").querySelectorAll("button").forEach((button) => { button.disabled = true; });
        try {
            const submitCard = async () => {
                const previousEnemyHp = state.run.battle.enemy.hp;
                const result = await api("/battle/play-card", { method: "POST", body: JSON.stringify({ card_instance_id: cardInstanceId, expected_state_version: state.run.state_version, idempotency_key: requestKey() }) });
                if (animation === "attack" && result.battle?.enemy?.hp < previousEnemyHp) {
                    spawnCombatFeedback("enemy", "normal", previousEnemyHp - result.battle.enemy.hp);
                    await state.monsterAnimator?.play("hurt");
                }
                return result;
            };
            const result = animation && state.spriteAnimator
                ? await state.spriteAnimator.play(animation, submitCard)
                : await submitCard();
            state.actionLocked = false;
            queueDrawVfx(result.battle, pileOrigins);
            state.run = result;
            await renderRun();
        } catch (error) {
            state.actionLocked = false;
            await refreshActiveRun().catch(() => {});
            setStatus("run-status", error.message, "error");
        }
    }

    async function endTurn() {
        if (state.actionLocked) return;
        const pileOrigins = capturePileOrigins();
        const battle = state.run.battle;
        const vulnerableStacks = (battle.player.active_effects || [])
            .filter((effect) => effect.type === "vulnerable")
            .reduce((total, effect) => total + Number(effect.stacks || 0), 0);
        const incomingAttack = Number(battle.next_intent?.damage || 0) + Number(battle.enemy.strength || 0) + vulnerableStacks;
        const shieldAfterAttack = Math.max(0, Number(battle.player.shield || 0) - incomingAttack);
        const poisonStacks = (battle.player.active_effects || [])
            .filter((effect) => effect.type === "poison")
            .reduce((total, effect) => total + Number(effect.stacks || 0), 0);
        const incomingDamage = Math.max(0, incomingAttack - Number(battle.player.shield || 0))
            + Math.max(0, poisonStacks - shieldAfterAttack);
        const attackFullyBlocked = incomingAttack > 0 && incomingAttack <= Number(battle.player.shield || 0);
        const feedbackEvents = estimateEndTurnFeedback(battle);
        state.actionLocked = true;
        byId("run-content").querySelectorAll("button").forEach((button) => { button.disabled = true; });
        try {
            const finishTurn = async () => {
                const result = await api("/battle/end-turn", { method: "POST", body: JSON.stringify({ expected_state_version: state.run.state_version, idempotency_key: requestKey() }) });
                if (attackFullyBlocked) spawnBlockedPopup("player");
                feedbackEvents.forEach((event) => spawnCombatFeedback(event.target, event.kind, event.amount));
                return result;
            };
            let result;
            if (incomingDamage > 0 && state.spriteAnimator && state.monsterAnimator) {
                const [, resolvedTurn] = await Promise.all([
                    state.monsterAnimator.play("attack"),
                    state.spriteAnimator.play("hurt", finishTurn)
                ]);
                result = resolvedTurn;
            } else if (state.monsterAnimator) {
                result = await state.monsterAnimator.play("attack", finishTurn);
            } else {
                result = await finishTurn();
            }
            state.actionLocked = false;
            queueDrawVfx(result.battle, pileOrigins);
            state.run = result;
            await renderRun();
        } catch (error) {
            state.actionLocked = false;
            await refreshActiveRun().catch(() => {});
            setStatus("run-status", error.message, "error");
        }
    }

    async function resolveBattle() {
        const key = `${state.run.run_id}_${state.run.battle_id}`;
        const pendingResolution = { idempotency_key: key, expected_state_version: state.run.state_version };
        localStorage.setItem(pendingResolutionStorageKey, JSON.stringify(pendingResolution));
        try {
            const result = await api("/battle/resolve", { method: "POST", body: JSON.stringify({ expected_state_version: state.run.state_version, idempotency_key: key }) });
            localStorage.removeItem(pendingResolutionStorageKey);
            if (result.run_status === "VICTORY" || result.run_status === "DEFEATED") return showResult(result);
            if (result.stage_cleared) return showStageCleared(result);
            state.run = await api("/run/active");
            state.run = state.run.run;
            state.inventory = null;
            await renderRun();
        } catch (error) {
            await refreshActiveRun().catch(() => {});
            setStatus("run-status", error.message, "error");
        }
    }

    async function submitChallenge(event) {
        event.preventDefault();
        const node = state.run.map_graph.nodes[state.run.current_node_id];
        const challenge = await api("/node/challenge");
        const payload = { expected_state_version: state.run.state_version, idempotency_key: requestKey(), answers: {} };
        if (challenge.questions) {
            for (const question of challenge.questions) {
                const selected = document.querySelector(`input[name="q-${question.id}"]:checked`);
                if (!selected) return setStatus("run-status", "Hãy trả lời tất cả câu hỏi.", "error");
                payload.answers[String(question.id)] = selected.value;
            }
        } else {
            payload.submitted_text = byId("typing-answer").value;
        }
        try {
            const result = await api("/node/complete", { method: "POST", body: JSON.stringify(payload) });
            if (result.retry_required) {
                state.run = (await api("/run/active")).run;
                await renderRun();
                return;
            }
            if (!result.completed) return setStatus("run-status", result.message, "error");
            state.run = await api("/run/active");
            state.run = state.run.run;
            await renderRun();
            const message = result.reward_forfeited
                ? "Đã hoàn tất sau khi sửa đáp án. Phòng này không còn phần thưởng."
                : node.room_type === "inn"
                    ? `Đã hồi ${result.reward.amount} HP.`
                    : result.reward?.type === "heal" ? `Sự kiện: hồi ${result.reward.amount} HP.`
                    : result.reward?.type === "damage" ? `Sự kiện: mất ${result.reward.amount} HP.`
                    : result.reward?.type === "pack" ? `Sự kiện: nhận ${result.reward.pack.name}!`
                    : "Thử thách hoàn tất.";
            setStatus("run-status", message, "success");
        } catch (error) {
            await refreshActiveRun().catch(() => {});
            setStatus("run-status", error.message, "error");
        }
    }

    function showQuizFeedback(feedback) {
        const list = byId("quiz-feedback-list");
        list.innerHTML = feedback.map((item, index) => `
            <article class="quiz-feedback-item ${item.is_correct ? "is-correct" : "is-incorrect"}">
                <h3><span>Câu ${index + 1}</span><strong>${item.is_correct ? "ĐÚNG" : "SAI"}</strong></h3>
                <p>${escapeHtml(item.question)}</p>
                <p><span class="quiz-feedback-label">Bạn chọn:</span> ${escapeHtml(item.selected_answer || "Chưa có đáp án")}</p>
                ${item.is_correct ? "" : `<p class="quiz-correct-answer"><span class="quiz-feedback-label">Đáp án đúng:</span> ${escapeHtml(item.correct_answer)}</p>`}
            </article>`).join("");
        byId("quiz-feedback-modal").classList.remove("hidden");
        byId("quiz-feedback-retry").focus();
    }

    function closeQuizFeedback() {
        byId("quiz-feedback-modal").classList.add("hidden");
        byId("run-content").querySelector(".quiz-choice input:not(:disabled)")?.focus();
    }

    function showStageCleared(result) {
        state.run = result;
        state.inventory = null;
        const relicReward = result.relic
            ? `<div class="boss-relic-reward"><img src="${escapeHtml(result.relic.image_url)}" alt=""><div><strong>Relic mới: ${escapeHtml(result.relic.name)}</strong><small>${escapeHtml(result.relic.description)}</small></div></div>`
            : `<p class="boss-relic-complete">Bạn đã sưu tập đủ 19 relic.</p>`;
        const nextFloors = result.map_graph?.final_floor || 10;
        byId("stage-clear-title").textContent = `QUA ẢI ${result.stage_cleared}`;
        byId("stage-clear-details").innerHTML = `<p>Ải ${escapeHtml(String(result.stage))} có ${nextFloors} tầng và quái mạnh hơn.</p>${relicReward}`;
        byId("stage-clear-modal").classList.remove("hidden");
    }

    function showResult(result) {
        state.run = null;
        document.body.classList.remove("battle-mode");
        byId("result-title").textContent = "HÀNH TRÌNH KẾT THÚC";
        const cleared = Number(result.stages_cleared || 0);
        const stageNote = cleared > 0 ? ` Bạn đã vượt qua ${cleared} ải và dừng lại ở ải ${result.stage}.` : ` Bạn dừng lại ở ải ${result.stage || 1}.`;
        byId("result-details").innerHTML = `<p>${escapeHtml(`${stageNote} Hành trình đã được lưu.`.trim())}</p>`;
        byId("result-modal").classList.remove("hidden");
    }

    async function openDeck(readOnly = false) {
        state.deckReadOnly = readOnly;
        showScreen("screen-deck");
        try {
            [state.deck, state.inventory, state.profile] = await Promise.all([
                api("/deck"),
                api("/inventory"),
                api("/profile").catch(() => null),
            ]);
            state.deckTab = "deck";
            renderDeck();
        } catch (error) { setStatus("deck-status", error.message, "error"); }
    }

    function renderDeckProfile() {
        const profile = state.profile || {};
        const displayName = profile.name || username || "Người chơi";
        byId("deck-player-name").textContent = displayName;
        byId("deck-avatar-fallback").textContent = displayName.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase() || "?";
        const avatar = byId("deck-player-avatar");
        if (profile.avatar_url) {
            avatar.src = profile.avatar_url;
            avatar.classList.remove("hidden");
            byId("deck-avatar-fallback").classList.add("hidden");
        } else {
            avatar.removeAttribute("src");
            avatar.classList.add("hidden");
            byId("deck-avatar-fallback").classList.remove("hidden");
        }
    }

    async function uploadDeckAvatar(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
            setStatus("deck-status", "Ảnh tối đa 5 MB.", "error");
            event.target.value = "";
            return;
        }
        const formData = new FormData();
        formData.append("image", file);
        setStatus("deck-status", "Đang cập nhật ảnh đại diện…");
        try {
            state.profile = await api("/profile/avatar", { method: "POST", body: formData });
            renderDeckProfile();
            setStatus("deck-status", "Đã cập nhật ảnh đại diện 512×512.", "success");
        } catch (error) {
            setStatus("deck-status", error.message, "error");
        } finally {
            event.target.value = "";
        }
    }

    async function openPvpLobby() {
        showScreen("screen-pvp");
        await window.StudySpirePvp.openLobby();
    }

    function renderDeck() {
        renderDeckProfile();
        const deckIds = state.deck.cards.map((card) => card.instance_id);
        const minimumCards = state.deck.minimum_cards || 20;
        byId("deck-count").textContent = `${deckIds.length} lá · tối thiểu ${minimumCards}`;
        byId("pack-count").textContent = state.inventory.packs.reduce((sum, pack) => sum + pack.quantity, 0);
        byId("deck-tabs").classList.toggle("hidden", state.deckReadOnly);
        byId("back-from-deck").textContent = state.deckReadOnly ? "← TRỞ LẠI TRẬN" : "← QUAY LẠI";
        document.querySelectorAll("[data-deck-tab]").forEach((button) => {
            const active = button.dataset.deckTab === state.deckTab;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", String(active));
        });
        const content = byId("deck-content");
        const inDeck = new Set(deckIds);
        const rows = state.inventory.cards.filter((card) => card.is_active !== false);
        const deckCards = rows.filter((card) => inDeck.has(card.instance_id));
        const availableCards = rows.filter((card) => !inDeck.has(card.instance_id));
        if (state.deckReadOnly) {
            content.innerHTML = `<p class="deck-lock-notice">Bộ bài mang theo trong hành trình · ${deckCards.length} lá</p><div class="current-deck-view">${deckCards.map((card) => {
                return `<button type="button" class="preview-card-button" data-preview-card="${escapeHtml(card.instance_id)}" aria-label="Xem trước ${escapeHtml(card.name)}">${window.renderCard({ id: card.instance_id, name: card.name, cost: card.mana_cost, type: card.type, type_label_vi: card.type_label_vi, rarity: card.rarity, artUrl: card.image_url, description: card.description, effect_tooltips: card.effect_tooltips })}</button>`;
            }).join("")}</div>`;
            bindCardPreviewHandlers(content);
            return;
        }
        if (state.deckTab === "packs") {
            content.innerHTML = state.inventory.packs.length ? `<div class="pack-grid">${state.inventory.packs.map((pack) => `<article class="pack-card"><div><p class="eyebrow">${escapeHtml(pack.subject)}</p><h3>${escapeHtml(pack.name)}</h3></div><p>${pack.quantity} pack trong kho</p><button class="primary-button" data-open-pack="${escapeHtml(pack.pack_id)}" data-pack-version="${pack.state_version}">MỞ PACK <span>→</span></button></article>`).join("")}</div>` : `<p class="inline-status">Kho pack đang trống.</p>`;
            content.querySelectorAll("[data-open-pack]").forEach((button) => button.addEventListener("click", () => openPack(button.dataset.openPack, Number(button.dataset.packVersion))));
            return;
        }

        const lockNotice = state.deck.must_remain_full && deckCards.length < 20
            ? `<p class="deck-lock-notice">Cần ít nhất ${minimumCards} lá để lưu và tiếp tục. Hiện có ${deckCards.length} lá.</p>`
            : "";
        const listing = (card, action, label) => `<article class="library-card" data-preview-card="${escapeHtml(card.instance_id)}" tabindex="0" aria-label="Xem trước ${escapeHtml(card.name)}"><img src="${rarityImage(card.image_url)}" alt=""><span><strong>${escapeHtml(card.name)}</strong><small>${escapeHtml(subjectLabels[card.subject] || "Vật lý")} · ${escapeHtml(card.rarity_label_vi || "Hiếm")} · ${escapeHtml(card.type_label_vi || cardTypeLabels[card.type] || "Phép")}</small></span><button type="button" data-${action}="${escapeHtml(card.instance_id)}">${label}</button></article>`;
        content.innerHTML = `${lockNotice}<div class="deck-columns"><section class="deck-column"><div class="deck-column-head"><span>BỘ BÀI HIỆN TẠI</span><span>${deckCards.length} lá · tối thiểu ${minimumCards}</span></div><div class="card-list">${deckCards.map((card) => listing(card, "remove-card", "BỎ")).join("") || `<p class="inline-status">Chưa có lá trong bộ bài.</p>`}</div><div class="card-list"><button id="save-deck" class="primary-button" ${state.deck.must_remain_full && deckCards.length < 20 ? "disabled" : ""}>LƯU BỘ BÀI <span>→</span></button></div></section><section class="deck-column"><div class="deck-column-head"><span>${state.deckTab === "cards" ? "KHO BÀI" : "THẺ CÓ THỂ THÊM"}</span><span>${availableCards.length}</span></div><div class="card-list">${availableCards.map((card) => listing(card, "add-card", "THÊM")).join("") || `<p class="inline-status">Không còn thẻ ngoài bộ bài.</p>`}</div></section></div>`;
        content.querySelectorAll("[data-remove-card]").forEach((button) => button.addEventListener("click", () => changeDeck(button.dataset.removeCard, false)));
        content.querySelectorAll("[data-add-card]").forEach((button) => button.addEventListener("click", () => changeDeck(button.dataset.addCard, true)));
        bindCardPreviewHandlers(content);
        byId("save-deck").addEventListener("click", saveDeck);
    }

    function changeDeck(instanceId, add) {
        const ids = state.deck.cards.map((card) => card.instance_id);
        if (add && !ids.includes(instanceId)) ids.push(instanceId);
        const minimumCards = state.deck.must_remain_full ? 20 : 10;
        if (!add && ids.length > minimumCards) ids.splice(ids.indexOf(instanceId), 1);
        const allById = Object.fromEntries(state.inventory.cards.map((card) => [card.instance_id, card]));
        state.deck.cards = ids.map((id) => allById[id]).filter(Boolean);
        renderDeck();
    }

    function deckExitIsBlocked() {
        return Boolean(state.deck?.must_remain_full && state.deck.cards.length < 20);
    }

    function showDeckLockReminder() {
        byId("deck-lock-modal").classList.remove("hidden");
        byId("deck-lock-return").focus();
    }

    async function leaveDeck() {
        if (state.deckReadOnly) {
            state.deckReadOnly = false;
            if (state.run) await refreshActiveRun();
            else showScreen("screen-entry");
            return;
        }
        if (deckExitIsBlocked()) {
            showDeckLockReminder();
            return;
        }
        if (state.run) renderRun();
        else showScreen("screen-entry");
    }

    async function saveDeck() {
        if (deckExitIsBlocked()) {
            showDeckLockReminder();
            setStatus("deck-status", "Sau khi đã đạt 20 lá, bạn cần giữ lại đủ 20 lá.", "error");
            return;
        }
        try {
            state.deck = await api("/deck", { method: "PUT", body: JSON.stringify({ expected_state_version: state.deck.state_version, idempotency_key: requestKey(), card_instance_ids: state.deck.cards.map((card) => card.instance_id) }) });
            setStatus("deck-status", "Đã lưu bộ bài.", "success");
            renderDeck();
        } catch (error) { setStatus("deck-status", error.message, "error"); }
    }

    async function openPack(packId, expectedStateVersion) {
        try {
            const result = await api("/pack/open", { method: "POST", body: JSON.stringify({ pack_id: packId, expected_state_version: expectedStateVersion, idempotency_key: requestKey() }) });
            [state.deck, state.inventory] = await Promise.all([api("/deck"), api("/inventory")]);
            renderDeck();
            state.pendingPackReward = { instanceId: result.card.instance_id };
            openCardPreview(result.card.instance_id);
            setStatus("deck-status", `Mở pack nhận được ${result.card.name}.`, "success");
        } catch (error) { setStatus("deck-status", error.message, "error"); }
    }

    async function initialize() {
        if (!token) {
            window.location.href = "/index.html";
            return;
        }
        byId("header-player").textContent = username;
        const returnToGameMenu = () => {
            if (!byId("screen-deck").classList.contains("hidden") && deckExitIsBlocked()) {
                showDeckLockReminder();
                return;
            }
            if (!byId("screen-pvp").classList.contains("hidden")) window.StudySpirePvp.close();
            showScreen("screen-entry");
        };
        byId("back-to-dashboard").addEventListener("click", () => {
            returnToGameMenu();
        });
        document.querySelector(".brand")?.addEventListener("click", (event) => {
            event.preventDefault();
            returnToGameMenu();
        });
        byId("start-run").addEventListener("click", openStartRunDialog);
        byId("confirm-start-run").addEventListener("click", startRun);
        byId("cancel-start-run").addEventListener("click", () => byId("start-run-modal").classList.add("hidden"));
        byId("start-run-modal").addEventListener("click", (event) => {
            if (event.target === byId("start-run-modal")) byId("start-run-modal").classList.add("hidden");
        });
        byId("resume-run").addEventListener("click", refreshActiveRun);
        byId("open-deck-from-run").addEventListener("click", openDeck);
        byId("back-from-deck").addEventListener("click", leaveDeck);
        byId("deck-avatar-change").addEventListener("click", () => byId("deck-avatar-file").click());
        byId("deck-avatar-file").addEventListener("change", uploadDeckAvatar);
        byId("deck-lock-return").addEventListener("click", () => byId("deck-lock-modal").classList.add("hidden"));
        byId("card-preview-close").addEventListener("click", closeCardPreview);
        byId("card-preview-modal").addEventListener("click", (event) => {
            if (event.target === byId("card-preview-modal")) closeCardPreview();
        });
        byId("quiz-feedback-retry").addEventListener("click", closeQuizFeedback);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !byId("card-preview-modal").classList.contains("hidden")) closeCardPreview();
        });
        byId("battle-save-exit").addEventListener("click", saveBattleAndExit);
        byId("battle-continue").addEventListener("click", () => byId("battle-menu-modal").classList.add("hidden"));
        byId("battle-view-deck").addEventListener("click", viewBattleDeck);
        byId("return-home").addEventListener("click", () => { byId("result-modal").classList.add("hidden"); showScreen("screen-entry"); });
        byId("stage-clear-continue").addEventListener("click", async () => {
            byId("stage-clear-modal").classList.add("hidden");
            await renderRun();
        });
        document.querySelectorAll("[data-entry-action]").forEach((button) => button.addEventListener("click", () => {
            if (button.dataset.entryAction === "deck") return openDeck();
            if (button.dataset.entryAction === "pvp" || button.dataset.entryAction === "ranked") return openPvpLobby();
            if (button.dataset.entryAction === "guide") return openGuide();
            byId("grade-select").focus();
        }));
        byId("guide-back").addEventListener("click", () => showScreen("screen-entry"));
        document.querySelectorAll("[data-guide-tab]").forEach((tab) => tab.addEventListener("click", () => selectGuideTab(tab.dataset.guideTab)));
        byId("pvp-back").addEventListener("click", () => {
            window.StudySpirePvp.close();
            showScreen("screen-entry");
        });
        document.querySelectorAll("[data-deck-tab]").forEach((button) => button.addEventListener("click", () => { state.deckTab = button.dataset.deckTab; renderDeck(); }));
        byId("entry-video").addEventListener("error", () => byId("entry-video").classList.add("hidden"));
        try {
            try {
                state.profile = await api("/profile");
                byId("header-player").textContent = state.profile.name || username;
            } catch (error) {
                setStatus("entry-status", `Không tải được hồ sơ người chơi: ${error.message}`, "error");
            }
            state.catalog = await api("/catalog");
            const gradeSelect = byId("grade-select");
            const availableGrades = state.catalog.available_grades || [];
            gradeSelect.innerHTML = availableGrades.map((grade) => `<option value="${grade}">Khối ${grade}</option>`).join("");
            if (!availableGrades.length) {
                byId("start-run").disabled = true;
                setStatus("entry-status", "Ngân hàng câu hỏi hiện chưa đủ dữ liệu cho một khối học.", "error");
            }
            const pendingResolution = localStorage.getItem(pendingResolutionStorageKey);
            if (pendingResolution) {
                try {
                    const result = await api("/battle/resolve", { method: "POST", body: pendingResolution });
                    localStorage.removeItem(pendingResolutionStorageKey);
                    if (result.run_status === "VICTORY" || result.run_status === "DEFEATED") {
                        showResult(result);
                        return;
                    }
                    if (result.stage_cleared) {
                        showStageCleared(result);
                        return;
                    }
                } catch (error) {
                    if (error instanceof TypeError) {
                        setStatus("entry-status", "Đang chờ kết nối để xác nhận kết quả trận đấu.", "error");
                        return;
                    }
                    const activeAfterFailure = await api("/run/active").catch(() => null);
                    if (activeAfterFailure && activeAfterFailure.run) {
                        localStorage.removeItem(pendingResolutionStorageKey);
                        state.run = activeAfterFailure.run;
                        await renderRun();
                        return;
                    }
                    setStatus("entry-status", "Chưa xác nhận được kết quả cuối. Hãy tải lại để thử khôi phục.", "error");
                    return;
                }
            }
            const active = await api("/run/active");
            if (active.run) {
                state.run = active.run;
                byId("start-run").classList.add("hidden");
                byId("resume-run").classList.remove("hidden");
                await renderRun();
            }
        } catch (error) { setStatus("entry-status", error.message, "error"); }
    }

    document.addEventListener("DOMContentLoaded", initialize);
})();
