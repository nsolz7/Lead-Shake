import { useEffect, useRef } from "react";
import { Power1, Power2, Power3, Sine, TimelineMax, TweenMax } from "gsap";
import {
  ALIVE_FISH, ALIVE_FISH_VIEWBOX, ALIVE_SCENE, DEAD_FISH, DEAD_FISH_VIEWBOX,
  SCENE_VIEWBOX, TOGGLE_SCENE,
} from "./fishMarkup";

// The Lead Shake mascot: a fish in a water bag. Ported from the master
// GSAP 2 animation file. All markup constants are static and trusted; no
// user input ever reaches dangerouslySetInnerHTML.

const COLORS = { aliveBody: "#ffb448", aliveFin: "#ff7b39", deadBody: "#ffdf9f", deadFin: "#f7b57f" };
const SURFACE = 272; // just under the drawn water_line (viewBox space)
const MOUTH = { x: 158, y: 406 }; // below the alive fish's eye

const rand = (min: number, max: number) => min + Math.random() * (max - min);

const part = (root: ParentNode, name: string) =>
  root.querySelector(`[data-part="${name}"]`) as SVGGraphicsElement | null;

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function safeBBox(el: SVGGraphicsElement | null) {
  try { return el ? el.getBBox() : null; } catch { return null; }
}

/* ---------- alive behaviour: subtle x/y wander, fin flaps, bubbles ---------- */
interface Bubble { el: SVGGraphicsElement; cx: number; cy: number; tl: TimelineMax | null }

function aliveController(svg: SVGSVGElement) {
  const fish = part(svg, "fish_alive-2");
  const fin = fish ? part(fish, "fin") : null;
  const bubbleEls = Array.from(svg.querySelectorAll<SVGGraphicsElement>('[data-part="bubbles"] > *'));
  const bubbles: Bubble[] = bubbleEls.map((el) => {
    const b = safeBBox(el);
    return { el, cx: b ? b.x + b.width / 2 : 0, cy: b ? b.y + b.height / 2 : 0, tl: null };
  });
  let active = false;
  let session = 0; // invalidates pending bubble callbacks after stop()

  function wander() {
    if (!active || !fish) return;
    TweenMax.to(fish, rand(2.5, 4), { x: rand(-12, 12), y: rand(-14, 4), ease: Sine.easeInOut, onComplete: wander });
  }

  function launch(b: Bubble, first: boolean, s: number) {
    if (!active || s !== session || !fish) return;
    const t = (fish as unknown as { _gsTransform?: { x: number; y: number } })._gsTransform || { x: 0, y: 0 };
    const startX = MOUTH.x + t.x + rand(-5, 5) - b.cx;
    const startY = MOUTH.y + t.y + rand(-4, 4) - b.cy;
    const endY = SURFACE + rand(0, 12) - b.cy;
    const scale = rand(0.5, 1.05);
    const dur = rand(2.4, 3.6);
    b.tl = new TimelineMax({
      delay: first ? rand(0, 2.5) : rand(0.2, 1.4),
      onComplete: () => launch(b, false, s),
    });
    b.tl.set(b.el, { x: startX, y: startY, scale, opacity: 0, transformOrigin: "50% 50%" })
      .to(b.el, 0.35, { opacity: 1 }, 0.01)
      .to(b.el, dur, { y: endY, ease: Sine.easeIn }, 0.01)
      .to(b.el, dur / 3, { x: `+=${rand(5, 9)}`, yoyo: true, repeat: 2, ease: Sine.easeInOut }, 0.01)
      .to(b.el, 0.3, { opacity: 0, scale: scale * 1.25 }, dur - 0.25);
  }

  return {
    fish,
    start() {
      active = true;
      session += 1;
      const s = session;
      if (bubbleEls.length) TweenMax.set(bubbleEls, { opacity: 0 });
      wander();
      if (fin) TweenMax.to(fin, 0.5, { rotation: 12, transformOrigin: "40% 10%", yoyo: true, repeat: -1, ease: Sine.easeInOut });
      bubbles.forEach((b, i) => { TweenMax.delayedCall(i * 0.5, () => launch(b, true, s)); });
    },
    stop() {
      active = false;
      session += 1;
      if (fish) TweenMax.killTweensOf(fish);
      if (fin) { TweenMax.killTweensOf(fin); TweenMax.set(fin, { rotation: 0 }); }
      bubbles.forEach((b) => {
        if (b.tl) b.tl.kill();
        TweenMax.to(b.el, 0.25, { opacity: 0 });
      });
    },
  };
}

