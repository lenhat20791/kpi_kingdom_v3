(() => {
    const ANIMATIONS = Object.freeze({
        idle: { frames: 6, duration: 1200, name: "soldier-idle" },
        attack: { frames: 6, duration: 720, impactFrame: 4, name: "soldier-attack" },
        shield: { frames: 9, duration: 990, impactFrame: 6, name: "soldier-shield" },
        hurt: { frames: 4, duration: 520, impactFrame: 2, name: "soldier-hurt" },
        death: { frames: 4, duration: 640, name: "soldier-death" }
    });

    class StudySpireAnimator {
        constructor(element, initialAnimation = "idle") {
            if (!element) throw new Error("Không tìm thấy sprite nhân vật.");
            this.element = element;
            if (initialAnimation === "death") this.playDeath();
            else this.setIdle();
        }

        setIdle() {
            this.element.dataset.animation = "idle";
        }

        setDeath() {
            this.element.dataset.animation = "death-final";
        }

        playDeath() {
            return this.play("death");
        }

        play(animationName, onImpact = () => undefined) {
            const config = ANIMATIONS[animationName];
            if (!config || animationName === "idle") {
                throw new Error(`Hoạt ảnh không hợp lệ: ${animationName}`);
            }

            this.element.dataset.animation = animationName;
            const animationFinished = new Promise((resolve) => {
                let finished = false;
                const finish = (event) => {
                    if (finished || (event && (event.target !== this.element || event.animationName !== config.name))) return;
                    finished = true;
                    this.element.removeEventListener("animationend", finish);
                    resolve();
                };
                this.element.addEventListener("animationend", finish);
                window.setTimeout(() => finish(), config.duration + 180);
            });

            if (animationName === "death") {
                return animationFinished.then(() => this.setDeath());
            }

            const impactDelay = config.duration * (config.impactFrame / config.frames);
            const impactFinished = new Promise((resolve, reject) => {
                window.setTimeout(() => {
                    Promise.resolve().then(onImpact).then(resolve, reject);
                }, impactDelay);
            });

            return Promise.all([animationFinished, impactFinished])
                .then(([, result]) => {
                    this.setIdle();
                    return result;
                })
                .catch((error) => {
                    this.setIdle();
                    throw error;
                });
        }
    }

    const MONSTER_PROFILES = Object.freeze({
        Bat: {
            frameSize: 87,
            idle: { file: "fly.png", frames: 11, duration: 1100 },
            attack: { file: "attack.png", frames: 11, duration: 715, impactFrame: 4 },
            hurt: { file: "hurt.png", frames: 3, duration: 390 },
            death: { file: "death.png", frames: 4, duration: 520 }
        },
        Mimic: {
            frameSize: 146,
            idle: { file: "idle_transformed.png", frames: 9, duration: 990 },
            attack: { file: "attack_1.png", frames: 14, duration: 728, impactFrame: 5 },
            hurt: { file: "hurt.png", frames: 3, duration: 390 },
            death: { file: "death.png", frames: 6, duration: 780 }
        },
        Rat: {
            frameSize: 70,
            idle: { file: "idle.png", frames: 10, duration: 1000 },
            attack: { file: "attack_bite.png", frames: 12, duration: 624, impactFrame: 5 },
            hurt: { file: "hurt.png", frames: 3, duration: 390 },
            death: { file: "rat-death.png", frames: 6, duration: 780 }
        },
        Slime: {
            frameSize: 156,
            idle: { file: "idle.png", frames: 14, duration: 980 },
            attack: { file: "attack.png", frames: 19, duration: 988, impactFrame: 5 },
            hurt: { file: "hurt.png", frames: 3, duration: 390 },
            death: { file: "death.png", frames: 11, duration: 990 }
        }
    });

    class StudyMonsterAnimator {
        constructor(element, monsterType, initialAnimation = "idle") {
            if (!element) throw new Error("Không tìm thấy sprite quái vật.");
            this.element = element;
            this.monsterType = MONSTER_PROFILES[monsterType] ? monsterType : "Rat";
            this.profile = MONSTER_PROFILES[this.monsterType];
            if (initialAnimation === "death") this.playDeath();
            else this.setAnimation(initialAnimation);
        }

        setAnimation(animationName) {
            const config = this.profile[animationName];
            if (!config) throw new Error(`Hoạt ảnh quái không hợp lệ: ${animationName}`);
            const displayFrameSize = 160;
            this.element.style.setProperty("--monster-image", `url("/assets/monsters/${this.monsterType}/${config.file}")`);
            this.element.style.setProperty("--monster-frame-count", config.frames);
            this.element.style.setProperty("--monster-duration", `${config.duration}ms`);
            this.element.style.setProperty("--monster-sheet-size", `${displayFrameSize * config.frames}px ${displayFrameSize}px`);
            this.element.style.setProperty("--monster-final-position", `${-displayFrameSize * (config.frames - 1)}px`);
            this.element.style.setProperty("--monster-step-timing", `steps(${config.frames}, jump-none)`);
            this.element.dataset.animation = animationName;
        }

        setIdle() {
            this.setAnimation("idle");
        }

        setDeath() {
            this.setAnimation("death");
            this.element.dataset.animation = "death-final";
        }

        playDeath() {
            return this.play("death");
        }

        play(animationName, onImpact = () => undefined) {
            const config = this.profile[animationName];
            if (!config || animationName === "idle") {
                throw new Error(`Hoạt ảnh quái không hợp lệ: ${animationName}`);
            }
            this.setAnimation(animationName);

            const animationFinished = new Promise((resolve) => {
                let finished = false;
                const finish = (event) => {
                    if (finished || (event && (event.target !== this.element || event.animationName !== `monster-${animationName}`))) return;
                    finished = true;
                    this.element.removeEventListener("animationend", finish);
                    resolve();
                };
                this.element.addEventListener("animationend", finish);
                window.setTimeout(() => finish(), config.duration + 180);
            });

            if (animationName === "death") {
                return animationFinished.then(() => this.setDeath());
            }

            const impactDelay = config.impactFrame
                ? config.duration * config.impactFrame / config.frames
                : 0;
            const impactFinished = new Promise((resolve, reject) => {
                window.setTimeout(() => Promise.resolve().then(onImpact).then(resolve, reject), impactDelay);
            });

            return Promise.all([animationFinished, impactFinished])
                .then(([, result]) => {
                    this.setIdle();
                    return result;
                })
                .catch((error) => {
                    this.setIdle();
                    throw error;
                });
        }
    }

    window.StudySpireAnimator = StudySpireAnimator;
    window.StudyMonsterAnimator = StudyMonsterAnimator;
})();
