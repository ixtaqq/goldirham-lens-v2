"use client";

import { useEffect, useRef, type ReactNode } from "react";

import {
  BASE_ALPHA,
  LENS_ALPHA,
  layoutFor,
  PARALLAX_MAX,
  TILE_FACTOR,
  verifyPulse,
  type TraceLayout,
} from "@/lib/field";
import { MOTION_ENABLED } from "@/lib/motion-pref";

import { MOTION_EVENT } from "./MotionToggle";

type Mode = "webgl" | "canvas" | "poster";

const IDLE_FRAME_MS = 32;

interface Frame {
  width: number;
  height: number;
  time: number;
  parallax: number;
  lens: { x: number; y: number; r: number };
  box: { x: number; y: number; w: number; h: number } | null;
  pulse: { trace: number; strength: number };
}

interface Renderer {
  mode: Exclude<Mode, "poster">;
  resize(width: number, height: number, scale: number): void;
  draw(frame: Frame): void;
  dispose(): void;
}

const VERTEX = `#version 300 es
in vec2 a_point;
in vec2 a_meta;
uniform vec2 u_res;
uniform float u_time;
uniform float u_parallax;
uniform vec3 u_layout[16];
out vec2 v_px;
out float v_trace;
void main() {
  int i = int(a_meta.x);
  vec3 l = u_layout[i];
  float tile = u_res.x * ${TILE_FACTOR.toFixed(2)};
  float speed = tile / l.z;
  float x = (a_point.x + a_meta.y) * tile - mod(u_time * speed + float(i) * 37.0, tile);
  float y = (l.x + (0.5 - a_point.y) * l.y) * u_res.y - u_parallax;
  v_px = vec2(x, y);
  v_trace = a_meta.x;
  gl_Position = vec4(x / u_res.x * 2.0 - 1.0, 1.0 - y / u_res.y * 2.0, 0.0, 1.0);
  gl_PointSize = 3.0;
}`;

const FRAGMENT = `#version 300 es
precision mediump float;
in vec2 v_px;
in float v_trace;
uniform vec3 u_lens;
uniform vec4 u_box;
uniform vec2 u_pulse;
uniform float u_points;
out vec4 color;
void main() {
  float d = distance(v_px, u_lens.xy);
  float lens = 1.0 - smoothstep(u_lens.z - 10.0, u_lens.z, d);
  float alpha = mix(${BASE_ALPHA.toFixed(2)}, ${LENS_ALPHA.toFixed(2)}, lens);
  if (u_points > 0.5) alpha = lens * 0.9;
  bool inside = v_px.x > u_box.x && v_px.x < u_box.x + u_box.z && v_px.y > u_box.y && v_px.y < u_box.y + u_box.w;
  float verify = (inside && abs(v_trace - u_pulse.x) < 0.5) ? u_pulse.y : 0.0;
  vec3 fog = vec3(0.553, 0.600, 0.573);
  vec3 mint = vec3(0.475, 0.835, 0.761);
  vec3 rgb = mix(fog, mint, verify);
  alpha = max(alpha, verify * 0.95);
  color = vec4(rgb * alpha, alpha);
}`;

function buildGeometry(traces: number[][]) {
  const lines: number[] = [];
  const lineMeta: number[] = [];
  const points: number[] = [];
  const pointMeta: number[] = [];
  traces.forEach((values, trace) => {
    const last = values.length - 1;
    for (let copy = 0; copy < 2; copy += 1) {
      for (let i = 0; i < last; i += 1) {
        lines.push(i / last, values[i] ?? 0, (i + 1) / last, values[i + 1] ?? 0);
        lineMeta.push(trace, copy, trace, copy);
      }
      values.forEach((value, i) => {
        points.push(i / last, value);
        pointMeta.push(trace, copy);
      });
    }
  });
  return {
    lines: new Float32Array(lines),
    lineMeta: new Float32Array(lineMeta),
    points: new Float32Array(points),
    pointMeta: new Float32Array(pointMeta),
  };
}