function startWaterSwell(svg: SVGSVGElement, duration: number) {
  const water = part(svg, "water_line");
  if (water) TweenMax.fromTo(water, duration, { y: -3 }, { y: 3, yoyo: true, repeat: -1, ease: Sine.easeInOut });
  return water;
}

/* ---------- FishLogo: the animated brand mark ---------- */
export function FishLogo({ size = 36 }: { size?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const svg = ref.current;
    if (!svg || prefersReducedMotion()) return undefined;
    const water = startWaterSwell(svg, 2.6);
    const ctrl = aliveController(svg);
    ctrl.start();
    return () => { ctrl.stop(); if (water) TweenMax.killTweensOf(water); };
  }, []);
  return <svg ref={ref} viewBox={SCENE_VIEWBOX} width={size} height={size} role="img"
    aria-label="Lead Shake — a live fish in a bag of water"
    dangerouslySetInnerHTML={{ __html: ALIVE_SCENE }} />;
}

/* ---------- FishBadge: static alive/dead fish shown beside lead scores ----------
   Rendered once into hidden <defs> and reused via <use> so long lead tables stay light. */
const DEFS_ID = "lead-shake-fish-defs";

function ensureFishDefs() {
  if (typeof document === "undefined" || document.getElementById(DEFS_ID)) return;
  const holder = document.createElement("div");
  holder.setAttribute("aria-hidden", "true");
  holder.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  holder.innerHTML = `<svg id="${DEFS_ID}" xmlns="http://www.w3.org/2000/svg"><defs>` +
    `<g id="lead-shake-fish-alive">${ALIVE_FISH}</g>` +
    `<g id="lead-shake-fish-dead">${DEAD_FISH}</g>` +
    `</defs></svg>`;
  document.body.appendChild(holder);
}

export function FishBadge({ alive }: { alive: boolean }) {
  useEffect(() => { ensureFishDefs(); }, []);
  return <span className="fish-badge">
    <svg viewBox={alive ? ALIVE_FISH_VIEWBOX : DEAD_FISH_VIEWBOX} role="img"
      aria-label={alive ? "Strong lead" : "Weak lead"}>
      <use href={alive ? "#lead-shake-fish-alive" : "#lead-shake-fish-dead"} />
    </svg>
  </span>;
}

