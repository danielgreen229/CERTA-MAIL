import * as THREE from "three";

const gsap = window.gsap;
const ScrollTrigger = window.ScrollTrigger;
gsap.registerPlugin(ScrollTrigger);

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const isTouch = matchMedia("(hover: none), (pointer: coarse)").matches;
const isSmall = innerWidth < 760;

/* =========================================================
   Разбивка текста на буквы / слова
   ========================================================= */
const splitChars = (root) => {
  const walk = (node) => {
    [...node.childNodes].forEach((child) => {
      if (child.nodeType === Node.TEXT_NODE) {
        const frag = document.createDocumentFragment();
        child.textContent.split(/(\s+)/).forEach((token) => {
          if (!token) return;
          if (/^\s+$/.test(token)) { frag.append(token); return; }
          const word = document.createElement("span");
          word.className = "wd";
          [...token].forEach((ch) => {
            const span = document.createElement("span");
            span.className = "char";
            span.textContent = ch;
            word.append(span);
          });
          frag.append(word);
        });
        child.replaceWith(frag);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        walk(child);
      }
    });
  };
  walk(root);
};

const splitWords = (el, className) => {
  const words = el.textContent.trim().split(/\s+/);
  el.innerHTML = words
    .map((w) => (className === "w" ? `<span class="w"><span>${w}</span></span>` : `<span class="${className}">${w}</span>`))
    .join(" ");
};

document.querySelectorAll(".split-chars").forEach(splitChars);
document.querySelectorAll(".split-words").forEach((el) => splitWords(el, "w"));
document.querySelectorAll(".scrub-words").forEach((el) => splitWords(el, "word"));

/* =========================================================
   WebGL: облако частиц, которое перетекает между формами
   ========================================================= */
const canvas = document.getElementById("gl");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x070b12, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x070b12, 0.06);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, 0, 8);

const COUNT = isSmall ? 5000 : 11000;
const rand = (a, b) => a + Math.random() * (b - a);

const shapeSphere = (i) => {
  const phi = Math.acos(1 - (2 * (i + 0.5)) / COUNT);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  const r = 2.4 + rand(-0.06, 0.06) + (Math.random() > 0.92 ? rand(0.2, 1.2) : 0);
  return [r * Math.cos(theta) * Math.sin(phi), r * Math.sin(theta) * Math.sin(phi), r * Math.cos(phi)];
};
const shapeKnot = () => {
  const t = Math.random() * Math.PI * 2;
  const p = 2, q = 3, R = 1.7, tube = 0.42;
  const r = R + 0.6 * Math.cos(q * t);
  const cx = r * Math.cos(p * t), cy = r * Math.sin(p * t), cz = 0.6 * Math.sin(q * t);
  const a = Math.random() * Math.PI * 2, d = tube * Math.sqrt(Math.random());
  return [cx + d * Math.cos(a), cy + d * Math.sin(a), cz + d * Math.cos(a + 1.3)];
};
const shapeWave = (i) => {
  const side = Math.ceil(Math.sqrt(COUNT));
  const gx = (i % side) / side - 0.5, gz = Math.floor(i / side) / side - 0.5;
  const x = gx * 11, z = gz * 11;
  const y = Math.sin(x * 0.9) * 0.45 + Math.cos(z * 1.1) * 0.45 - 1.2;
  return [x, y, z];
};
const shapeHelix = (i) => {
  const t = (i / COUNT) * Math.PI * 10 - Math.PI * 5;
  const strand = i % 3;
  const r = 1.3;
  if (strand === 2) {
    const k = Math.random();
    const a = Math.round(t * 2) / 2;
    return [Math.cos(a) * r * (2 * k - 1), a * 0.42, Math.sin(a) * r * (2 * k - 1)];
  }
  const off = strand * Math.PI;
  return [Math.cos(t + off) * r + rand(-0.05, 0.05), t * 0.42, Math.sin(t + off) * r + rand(-0.05, 0.05)];
};
const shapeGalaxy = () => {
  const arms = 4;
  const arm = Math.floor(Math.random() * arms);
  const d = Math.pow(Math.random(), 0.7) * 4.2;
  const a = (arm / arms) * Math.PI * 2 + d * 1.1 + rand(-0.25, 0.25) / (d * 0.3 + 0.4);
  return [Math.cos(a) * d, rand(-0.12, 0.12) * (4.5 - d) * 0.4, Math.sin(a) * d];
};

