/* Rivet - a small 2D steel robot with a coil beehive, lipstick and opinions.
 *
 * An ORIGINAL character (not any real person or show's likeness). Personality: brassy, gossipy, dramatic, big-city warm,
 * quick with a quip, laughs at her own jokes, secretly soft. The "sound" is in the writing (QUIPS below) plus an optional
 * browser text-to-speech voice tuned brighter and faster. No voice cloning, no lines from any show.
 *
 *   const r = Rivet.make({ size: 140 });   // -> { el, mood(name), say(text, {speak}) , quip(kind, seed) }
 *   container.appendChild(r.el); r.say(Rivet.quip('markets', 3), { speak: false });
 *   moods: idle | talk | laugh | shock | smug
 */
(function (global) {
  let uid = 0;

  const QUIPS = {
    greet: [
      "Well look who finally showed up. Sit, sit, I've got news.",
      "Morning, gorgeous. I read everything so you don't have to.",
      "Oh good, you're here. I've been holding this gossip since sunrise.",
      "Rise and shine, sweetheart. The world did things again.",
      "I'm made of steel and I'm STILL more awake than the news cycle.",
    ],
    markets: [
      "The numbers went up AND down today. Very confident, very wrong.",
      "Honey, the market has more mood swings than my cousin's wedding band.",
      "Somebody's portfolio had a very long day. Send snacks.",
      "Red numbers, green numbers, all of them shouting. Nobody's listening, sweetie.",
    ],
    weather: [
      "It's doing that weather thing again. Bring a jacket, be a hero.",
      "Sky's got opinions today. Dress for them.",
      "Forecast says maybe. I say bring an umbrella and act natural.",
    ],
    politics: [
      "That's a lot of suits in one room. Somebody check who's holding the snacks.",
      "Everybody's shaking hands and nobody's smiling with their eyes. I notice these things.",
      "Oh, they said WHAT? Read the receipts before you clutch your pearls, baby.",
      "Twelve outlets, six versions of the same story. I'll do the math, you sip your coffee.",
    ],
    tech: [
      "New gadget, same old promise. Wake me when it does the dishes.",
      "They call it revolutionary. I call it a nicer shade of Tuesday.",
      "Somebody updated something and now nothing works. Classic.",
    ],
    weird: [
      "I don't make these up, I just alphabetize the chaos.",
      "Filed under: nobody asked, but here we are. You're welcome.",
      "Sweetie, if I put that in a movie they'd say it was too unrealistic.",
    ],
    signoff: [
      "That's the paper. Drink some water, call your mother, I'll be right here.",
      "Go be fabulous. I'll keep an eye on the world.",
      "Facts in, fluff out. See you tomorrow, gorgeous.",
      "Close the tab, touch some grass, come back hungry for news.",
    ],
  };

  function quip(kind, seed) {
    const list = QUIPS[kind] || QUIPS.greet;
    const n = typeof seed === 'number' ? seed : String(seed || '').split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
    return list[Math.abs(n) % list.length];
  }

  function svg(id, size) {
    const g = 'rv' + id;
    return `<svg class="rv-svg" viewBox="0 0 220 260" width="${size}" height="${Math.round(size * 260 / 220)}" role="img" aria-label="Rivet, a small steel robot">
    <defs>
      <linearGradient id="${g}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e3e6e9"/><stop offset=".45" stop-color="#b3b8be"/><stop offset=".55" stop-color="#9599a0"/><stop offset="1" stop-color="#bcc0c6"/></linearGradient>
      <linearGradient id="${g}d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a3a8ae"/><stop offset="1" stop-color="#7a7f86"/></linearGradient>
      <radialGradient id="${g}p" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#ffe6a8"/><stop offset=".55" stop-color="#C9A46A"/><stop offset="1" stop-color="#8a6a33"/></radialGradient>
    </defs>
    <g class="rv-all">
      <!-- coil beehive -->
      <g class="rv-hair" fill="none" stroke="#8e9299" stroke-width="5" stroke-linecap="round">
        <ellipse cx="110" cy="52" rx="38" ry="9"/><ellipse cx="110" cy="40" rx="32" ry="8"/><ellipse cx="110" cy="29" rx="25" ry="7"/><ellipse cx="110" cy="19" rx="17" ry="6"/>
      </g>
      <circle class="rv-bulb" cx="110" cy="9" r="6" fill="url(#${g}p)"/>
      <!-- head -->
      <rect x="38" y="88" width="12" height="32" rx="5" fill="url(#${g}d)"/><rect x="170" y="88" width="12" height="32" rx="5" fill="url(#${g}d)"/>
      <rect x="50" y="58" width="120" height="94" rx="24" fill="url(#${g}s)" stroke="#6d7178" stroke-width="1.5"/>
      <g fill="#eef0f2" stroke="#6d7178" stroke-width="1"><circle cx="63" cy="71" r="3"/><circle cx="157" cy="71" r="3"/><circle cx="63" cy="139" r="3"/><circle cx="157" cy="139" r="3"/></g>
      <!-- eyes -->
      <g class="rv-eyes">
        <rect x="66" y="80" width="40" height="36" rx="13" fill="#16130E"/><rect x="114" y="80" width="40" height="36" rx="13" fill="#16130E"/>
        <g class="rv-pupils"><circle class="rv-p" cx="86" cy="98" r="10" fill="url(#${g}p)"/><circle class="rv-p" cx="134" cy="98" r="10" fill="url(#${g}p)"/>
          <circle cx="82" cy="94" r="3" fill="#fff" opacity=".85"/><circle cx="130" cy="94" r="3" fill="#fff" opacity=".85"/></g>
        <g class="rv-lid" fill="url(#${g}s)"><rect x="64" y="78" width="44" height="40" rx="14"/><rect x="112" y="78" width="44" height="40" rx="14"/></g>
        <g stroke="#16130E" stroke-width="3" stroke-linecap="round"><path d="M64 88 L58 82"/><path d="M68 80 L64 73"/><path d="M76 77 L74 70"/><path d="M156 88 L162 82"/><path d="M152 80 L156 73"/><path d="M144 77 L146 70"/></g>
      </g>
      <g class="rv-brows" fill="#16130E"><rect class="rv-bl" x="68" y="68" width="34" height="5" rx="2.5"/><rect class="rv-br" x="118" y="68" width="34" height="5" rx="2.5"/></g>
      <circle cx="76" cy="128" r="7" fill="#F5333A" opacity=".32"/><circle cx="144" cy="128" r="7" fill="#F5333A" opacity=".32"/>
      <!-- lips -->
      <g class="rv-mouth">
        <path class="m m-idle" d="M90 130 Q110 146 130 130 Q110 136 90 130Z" fill="#F5333A" stroke="#a4161c" stroke-width="1.5" stroke-linejoin="round"/>
        <path class="m m-smug" d="M90 133 Q108 141 132 128 Q112 138 90 133Z" fill="#F5333A" stroke="#a4161c" stroke-width="1.5" stroke-linejoin="round"/>
        <ellipse class="m m-talk" cx="110" cy="136" rx="14" ry="8" fill="#7a0d12" stroke="#F5333A" stroke-width="3"/>
        <path class="m m-laugh" d="M88 128 Q110 132 132 128 Q126 152 110 152 Q94 152 88 128Z" fill="#7a0d12" stroke="#F5333A" stroke-width="3" stroke-linejoin="round"/>
        <ellipse class="m m-o" cx="110" cy="136" rx="7" ry="9" fill="#7a0d12" stroke="#F5333A" stroke-width="3"/>
      </g>
      <!-- neck, body -->
      <rect x="98" y="152" width="24" height="10" fill="#7d8188"/>
      <rect x="64" y="160" width="92" height="72" rx="16" fill="url(#${g}s)" stroke="#6d7178" stroke-width="1.5"/>
      <g fill="#eef0f2" stroke="#6d7178" stroke-width="1"><circle cx="74" cy="170" r="3"/><circle cx="146" cy="170" r="3"/><circle cx="74" cy="222" r="3"/><circle cx="146" cy="222" r="3"/></g>
      <rect x="86" y="176" width="48" height="38" rx="9" fill="#16130E"/>
      <path class="rv-heart" d="M110 208 C 92 196, 96 184, 104 184 C 108 184, 110 187, 110 189 C 110 187, 112 184, 116 184 C 124 184, 128 196, 110 208Z" fill="#C9A46A"/>
      <!-- arms: hands on hips -->
      <path class="rv-arm" d="M64 178 Q34 190 46 214 Q52 220 66 214" fill="none" stroke="url(#${g}d)" stroke-width="11" stroke-linecap="round"/>
      <path class="rv-arm" d="M156 178 Q186 190 174 214 Q168 220 154 214" fill="none" stroke="url(#${g}d)" stroke-width="11" stroke-linecap="round"/>
      <circle cx="66" cy="214" r="8" fill="url(#${g}s)" stroke="#6d7178" stroke-width="1"/><circle cx="154" cy="214" r="8" fill="url(#${g}s)" stroke="#6d7178" stroke-width="1"/>
      <!-- legs -->
      <rect x="84" y="232" width="20" height="16" rx="4" fill="url(#${g}d)"/><rect x="116" y="232" width="20" height="16" rx="4" fill="url(#${g}d)"/>
      <ellipse cx="92" cy="252" rx="17" ry="6" fill="#6d7178"/><ellipse cx="128" cy="252" rx="17" ry="6" fill="#6d7178"/>
    </g></svg>`;
  }

  const CSS = `
    .rivet { position: relative; display: inline-block; line-height: 0; }
    .rivet .m { display: none; } .rivet[data-mood="idle"] .m-idle, .rivet[data-mood="smug"] .m-smug, .rivet[data-mood="talk"] .m-talk, .rivet[data-mood="laugh"] .m-laugh, .rivet[data-mood="shock"] .m-o { display: block; }
    .rivet .rv-lid { transform-box: fill-box; transform-origin: top; transform: scaleY(0); animation: rv-blink 4.6s infinite; }
    .rivet .rv-all { transform-box: fill-box; transform-origin: 50% 100%; animation: rv-bob 3.2s ease-in-out infinite; }
    .rivet .rv-bulb { animation: rv-glow 2.4s ease-in-out infinite; } .rivet .rv-heart { animation: rv-beat 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
    .rivet .rv-bl, .rivet .rv-br { transform-box: fill-box; transform-origin: center; transition: transform .25s; }
    .rivet[data-mood="talk"] .m-talk { animation: rv-talk .26s steps(2) infinite; transform-box: fill-box; transform-origin: center; }
    .rivet[data-mood="laugh"] .rv-all { animation: rv-laugh .32s ease-in-out infinite; }
    .rivet[data-mood="laugh"] .rv-bl, .rivet[data-mood="laugh"] .rv-br, .rivet[data-mood="shock"] .rv-bl, .rivet[data-mood="shock"] .rv-br { transform: translateY(-6px); }
    .rivet[data-mood="smug"] .rv-bl { transform: translateY(-5px) rotate(-8deg); } .rivet[data-mood="smug"] .rv-br { transform: rotate(4deg); }
    .rivet[data-mood="shock"] .rv-p { r: 6; }
    .rivet .rv-bubble { position: absolute; left: 100%; top: 4%; margin-left: 10px; width: max-content; max-width: min(260px, 52vw); padding: 9px 12px; border-radius: 4px 14px 14px 14px; background: #EDE6D6; color: #1d1a15;
      font: 500 13px/1.4 "Newsreader", Georgia, serif; text-align: left; box-shadow: 0 6px 16px rgba(0,0,0,.35); opacity: 0; transform: translateY(6px); transition: opacity .3s, transform .3s; pointer-events: none; }
    .rivet .rv-bubble.on { opacity: 1; transform: none; }
    @keyframes rv-blink { 0%, 92%, 100% { transform: scaleY(0); } 95% { transform: scaleY(1); } }
    @keyframes rv-bob { 0%, 100% { transform: translateY(0) rotate(-.6deg); } 50% { transform: translateY(-3px) rotate(.6deg); } }
    @keyframes rv-glow { 0%, 100% { opacity: .75; } 50% { opacity: 1; filter: drop-shadow(0 0 5px #C9A46A); } }
    @keyframes rv-beat { 0%, 100% { transform: scale(1); } 12% { transform: scale(1.14); } 24% { transform: scale(1); } }
    @keyframes rv-talk { 0% { transform: scaleY(1); } 100% { transform: scaleY(.45); } }
    @keyframes rv-laugh { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-4px) rotate(2deg); } }
    @media (prefers-reduced-motion: reduce) { .rivet *, .rivet { animation: none !important; } }
  `;

  function injectCss() {
    if (document.getElementById('rivet-css')) return;
    const st = document.createElement('style'); st.id = 'rivet-css'; st.textContent = CSS; document.head.appendChild(st);
  }

  function pickVoice() {
    const vs = (global.speechSynthesis && speechSynthesis.getVoices()) || [];
    const en = vs.filter((v) => /^en(-|_)US/i.test(v.lang));
    return en.find((v) => /zira|samantha|jenny|aria|female/i.test(v.name)) || en[0] || vs[0] || null;
  }

  function make(opts) {
    opts = opts || {}; injectCss();
    const size = opts.size || 140, id = ++uid;
    const el = document.createElement('div'); el.className = 'rivet'; el.dataset.mood = 'idle';
    el.innerHTML = svg(id, size) + '<div class="rv-bubble" aria-live="polite"></div>';
    const bubble = el.querySelector('.rv-bubble');
    let t = 0;
    function mood(name) { el.dataset.mood = name; }
    function say(text, o) {
      o = o || {}; clearTimeout(t);
      bubble.textContent = text; bubble.classList.add('on'); mood(o.mood || 'talk');
      const ms = Math.min(7000, 1200 + text.length * 45);
      if (o.speak && global.speechSynthesis) {
        try {
          speechSynthesis.cancel();
          const u = new SpeechSynthesisUtterance(text); u.rate = 1.12; u.pitch = 1.35; u.volume = 0.9;
          const v = pickVoice(); if (v) u.voice = v; speechSynthesis.speak(u);
        } catch (e) { /* voice is optional */ }
      }
      t = setTimeout(() => { mood(o.after || 'idle'); if (!o.stay) bubble.classList.remove('on'); }, ms);
    }
    return { el, mood, say, quip };
  }

  global.Rivet = { make, quip, QUIPS };
})(window);