/* ---------- FishToggle: click the bag to shake (kill) or shock (revive) ---------- */
export function FishToggle() {
  const ref = useRef<SVGSVGElement>(null);
  const api = useRef<{ toggle: () => void } | null>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return undefined;
    const reduced = prefersReducedMotion();
    const ctrl = aliveController(svg);
    const fish = ctrl.fish;
    if (!fish) return undefined;
    const eyeA = part(fish, "eye");
    const eyeX = part(fish, "eye_dead");
    const bodyBg = part(fish, "body_bg");
    const finBg = part(fish, "top_fin_bg");
    const fx = part(svg, "revive_fx");
    const shockG = fx ? part(fx, "shock_animation") : null;
    const bolts = shockG ? Array.from(shockG.querySelectorAll<SVGGraphicsElement>("polyline, path")) : [];
    const surges = shockG ? Array.from(shockG.querySelectorAll<SVGGraphicsElement>("circle")) : [];

    // park the dead X eye exactly over the live eye
    const a = safeBBox(eyeA);
    const d = safeBBox(eyeX);
    if (a && d && eyeX) {
      TweenMax.set(eyeX, { x: a.x + a.width / 2 - (d.x + d.width / 2), y: a.y + a.height / 2 - (d.y + d.height / 2) });
    }
    const fishBox = safeBBox(fish);
    const floatY = fishBox ? 290 - fishBox.y : 0; // belly-up float, back just under the line

    let alive = true;
    let busy = false;
    let tl: TimelineMax | null = null;
    let water: SVGGraphicsElement | null = null;

    const setLabel = () => svg.setAttribute("aria-label", alive
      ? "The Lead Shake fish, alive in its bag. Activate to shake the bag."
      : "The fish went belly up. Activate to revive it.");
    setLabel();

    if (!reduced) {
      water = startWaterSwell(svg, 3.4);
      ctrl.start();
    }

    function deadBob() {
      TweenMax.to(fish, 3.2, { y: "+=14", yoyo: true, repeat: -1, ease: Sine.easeInOut });
      TweenMax.fromTo(fish, 4.6, { rotation: -1.5 }, { rotation: 1.5, transformOrigin: "50% 50%", yoyo: true, repeat: -1, ease: Sine.easeInOut });
    }

    function applyInstant(toAlive: boolean) {
      TweenMax.set(fish, { scaleY: toAlive ? 1 : -1, transformOrigin: "50% 50%", x: 0, y: toAlive ? 0 : floatY, rotation: 0 });
      if (bodyBg) TweenMax.set(bodyBg, { fill: toAlive ? COLORS.aliveBody : COLORS.deadBody });
      if (finBg) TweenMax.set(finBg, { fill: toAlive ? COLORS.aliveFin : COLORS.deadFin });
      if (eyeA) TweenMax.set(eyeA, { opacity: toAlive ? 1 : 0 });
      if (eyeX) TweenMax.set(eyeX, { opacity: toAlive ? 0 : 1 });
    }

    function kill() {
      ctrl.stop();
      tl = new TimelineMax({ onComplete() { deadBob(); alive = false; busy = false; setLabel(); } });
      // shake the whole bag, then flip belly-up, dull the colors, swap the eye
      tl.to(svg, 0.07, { y: -24, yoyo: true, repeat: 9, ease: Power1.easeInOut })
        .to(svg, 0.09, { rotation: 1.5, yoyo: true, repeat: 7, ease: Sine.easeInOut }, 0)
        .to(svg, 0.25, { y: 0, rotation: 0, ease: Power2.easeOut })
        .to(fish, 0.45, { scaleY: -1, transformOrigin: "50% 50%", ease: Power3.easeInOut }, "flip");
      if (bodyBg) tl.to(bodyBg, 0.5, { fill: COLORS.deadBody }, "flip");
      if (finBg) tl.to(finBg, 0.5, { fill: COLORS.deadFin }, "flip");
      if (eyeA) tl.set(eyeA, { opacity: 0 }, "flip+=0.22");
      if (eyeX) tl.set(eyeX, { opacity: 1 }, "flip+=0.22");
      tl.to(fish, 1.2, { y: floatY, ease: Sine.easeInOut });
    }

    function revive() {
      TweenMax.killTweensOf(fish); // stop the dead bob/sway
      const flash = () => {
        // random radial pattern each strike
        if (shockG) TweenMax.set(shockG, { rotation: rand(0, 360), svgOrigin: "304.36 300.35" });
        bolts.forEach((el) => TweenMax.set(el, { opacity: Math.random() < 0.45 ? 1 : 0 }));
      };
      tl = new TimelineMax({ onComplete() { ctrl.start(); alive = true; busy = false; setLabel(); } });
      if (fx) tl.set(fx, { opacity: 1 }, 0);
      if (surges.length) {
        tl.fromTo(surges, 0.12, { scale: 0.5, transformOrigin: "50% 50%" },
          { scale: 1.25, yoyo: true, repeat: 8, ease: Sine.easeInOut }, 0);
      }
      for (let i = 0; i < 12; i += 1) tl.call(flash, undefined, undefined, i * 0.09);
      tl.to(fish, 0.06, { x: "+=4", yoyo: true, repeat: 15, ease: Power1.easeInOut }, 0.05); // twitch
      if (fx) tl.set(fx, { opacity: 0 }, 1.15);
      // death in reverse: flip back, colors return, sink to the middle
      tl.to(fish, 0.45, { scaleY: 1, rotation: 0, transformOrigin: "50% 50%", ease: Power3.easeInOut }, 1.2);
      if (bodyBg) tl.to(bodyBg, 0.5, { fill: COLORS.aliveBody }, 1.2);
      if (finBg) tl.to(finBg, 0.5, { fill: COLORS.aliveFin }, 1.2);
      if (eyeA) tl.set(eyeA, { opacity: 1 }, 1.42);
      if (eyeX) tl.set(eyeX, { opacity: 0 }, 1.42);
      tl.to(fish, 1.0, { x: 0, y: 0, ease: Sine.easeInOut }, 1.3);
    }

    api.current = {
      toggle() {
        if (busy) return;
        if (reduced) { alive = !alive; applyInstant(alive); setLabel(); return; }
        busy = true;
        if (alive) kill(); else revive();
      },
    };

    return () => {
      api.current = null;
      ctrl.stop();
      if (tl) tl.kill();
      const targets: Array<Element | null> = [fish, water, fx, eyeA, eyeX, bodyBg, finBg, svg, ...bolts, ...surges];
      targets.forEach((el) => { if (el) TweenMax.killTweensOf(el); });
    };
  }, []);

  return <svg ref={ref} viewBox={SCENE_VIEWBOX} role="button" tabIndex={0}
    aria-label="The Lead Shake fish, alive in its bag. Activate to shake the bag."
    onClick={() => api.current?.toggle()}
    onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); api.current?.toggle(); }
    }}
    dangerouslySetInnerHTML={{ __html: TOGGLE_SCENE }} />;
}