const SHAPES = [shapeSphere, shapeKnot, shapeWave, shapeHelix, shapeGalaxy];
const geometry = new THREE.BufferGeometry();
SHAPES.forEach((fn, s) => {
  const arr = new Float32Array(COUNT * 3);
  for (let i = 0; i < COUNT; i++) arr.set(fn(i), i * 3);
  geometry.setAttribute(s === 0 ? "position" : `p${s}`, new THREE.BufferAttribute(arr, 3));
});
const rnd = new Float32Array(COUNT);
for (let i = 0; i < COUNT; i++) rnd[i] = Math.random();
geometry.setAttribute("aRand", new THREE.BufferAttribute(rnd, 1));

const uniforms = {
  uTime: { value: 0 },
  uFrom: { value: 0 },
  uTo: { value: 0 },
  uMix: { value: 1 },
  uHue: { value: 0 },
  uIntro: { value: 0 },
  uVel: { value: 0 },
  uDim: { value: 1 },
  uPixel: { value: renderer.getPixelRatio() },
  uMouse: { value: new THREE.Vector3(99, 99, 0) },
};

const material = new THREE.ShaderMaterial({
  uniforms,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
  vertexShader: /* glsl */ `
    attribute vec3 p1; attribute vec3 p2; attribute vec3 p3; attribute vec3 p4;
    attribute float aRand;
    uniform float uTime, uFrom, uTo, uMix, uIntro, uVel, uPixel;
    uniform vec3 uMouse;
    varying float vRand; varying float vAlpha;

    vec3 shapeAt(float i) {
      if (i < 0.5) return position;
      if (i < 1.5) return p1;
      if (i < 2.5) return p2;
      if (i < 3.5) return p3;
      return p4;
    }

    void main() {
      vRand = aRand;
      float m = smoothstep(0.0, 1.0, clamp((uMix - aRand * 0.35) / 0.65, 0.0, 1.0));
      vec3 a = shapeAt(uFrom);
      vec3 b = shapeAt(uTo);
      vec3 pos = mix(a, b, m);

      // во время перехода частицы разлетаются по дуге
      float burst = sin(m * 3.14159);
      pos += normalize(pos + 0.001) * burst * (0.6 + aRand * 1.4);
      pos.y += burst * sin(aRand * 40.0) * 0.6;

      // дыхание
      float t = uTime * 0.6 + aRand * 6.2831;
      pos += vec3(sin(t), cos(t * 1.3), sin(t * 0.7)) * 0.035;

      // интро: собираются из облака
      pos *= mix(5.0 + aRand * 6.0, 1.0, uIntro);

      vec4 world = modelMatrix * vec4(pos, 1.0);
      // отталкивание от курсора
      vec3 toM = world.xyz - uMouse;
      float dm = length(toM.xy);
      world.xyz += normalize(toM + 0.0001) * smoothstep(1.6, 0.0, dm) * 0.7;

      vec4 mv = viewMatrix * world;
      gl_Position = projectionMatrix * mv;
      float size = (1.0 + aRand * 2.2) * (1.0 + abs(uVel) * 0.6);
      gl_PointSize = min(size * uPixel * 14.0 / -mv.z, 7.0 * uPixel);
      vAlpha = uIntro * (0.35 + aRand * 0.65);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform float uHue, uDim;
    varying float vRand; varying float vAlpha;
    void main() {
      vec2 c = gl_PointCoord - 0.5;
      float d = length(c);
      if (d > 0.5) discard;
      float glow = pow(1.0 - d * 2.0, 1.8);
      vec3 ice = vec3(0.72, 0.80, 0.91);
      vec3 navy = vec3(0.23, 0.32, 0.47);
      vec3 red = vec3(0.88, 0.31, 0.36);
      vec3 col = mix(navy, ice, smoothstep(0.2, 0.9, vRand));
      float redAmt = smoothstep(0.0, 1.0, uHue * 1.3 - vRand * 0.6);
      col = mix(col, red, redAmt);
      if (vRand > 0.965) col = red * 1.3;
      gl_FragColor = vec4(col, glow * vAlpha * 0.9 * uDim);
    }
  `,
});

