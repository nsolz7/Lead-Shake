// Compatibility typings for the legacy TweenMax/TimelineMax API exposed by
// the maintained GSAP 3 package. The animation is a direct port of the
// hand-tuned Lead Shake master file, so loose typing here is intentional.
declare module "gsap" {
  export const gsap: any;
  export const TweenMax: any;
  export const TweenLite: any;
  export class TimelineMax {
    constructor(vars?: Record<string, unknown>);
    to(...args: unknown[]): this;
    fromTo(...args: unknown[]): this;
    set(...args: unknown[]): this;
    call(...args: unknown[]): this;
    kill(): this;
  }
  export const Sine: any;
  export const Power1: any;
  export const Power2: any;
  export const Power3: any;
  export const Linear: any;
}