function webglRenderer(canvas: HTMLCanvasElement, layout: TraceLayout[], traces: number[][]): Renderer | null {
  const gl = canvas.getContext("webgl2", { alpha: true, antialias: false, premultipliedAlpha: true });
  if (!gl) return null;
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
  };
  const vs = compile(gl.VERTEX_SHADER, VERTEX);
  const fs = compile(gl.FRAGMENT_SHADER, FRAGMENT);
  const program = gl.createProgram();
  if (!vs || !fs || !program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  const geometry = buildGeometry(traces);
  const vao = (data: Float32Array, meta: Float32Array) => {
    const array = gl.createVertexArray();
    gl.bindVertexArray(array);
    for (const [name, values] of [
      ["a_point", data],
      ["a_meta", meta],
    ] as const) {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW);
      const location = gl.getAttribLocation(program, name);
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0);
    }
    return array;
  };
  const lineVao = vao(geometry.lines, geometry.lineMeta);
  const pointVao = vao(geometry.points, geometry.pointMeta);
  const u = (name: string) => gl.getUniformLocation(program, name);
  const uniforms = {
    res: u("u_res"),
    time: u("u_time"),
    parallax: u("u_parallax"),
    layout: u("u_layout"),
    lens: u("u_lens"),
    box: u("u_box"),
    pulse: u("u_pulse"),
    points: u("u_points"),
  };
  gl.uniform3fv(uniforms.layout, new Float32Array(layout.flatMap((l) => [l.band, l.amp, l.cycle])));
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

  return {
    mode: "webgl",
    resize(width, height, scale) {
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      gl.viewport(0, 0, canvas.width, canvas.height);
    },
    draw(frame) {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(uniforms.res, frame.width, frame.height);
      gl.uniform1f(uniforms.time, frame.time);
      gl.uniform1f(uniforms.parallax, frame.parallax);
      gl.uniform3f(uniforms.lens, frame.lens.x, frame.lens.y, frame.lens.r);
      const box = frame.box ?? { x: -1, y: -1, w: 0, h: 0 };
      gl.uniform4f(uniforms.box, box.x, box.y, box.w, box.h);
      gl.uniform2f(uniforms.pulse, frame.pulse.trace % traces.length, frame.pulse.strength);
      gl.uniform1f(uniforms.points, 0);
      gl.bindVertexArray(lineVao);
      gl.drawArrays(gl.LINES, 0, geometry.lines.length / 2);
      gl.uniform1f(uniforms.points, 1);
      gl.bindVertexArray(pointVao);
      gl.drawArrays(gl.POINTS, 0, geometry.points.length / 2);
    },
    dispose() {
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    },
  };
}

function canvasRenderer(canvas: HTMLCanvasElement, layout: TraceLayout[], traces: number[][]): Renderer | null {
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  let scale = 1;
  const path = (frame: Frame, index: number) => {
    const values = traces[index] ?? [];
    const l = layout[index];
    const p = new Path2D();
    if (!l || values.length < 2) return p;
    const tile = frame.width * TILE_FACTOR;
    const shift = (frame.time * (tile / l.cycle) + index * 37) % tile;
    const last = values.length - 1;
    for (let copy = 0; copy < 2; copy += 1) {
      values.forEach((value, i) => {
        const x = (i / last + copy) * tile - shift;
        const y = (l.band + (0.5 - value) * l.amp) * frame.height - frame.parallax;
        if (i === 0) p.moveTo(x, y);
        else p.lineTo(x, y);
      });
    }
    return p;
  };
  return {
    mode: "canvas",
    resize(width, height, nextScale) {
      scale = nextScale;
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
    },
    draw(frame) {
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.clearRect(0, 0, frame.width, frame.height);
      ctx.lineWidth = 1;
      const paths = layout.map((_, index) => path(frame, index));
      ctx.strokeStyle = `rgba(141,153,146,${BASE_ALPHA})`;
      paths.forEach((p) => ctx.stroke(p));
      ctx.save();
      ctx.beginPath();
      ctx.arc(frame.lens.x, frame.lens.y, frame.lens.r, 0, Math.PI * 2);
      ctx.clip();
      ctx.strokeStyle = `rgba(141,153,146,${LENS_ALPHA})`;
      paths.forEach((p) => ctx.stroke(p));
      ctx.restore();
      if (frame.box && frame.pulse.strength > 0) {
        const active = paths[frame.pulse.trace % paths.length];
        if (active) {
          ctx.save();
          ctx.beginPath();
          ctx.rect(frame.box.x, frame.box.y, frame.box.w, frame.box.h);
          ctx.clip();
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = `rgba(121,213,194,${0.95 * frame.pulse.strength})`;
          ctx.stroke(active);
          ctx.restore();
        }
      }
    },
    dispose() {},
  };
}