const points = new THREE.Points(geometry, material);
const group = new THREE.Group();
group.add(points);
scene.add(group);

// мягкие кольца-орбиты для глубины
const ringMat = new THREE.LineBasicMaterial({ color: 0x3a5277, transparent: true, opacity: 0.25 });
const rings = new THREE.Group();
[3.4, 4.3, 5.4].forEach((r, i) => {
  const pts = [];
  for (let k = 0; k <= 128; k++) { const a = (k / 128) * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); }
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMat);
  line.rotation.x = 1.1 + i * 0.25;
  line.rotation.y = i * 0.6;
  rings.add(line);
});
scene.add(rings);

const setShape = (index, hue) => {
  if (index === uniforms.uTo.value) {
    gsap.to(uniforms.uHue, { value: hue, duration: 1.6, ease: "power2.out" });
    return;
  }
  uniforms.uFrom.value = uniforms.uMix.value > 0.5 ? uniforms.uTo.value : uniforms.uFrom.value;
  uniforms.uTo.value = index;
  uniforms.uMix.value = 0;
  gsap.to(uniforms.uMix, { value: 1, duration: reduceMotion ? 0.01 : 2.2, ease: "power3.inOut", overwrite: true });
  gsap.to(uniforms.uHue, { value: hue, duration: 1.6, ease: "power2.out" });
};

// позиция облака: справа в hero, по центру дальше
const layout = { x: isSmall ? 0 : 2.4, y: 0, z: 0 };
const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
const raycastPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
let velocity = 0;

addEventListener("pointermove", (e) => {
  mouse.tx = (e.clientX / innerWidth) * 2 - 1;
  mouse.ty = -(e.clientY / innerHeight) * 2 + 1;
  ndc.set(mouse.tx, mouse.ty);
  ray.setFromCamera(ndc, camera);
  ray.ray.intersectPlane(raycastPlane, uniforms.uMouse.value);
});

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const clock = new THREE.Clock();
const render = () => {
  const dt = Math.min(clock.getDelta(), 0.05);
  uniforms.uTime.value += dt;
  mouse.x += (mouse.tx - mouse.x) * 0.05;
  mouse.y += (mouse.ty - mouse.y) * 0.05;
  uniforms.uVel.value += (velocity - uniforms.uVel.value) * 0.1;

  group.rotation.y += dt * (0.08 + Math.abs(uniforms.uVel.value) * 0.6);
  group.rotation.x = mouse.y * 0.25 + Math.sin(uniforms.uTime.value * 0.2) * 0.1;
  group.rotation.z = mouse.x * -0.1;
  group.position.x += (layout.x - group.position.x) * 0.04;
  group.position.y += (layout.y - group.position.y) * 0.04;
  rings.rotation.z += dt * 0.05;
  rings.position.copy(group.position);
  camera.position.x = mouse.x * 0.6;
  camera.position.y = mouse.y * 0.4;
  camera.position.z += (8 + layout.z - camera.position.z) * 0.05;
  camera.lookAt(0, 0, 0);

  renderer.render(scene, camera);
  requestAnimationFrame(render);
};
render();

/* =========================================================
   Плавный скролл
   ========================================================= */
