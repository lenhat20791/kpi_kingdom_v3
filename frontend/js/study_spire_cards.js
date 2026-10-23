(() => {
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[char]);

    function renderCard(cardData) {
        const card = cardData || {};
        const typeLabels = { attack: "Tấn công", defense: "Phòng thủ", spell: "Phép" };
        const cardType = card.type_label_vi || typeLabels[String(card.type || "spell").toLowerCase()] || "Phép";
        const rarityValue = String(card.rarity || "common").toLowerCase();
        const rarity = ({ r: "rare", ur: "ultra_rare", legendary: "legend" })[rarityValue] || rarityValue;
        const effectTooltips = Array.isArray(card.effect_tooltips) ? card.effect_tooltips : [];
        const artUrl = String(card.artUrl || "").trim();
        const art = artUrl
            ? `<img class="spire-card-art-image" src="${escapeHtml(artUrl)}" alt="">`
            : `<span class="spire-card-art-placeholder" aria-hidden="true"></span>`;

        return `<span class="spire-card" data-card-id="${escapeHtml(card.id)}" data-type="${escapeHtml(card.type || "spell")}" data-rarity="${escapeHtml(rarity)}" data-effect-tooltips="${escapeHtml(JSON.stringify(effectTooltips))}" role="group" aria-label="${escapeHtml(card.name || "Lá bài")}, ${escapeHtml(cardType)}, ${escapeHtml(card.description || "")}">
            <span class="spire-card-mana">${escapeHtml(card.cost ?? "?")}</span>
            <span class="spire-card-banner"><span class="spire-card-name">${escapeHtml(card.name || "")}</span></span>
            <span class="spire-card-artbox">${art}<span class="spire-card-type">${cardType}</span></span>
            <span class="spire-card-description">${escapeHtml(card.description || "")}</span>
        </span>`;
    }

    document.addEventListener("error", (event) => {
        const image = event.target;
        if (!(image instanceof HTMLImageElement)) return;
        if (image.classList.contains("spire-card-art-image")) {
            const placeholder = document.createElement("span");
            placeholder.className = "spire-card-art-placeholder";
            placeholder.setAttribute("aria-hidden", "true");
            image.replaceWith(placeholder);
        } else if (image.closest(".library-card")) {
            image.style.visibility = "hidden";
        }
    }, true);

    let activeCardTooltip = null;

    function hideCardTooltip() {
        activeCardTooltip?.remove();
        activeCardTooltip = null;
    }

    function showCardTooltip(card) {
        let explanations;
        try {
            explanations = JSON.parse(card.dataset.effectTooltips || "[]");
        } catch {
            return;
        }
        if (!Array.isArray(explanations) || !explanations.length) return;
        hideCardTooltip();
        const tooltip = document.createElement("div");
        tooltip.className = "effect-tooltip card-effect-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.textContent = explanations.join("\n");
        document.body.appendChild(tooltip);

        const cardRect = card.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const right = cardRect.right + 8;
        const left = right + tooltipRect.width <= window.innerWidth - 8
            ? right
            : Math.max(8, cardRect.left - tooltipRect.width - 8);
        const top = Math.max(8, Math.min(cardRect.top, window.innerHeight - tooltipRect.height - 8));
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
        activeCardTooltip = tooltip;
    }

    const cardTooltipFromTarget = (target) => {
        if (!(target instanceof Element)) return null;
        return target.closest(".spire-card[data-effect-tooltips]")
            || target.querySelector(".spire-card[data-effect-tooltips]");
    };

    document.addEventListener("pointerover", (event) => {
        const card = cardTooltipFromTarget(event.target);
        if (!card || (event.relatedTarget instanceof Node && card.contains(event.relatedTarget))) return;
        showCardTooltip(card);
    });
    document.addEventListener("pointerout", (event) => {
        const card = cardTooltipFromTarget(event.target);
        if (card && !(event.relatedTarget instanceof Node && card.contains(event.relatedTarget))) hideCardTooltip();
    });
    document.addEventListener("focusin", (event) => {
        const card = cardTooltipFromTarget(event.target);
        if (card) showCardTooltip(card);
    });
    document.addEventListener("focusout", (event) => {
        const card = cardTooltipFromTarget(event.target);
        if (card && !(event.relatedTarget instanceof Node && card.contains(event.relatedTarget))) hideCardTooltip();
    });

    window.renderCard = renderCard;
})();