/** Full-viewport motion background. Poster first; the live field fades in after first paint. */
export function SignalField({ traces, session, poster }: { traces: number[][]; session: string; poster: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = root.current;
    const canvas = canvasRef.current;
    if (!MOTION_ENABLED || !element || !canvas) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches) {
      element.dataset.field = "poster";
      return;
    }
    const layout = layoutFor(traces.length);
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    let renderer: Renderer | null = null;
    let raf = 0;
    let running = false;
    let start = 0;
    let width = 0;
    let height = 0;
    let scale = 1;
    let pointer: { x: number; y: number } | null = null;
    let slowFrames = 0;
    let last = 0;
    let lastDraw = 0;
    let pointerAt = -Infinity;
    let scrollingUntil = 0;
    let parallax = 0;
    let heroVisible = true;
    let labelWidth = 0;
    const frameSvg = document.querySelector("[data-verify-frame] svg");

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const cap = width < 768 ? 1.5 : 2;
      scale = Math.min(window.devicePixelRatio || 1, cap) * (slowFrames > 30 ? 0.5 : 1);
      // One parallax step taller, so the shifted canvas never uncovers its bottom edge.
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height + PARALLAX_MAX}px`;
      renderer?.resize(width, height + PARALLAX_MAX, scale);
    };

    const frameBox = () => {
      if (!frameSvg) return null;
      const rect = frameSvg.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > height) return null;
      const unit = rect.width / 120;
      return { x: rect.left + 46 * unit, y: rect.top + 22 * unit, w: 52 * unit, h: 52 * unit };
    };

    const tick = (now: number) => {
      if (!running || !renderer) return;
      raf = requestAnimationFrame(tick);
      if (!start) start = now;
      if (last && now - last > 24) slowFrames += 1;
      if (slowFrames === 31) resize();
      last = now;
      // The drift is slow, so the field redraws at about 30fps unless the pointer steers the lens,
      // and holds its frame while the page scrolls; parallax moves the canvas on the compositor.
      if (now < scrollingUntil) return;
      if (now - lastDraw < IDLE_FRAME_MS && now - pointerAt > 250) return;
      lastDraw = now;
      const scroll = window.scrollY;
      const small = width < 768;
      const lens = pointer ?? {
        x: width * (small ? 0.74 : 0.86),
        y: height * (small ? 0.64 : 0.24) + Math.sin(scroll * 0.002) * 40,
      };
      const r = width < 768 ? 80 : 104;
      const box = frameBox();
      renderer.draw({
        width,
        height: height + PARALLAX_MAX,
        time: (now - start) / 1000,
        parallax: 0,
        lens: { x: lens.x, y: lens.y + parallax, r },
        box: box && { ...box, y: box.y + parallax },
        pulse: verifyPulse(now - start),
      });
      const label = labelRef.current;
      if (label) {
        const x = Math.min(lens.x + r * 0.72, width - labelWidth - 12);
        label.style.transform = `translate(${x}px, ${lens.y + r * 0.72}px)`;
      }
    };

    const paused = () => document.documentElement.classList.contains("motion-paused");
    const play = () => {
      if (running || !renderer || !heroVisible || document.hidden || paused() || reduce.matches) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };
    const sync = () => (!heroVisible || document.hidden || paused() || reduce.matches ? stop() : play());

    const onScroll = (event: Event) => {
      scrollingUntil = event.timeStamp + 150;
      parallax = Math.min(window.scrollY * 0.05, PARALLAX_MAX);
      canvas.style.transform = `translate3d(0, ${-parallax}px, 0)`;
    };

    const onPointer = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      pointer = { x: event.clientX, y: event.clientY };
      pointerAt = event.timeStamp;
    };

    const boot = () => {
      renderer = webglRenderer(canvas, layout, traces) ?? canvasRenderer(canvas, layout, traces);
      element.dataset.field = renderer?.mode ?? "poster";
      if (!renderer) return;
      resize();
      labelWidth = labelRef.current?.offsetWidth ?? 0;
      play();
      requestAnimationFrame(() => element.classList.add("field-live"));
    };

    const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 200));
    const handle = idle(boot);
    // Parallax and the verification moment live in the hero; below it the field holds its last frame.
    const observer = new IntersectionObserver(([entry]) => {
      heroVisible = entry?.isIntersecting ?? true;
      sync();
    });
    observer.observe(document.getElementById("top") ?? canvas);
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", onScroll, { passive: true });
    if (!coarse) window.addEventListener("pointermove", onPointer, { passive: true });
    document.addEventListener("visibilitychange", sync);
    window.addEventListener(MOTION_EVENT, sync);
    reduce.addEventListener("change", sync);

    return () => {
      stop();
      if (typeof handle === "number") window.cancelIdleCallback?.(handle);
      observer.disconnect();
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener(MOTION_EVENT, sync);
      reduce.removeEventListener("change", sync);
      renderer?.dispose();
    };
  }, [traces]);

  return (
    <div ref={root} className="signal-field ledger-ground pointer-events-none fixed inset-0 -z-10" aria-hidden="true" data-field="poster">
      <div className="field-poster absolute inset-0">{poster}</div>
      <canvas ref={canvasRef} className="field-canvas absolute inset-0" />
      <div ref={labelRef} className="field-lens-label label absolute left-0 top-0 whitespace-nowrap text-[0.6875rem]">
        demo feed · {session}
      </div>
    </div>
  );
}