let lenis = null;
if (window.Lenis && !reduceMotion) {
  lenis = new window.Lenis({ lerp: 0.09, smoothWheel: true });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
  lenis.stop();
}

document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener("click", (e) => {
    const target = document.querySelector(a.getAttribute("href"));
    if (!target) return;
    e.preventDefault();
    if (lenis) lenis.scrollTo(target, { duration: 1.6 });
    else target.scrollIntoView({ behavior: "smooth" });
  });
});

/* =========================================================
   Видео: ленивые слоты под ролики из media/
   ========================================================= */
const videoSlots = [...document.querySelectorAll("[data-video]")];
videoSlots.forEach((slot) => {
  const file = slot.dataset.video;
  if (slot.dataset.label) {
    slot.insertAdjacentHTML("beforeend", `<div class="ph"><div class="ph__play"></div><div class="ph__label">${slot.dataset.label}</div><div class="ph__file">${file}</div></div>`);
  }
  const video = document.createElement("video");
  Object.assign(video, { muted: true, loop: true, playsInline: true, preload: "none" });
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.addEventListener("loadeddata", () => slot.classList.add("has-video"));
  slot.prepend(video);
  slot._video = video;
  slot._file = file;
});

const videoObserver = new IntersectionObserver((entries) => {
  entries.forEach(({ target, isIntersecting }) => {
    const video = target._video;
    if (isIntersecting) {
      if (!video.src) { video.src = target._file; video.preload = "auto"; }
      video.play().catch(() => {});
    } else if (video.src) {
      video.pause();
    }
  });
}, { rootMargin: "200px 0px" });
videoSlots.forEach((slot) => videoObserver.observe(slot));

/* =========================================================
   Курсор, магнитные кнопки, 3D-наклон
   ========================================================= */
if (!isTouch) {
  const cursor = document.querySelector(".cursor");
  const dot = cursor.querySelector(".cursor__dot");
  const ring = cursor.querySelector(".cursor__ring");
  const dotX = gsap.quickTo(dot, "x", { duration: 0.1 });
  const dotY = gsap.quickTo(dot, "y", { duration: 0.1 });
  const ringX = gsap.quickTo(ring, "x", { duration: 0.5, ease: "power3" });
  const ringY = gsap.quickTo(ring, "y", { duration: 0.5, ease: "power3" });
  addEventListener("pointermove", (e) => { dotX(e.clientX); dotY(e.clientY); ringX(e.clientX); ringY(e.clientY); });
  document.querySelectorAll("a, .frame, .terminal").forEach((el) => {
    el.addEventListener("pointerenter", () => cursor.classList.add("is-hover"));
    el.addEventListener("pointerleave", () => cursor.classList.remove("is-hover"));
  });

  document.querySelectorAll("[data-magnetic]").forEach((el) => {
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      gsap.to(el, { x: (e.clientX - r.left - r.width / 2) * 0.35, y: (e.clientY - r.top - r.height / 2) * 0.35, duration: 0.4, ease: "power3.out" });
    });
    el.addEventListener("pointerleave", () => gsap.to(el, { x: 0, y: 0, duration: 0.9, ease: "elastic.out(1, 0.35)" }));
  });

  document.querySelectorAll("[data-tilt]").forEach((el) => {
    const glare = el.querySelector(".frame__glare");
    const rx = gsap.quickTo(el, "rotationX", { duration: 0.6, ease: "power3" });
    const ry = gsap.quickTo(el, "rotationY", { duration: 0.6, ease: "power3" });
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      ry((px - 0.5) * 16);
      rx(-(py - 0.5) * 12);
      if (glare) { glare.style.setProperty("--gx", `${px * 100}%`); glare.style.setProperty("--gy", `${py * 100}%`); }
    });
    el.addEventListener("pointerleave", () => { rx(0); ry(0); });
  });

  const floats = document.querySelectorAll(".hero__float");
  addEventListener("pointermove", (e) => {
    const cx = e.clientX / innerWidth - 0.5, cy = e.clientY / innerHeight - 0.5;
    floats.forEach((f) => {
      const d = parseFloat(f.dataset.depth);
      gsap.to(f, { x: cx * 60 * d, y: cy * 40 * d, rotationY: cx * 20 * d, rotationX: -cy * 14 * d, duration: 1, ease: "power2.out" });
    });
  });
}

/* =========================================================
   Скролл-анимации
   ========================================================= */
const buildScroll = () => {
  // прогресс и навбар
  gsap.to("#progress", { scaleX: 1, ease: "none", scrollTrigger: { start: 0, end: "max", scrub: 0.3 } });
  ScrollTrigger.create({
    start: 80,
    end: "max",
    onToggle: (self) => document.querySelector(".nav").classList.toggle("is-scrolled", self.isActive),
    onUpdate: (self) => { velocity = gsap.utils.clamp(-3, 3, self.getVelocity() / 2500); },
  });

  // форма облака по секциям
  document.querySelectorAll("[data-shape]").forEach((el) => {
    ScrollTrigger.create({
      trigger: el,
      start: "top 55%",
      end: "bottom 45%",
      onToggle: (self) => { if (self.isActive) setShape(+el.dataset.shape, +el.dataset.hue); },
    });
  });

  // облако уезжает в центр после hero
  ScrollTrigger.create({
    trigger: ".hero",
    start: "top top",
    end: "bottom top",
    scrub: true,
    onUpdate: (self) => {
      layout.x = (isSmall ? 0 : 2.4) * (1 - self.progress);
      layout.z = self.progress * 2.5;
      uniforms.uDim.value = 1 - self.progress * 0.45;
    },
  });

  // hero уходит с параллаксом
  gsap.to(".hero__inner", { yPercent: -18, opacity: 0, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });
  gsap.to(".hero__float", { y: (i) => -120 - i * 80, opacity: 0, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "80% top", scrub: true } });

  // marquee реагирует на скорость скролла
  const skew = gsap.quickTo(".marquee__track", "skewX", { duration: 0.5, ease: "power3" });
  gsap.ticker.add(() => skew(velocity * -6));

  // манифест: слова загораются
  gsap.to(".manifest .word", {
    opacity: 1,
    stagger: 0.08,
    ease: "none",
    scrollTrigger: { trigger: ".manifest", start: "top 75%", end: "bottom 55%", scrub: 0.6 },
  });

  // заголовки по словам
  document.querySelectorAll(".split-words").forEach((el) => {
    gsap.from(el.querySelectorAll(".w > span"), {
      yPercent: 110,
      rotate: 6,
      duration: 1.1,
      stagger: 0.06,
      ease: "power4.out",
      scrollTrigger: { trigger: el, start: "top 85%" },
    });
  });

  // фичи
  document.querySelectorAll(".feature").forEach((feature) => {
    const media = feature.querySelector(".feature__media");
    const flip = feature.classList.contains("feature--flip");
    gsap.fromTo(media,
      { rotationX: 28, rotationY: flip ? 18 : -18, y: 140, scale: 0.82, opacity: 0, transformPerspective: 1400 },
      { rotationX: 0, rotationY: 0, y: 0, scale: 1, opacity: 1, ease: "power2.out", scrollTrigger: { trigger: feature, start: "top 90%", end: "top 30%", scrub: 1 } });
    gsap.to(media, { y: -60, ease: "none", scrollTrigger: { trigger: feature, start: "center center", end: "bottom top", scrub: true } });

    gsap.from(feature.querySelector(".feature__num"), { yPercent: 60, opacity: 0, duration: 1.4, ease: "expo.out", scrollTrigger: { trigger: feature, start: "top 75%" } });
    gsap.to(feature.querySelector(".feature__num"), { y: -80, ease: "none", scrollTrigger: { trigger: feature, start: "top bottom", end: "bottom top", scrub: true } });
    gsap.from(feature.querySelector("p"), { y: 30, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: feature, start: "top 70%" } });
    gsap.from(feature.querySelectorAll(".chips li"), { y: 20, opacity: 0, scale: 0.8, duration: 0.7, stagger: 0.07, ease: "back.out(2)", scrollTrigger: { trigger: feature, start: "top 65%" } });
  });

  // конвейер — горизонтальный скролл на десктопе
  const mm = gsap.matchMedia();
  mm.add("(min-width: 761px)", () => {
    const track = document.querySelector(".pipeline__track");
    const line = document.querySelector(".pipeline__line");
    line.style.width = `${track.scrollWidth}px`;
    const distance = () => track.scrollWidth - innerWidth;
    const tween = gsap.to([track, line], {
      x: () => -distance(),
      ease: "none",
      scrollTrigger: { trigger: ".pipeline", start: "top top", end: () => `+=${distance()}`, pin: true, scrub: 1, invalidateOnRefresh: true },
    });
    gsap.to("#pipePath", { strokeDashoffset: -400, ease: "none", scrollTrigger: { trigger: ".pipeline", start: "top top", end: () => `+=${distance()}`, scrub: true } });
    track.querySelectorAll("li").forEach((li) => {
      gsap.fromTo(li,
        { rotationY: -35, z: -200, opacity: 0.25, transformPerspective: 1000 },
        { rotationY: 0, z: 0, opacity: 1, ease: "power2.out", scrollTrigger: { trigger: li, containerAnimation: tween, start: "left 95%", end: "left 55%", scrub: true } });
      gsap.from(li.querySelector("span"), { scale: 0, rotate: -180, ease: "back.out(2)", scrollTrigger: { trigger: li, containerAnimation: tween, start: "left 85%", end: "left 65%", scrub: true } });
    });
  });
  mm.add("(max-width: 760px)", () => {
    gsap.utils.toArray(".pipeline__track li").forEach((li) => {
      gsap.from(li, { y: 60, opacity: 0, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: li, start: "top 88%" } });
    });
  });

  // счётчики
  document.querySelectorAll("[data-count]").forEach((el) => {
    const end = parseFloat(el.dataset.count);
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const state = { v: 0 };
    const fmt = (v) => v.toFixed(decimals).replace(".", ",");
    el.textContent = fmt(0);
    gsap.to(state, {
      v: end, duration: 2.2, ease: "power3.out",
      onUpdate: () => { el.textContent = fmt(state.v); },
      scrollTrigger: { trigger: el, start: "top 85%" },
    });
  });
  gsap.from(".stat", { y: 80, opacity: 0, duration: 1.2, stagger: 0.12, ease: "expo.out", scrollTrigger: { trigger: ".numbers", start: "top 75%" } });

  // финальный заголовок по буквам
  gsap.from(".start__title .char", { yPercent: 120, rotate: 12, duration: 1.2, stagger: 0.035, ease: "expo.out", scrollTrigger: { trigger: ".start", start: "top 70%" } });
  gsap.fromTo(".terminal", { rotationX: 40, y: 120, opacity: 0, transformPerspective: 1400 }, { rotationX: 0, y: 0, opacity: 1, ease: "power2.out", scrollTrigger: { trigger: ".terminal", start: "top 95%", end: "top 45%", scrub: 1 } });
  ScrollTrigger.create({ trigger: ".terminal", start: "top 65%", once: true, onEnter: typeTerminal });

  // футер
  gsap.from(".footer__big", { yPercent: 40, opacity: 0, ease: "none", scrollTrigger: { trigger: ".footer", start: "top bottom", end: "bottom bottom", scrub: true } });
};

/* =========================================================
   Терминал печатает
   ========================================================= */
const TERMINAL = [
  ["cmd", "cd lead-assistant"],
  ["cmd", "docker compose up -d"],
  ["dim", "[+] Running 2/2"],
  ["ok", " ✔ Container llm   Started"],
  ["ok", " ✔ Container web   Started"],
  ["cmd", ".venv/bin/process-leads"],
  ["dim", "→ list_leads(status=\"new\")"],
  ["dim", "→ get_lead · извлечение цитат · проверка черновика"],
  ["dim", "→ update_lead · status=processed"],
  ["ok", "✔ Сводка готова: runs/<run_id>/summary.md"],
];
let typed = false;
function typeTerminal() {
  if (typed) return;
  typed = true;
  const el = document.getElementById("terminal");
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  let html = "";
  let lineIdx = 0;
  const caret = '<span class="caret"></span>';
  const next = () => {
    if (lineIdx >= TERMINAL.length) { el.innerHTML = html + '<span class="p">$</span> ' + caret; return; }
    const [kind, text] = TERMINAL[lineIdx++];
    if (kind !== "cmd") {
      html += `<span class="${kind}">${esc(text)}</span>\n`;
      el.innerHTML = html + caret;
      setTimeout(next, reduceMotion ? 0 : 260);
      return;
    }
    let i = 0;
    const prefix = '<span class="p">$</span> ';
    const tick = () => {
      el.innerHTML = html + prefix + esc(text.slice(0, i)) + caret;
      if (i++ < text.length) setTimeout(tick, reduceMotion ? 0 : 28 + Math.random() * 40);
      else { html += prefix + esc(text) + "\n"; setTimeout(next, reduceMotion ? 0 : 420); }
    };
    tick();
  };
  next();
}

/* =========================================================
   Прелоадер → интро hero
   ========================================================= */
const intro = () => {
  const tl = gsap.timeline({ defaults: { ease: "expo.out" } });
  tl.to("#preloader", { yPercent: -100, duration: 1.1, ease: "expo.inOut" })
    .to(uniforms.uIntro, { value: 1, duration: 2.8, ease: "power3.out" }, "-=0.8")
    .from(".hero__title .char", { yPercent: 120, rotate: 10, duration: 1.3, stagger: 0.028 }, "-=2.6")
    .from(".reveal-up", { y: 40, opacity: 0, duration: 1.2, stagger: 0.12 }, "-=1.6")
    .from(".nav > *", { y: -30, opacity: 0, duration: 1, stagger: 0.08 }, "-=1.2")
    .from(".hero__float", { scale: 0.6, opacity: 0, duration: 1.2, stagger: 0.15, ease: "back.out(1.6)" }, "-=1.1")
    .from(".hero__scroll", { opacity: 0, y: 20, duration: 1 }, "-=0.8")
    .add(() => {
      document.body.classList.remove("is-loading");
      document.getElementById("preloader").style.display = "none";
      lenis?.start();
    });
};

const preload = () => {
  document.body.classList.add("is-loading");
  const state = { v: 0 };
  const count = document.getElementById("preCount");
  const bar = document.getElementById("preBar");
  const fonts = document.fonts ? document.fonts.ready : Promise.resolve();
  const counter = gsap.to(state, {
    v: 100, duration: reduceMotion ? 0.1 : 1.4, ease: "power2.inOut",
    onUpdate: () => { count.textContent = Math.round(state.v); bar.style.width = `${state.v}%`; },
  });
  Promise.all([fonts, counter.then()]).then(() => {
    buildScroll();
    ScrollTrigger.refresh();
    intro();
  });
};

scrollTo(0, 0);
preload();

// ---------- видеоинструкция: своя кнопка запуска, дальше штатные элементы управления ----------
{
  const video = document.getElementById("tutorial");
  const play = document.getElementById("tutorialPlay");
  const section = video?.closest(".tutorial");
  if (video && play && section) {
    play.addEventListener("click", () => {
      video.controls = true;
      video.play().catch(() => {});
    });
    video.addEventListener("play", () => section.classList.add("is-playing"));
  }
}
