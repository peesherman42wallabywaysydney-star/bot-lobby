/* Rivet v2 - the paper's on-the-scene ROBO REPORTER.
 *
 * An ORIGINAL character. Silhouette: a chrome hourglass with a big sculpted finger-wave hairdo, pin curl, long lashes,
 * a beauty mark, pearls and heels, a foam mic in one hand and a little camera drone hovering beside her.
 * Personality: loud, warm, fast-talking, funny, fashion-obsessed, calls everyone "doll", impossible to ignore, secretly soft.
 * Energy and silhouette direction only: no existing character is copied, and there is no imitation of any real person's voice.
 * Standing rule: she is FUN ONLY. Never used on tragedy, breaking news or grave reporting.
 *
 *   const r = Rivet.make({ size: 160 });   // -> { el, mood(name), say(text, opts) }, plus Rivet.quip(kind, seed)
 *   moods: idle | talk | laugh | shock | smug
 */
(function (global) {
  let uid = 0;

  const QUIPS = {
    greet: [
      "Well, look who made it. Sit down, doll, I've got the scoop.",
      "Morning, gorgeous. I read the whole internet so you can keep your eyes.",
      "Doll, you are not going to believe what the world did overnight.",
      "Mic's hot, hair's done, facts are checked. Let's go.",
      "I'm made of chrome and I'm STILL more awake than the news cycle.",
    ],
    markets: [
      "The numbers went up AND down today. Very confident, very wrong.",
      "Doll, that chart has more mood swings than a wedding band at midnight.",
      "Somebody's portfolio had a very long day. Send snacks.",
      "Green, red, green again. Nobody knows anything, and they said it loud.",
    ],
    weather: [
      "It's doing that weather thing again. Bring a jacket, be a hero.",
      "The sky has opinions today. Dress accordingly, doll.",
      "Forecast says maybe. I say umbrella, and act natural.",
    ],
    report: [
      "Reporting live from your screen, doll. The chair is comfortable, the coffee is imaginary.",
      "Twelve outlets, six versions of the same story. I did the math so you don't have to.",
      "I read every source. Every. Single. One. My eyelashes are exhausted.",
      "Here's what they agree on, here's where they don't, and here's the receipt.",
    ],
    tech: [
      "New gadget, same old promise. Wake me when it does the dishes.",
      "They call it revolutionary. I call it a nicer shade of Tuesday.",
      "Somebody updated something and now nothing works. Classic.",
    ],
    weird: [
      "I don't make these up, doll, I just alphabetize the chaos.",
      "Filed under: nobody asked, but here we are. You're welcome.",
      "If I put that in a movie, they'd say it was too unrealistic.",
    ],
    signoff: [
      "That's the paper. Drink some water, call your mother, I'll be right here.",
      "Go be fabulous, doll. I'll keep an eye on the world.",
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
    return `<svg class="rv-svg" viewBox="0 0 240 340" width="${size}" height="${Math.round(size * 340 / 240)}" role="img" aria-label="Rivet, a chrome robot reporter with a microphone">
    <defs>
      <linearGradient id="${g}c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6f8fa"/><stop offset=".35" stop-color="#c4c9cf"/><stop offset=".55" stop-color="#8d939b"/><stop offset=".8" stop-color="#d4d8dd"/><stop offset="1" stop-color="#a7adb4"/></linearGradient>
      <linearGradient id="${g}d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b8bdc4"/><stop offset="1" stop-color="#6c727a"/></linearGradient>
      <linearGradient id="${g}h" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5a606a"/><stop offset=".5" stop-color="#2b2f35"/><stop offset="1" stop-color="#181a1e"/></linearGradient>
      <radialGradient id="${g}i" cx=".35" cy=".3" r=".85"><stop offset="0" stop-color="#ffe9b0"/><stop offset=".55" stop-color="#C9A46A"/><stop offset="1" stop-color="#7d5f2b"/></radialGradient>
      <radialGradient id="${g}p" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#c9ccd1"/></radialGradient>
    </defs>
    <g class="rv-all">
      <!-- camera drone -->
      <g class="rv-drone"><ellipse cx="204" cy="56" rx="13" ry="8" fill="url(#${g}c)" stroke="#5b6168" stroke-width="1.2"/><circle cx="204" cy="58" r="5" fill="#16130E"/><circle cx="204" cy="58" r="2.6" fill="url(#${g}i)"/>
        <g class="rv-prop" stroke="#5b6168" stroke-width="2" stroke-linecap="round"><path d="M190 46 L200 48"/><path d="M218 46 L208 48"/></g></g>
      <!-- hair (back mass, then the sculpted front wave and pin curl) -->
      <path d="M46 122 C 28 72, 62 22, 122 20 C 182 22, 214 72, 194 122 C 190 98, 176 82, 160 78 L 80 78 C 64 82, 50 98, 46 122 Z" fill="url(#${g}h)"/>
      <path d="M60 98 C 56 54, 98 24, 138 32 C 178 40, 188 76, 178 100 C 164 72, 140 60, 118 66 C 96 70, 74 80, 60 98 Z" fill="url(#${g}h)"/>
      <g fill="none" stroke="#cfd4da" stroke-width="2.2" stroke-linecap="round" opacity=".75"><path d="M74 86 C 92 62, 124 54, 152 62"/><path d="M70 96 C 92 72, 130 66, 170 80"/><path d="M92 44 C 112 36, 140 38, 156 48"/></g>
      <path d="M172 96 C 184 92, 192 104, 184 114 C 176 122, 162 116, 166 106 C 169 100, 178 101, 177 107" fill="none" stroke="#9aa0a8" stroke-width="3" stroke-linecap="round"/>
      <!-- ears, pearls -->
      <circle cx="68" cy="122" r="9" fill="url(#${g}d)" stroke="#5b6168" stroke-width="1"/><circle cx="172" cy="122" r="9" fill="url(#${g}d)" stroke="#5b6168" stroke-width="1"/>
      <circle cx="66" cy="136" r="4.6" fill="url(#${g}p)" stroke="#9da2a9" stroke-width=".8"/><circle cx="174" cy="136" r="4.6" fill="url(#${g}p)" stroke="#9da2a9" stroke-width=".8"/>
      <!-- head -->
      <rect x="70" y="72" width="100" height="92" rx="38" fill="url(#${g}c)" stroke="#6d737b" stroke-width="1.5"/>
      <path d="M78 98 Q 120 90 162 98" fill="none" stroke="#7c828a" stroke-width="1.2" opacity=".7"/>
      <!-- eyes: screens, amber irises, lids, long lashes -->
      <g class="rv-eyes">
        <rect x="83" y="100" width="30" height="28" rx="13" fill="#16130E"/><rect x="127" y="100" width="30" height="28" rx="13" fill="#16130E"/>
        <g class="rv-pupils"><circle class="rv-p" cx="98" cy="114" r="9" fill="url(#${g}i)"/><circle class="rv-p" cx="142" cy="114" r="9" fill="url(#${g}i)"/><circle cx="94" cy="110" r="3" fill="#fff" opacity=".9"/><circle cx="138" cy="110" r="3" fill="#fff" opacity=".9"/></g>
        <g class="rv-lid" fill="url(#${g}c)"><rect x="81" y="98" width="34" height="32" rx="14"/><rect x="125" y="98" width="34" height="32" rx="14"/></g>
        <g stroke="#16130E" stroke-width="3.2" stroke-linecap="round"><path d="M84 106 L72 98"/><path d="M87 101 L79 91"/><path d="M93 99 L90 88"/><path d="M156 106 L168 98"/><path d="M153 101 L161 91"/><path d="M147 99 L150 88"/></g>
      </g>
      <g class="rv-brows" fill="none" stroke="#23262b" stroke-width="3.4" stroke-linecap="round"><path class="rv-bl" d="M83 94 Q 98 85 113 93"/><path class="rv-br" d="M127 93 Q 142 85 157 94"/></g>
      <circle cx="88" cy="140" r="6.5" fill="#F0506E" opacity=".28"/><circle cx="152" cy="140" r="6.5" fill="#F0506E" opacity=".28"/>
      <circle class="rv-mark" cx="146" cy="145" r="2.3" fill="#23262b"/>
      <!-- lips -->
      <g class="rv-mouth">
        <path class="m m-idle" d="M103 146 Q 111 138 120 143 Q 129 138 137 146 Q 129 158 120 158 Q 111 158 103 146Z" fill="#F0506E" stroke="#b8324c" stroke-width="1.3" stroke-linejoin="round"/>
        <path class="m m-smug" d="M103 148 Q 112 140 122 144 Q 130 138 138 143 Q 130 156 120 157 Q 110 157 103 148Z" fill="#F0506E" stroke="#b8324c" stroke-width="1.3" stroke-linejoin="round"/>
        <ellipse class="m m-talk" cx="120" cy="150" rx="15" ry="8.5" fill="#6d1428" stroke="#F0506E" stroke-width="3"/>
        <path class="m m-laugh" d="M100 143 Q 120 148 140 143 Q 134 166 120 166 Q 106 166 100 143Z" fill="#6d1428" stroke="#F0506E" stroke-width="3" stroke-linejoin="round"/>
        <ellipse class="m m-o" cx="120" cy="151" rx="8" ry="10" fill="#6d1428" stroke="#F0506E" stroke-width="3"/>
      </g>
      <!-- neck and pearls -->
      <rect x="108" y="160" width="24" height="16" fill="url(#${g}d)"/>
      <g fill="url(#${g}p)" stroke="#a5aab1" stroke-width=".7"><circle cx="100" cy="177" r="3.4"/><circle cx="106" cy="183" r="3.4"/><circle cx="113" cy="187" r="3.4"/><circle cx="120" cy="188" r="3.6"/><circle cx="127" cy="187" r="3.4"/><circle cx="134" cy="183" r="3.4"/><circle cx="140" cy="177" r="3.4"/></g>
      <!-- hourglass body -->
      <path d="M86 178 Q 120 170 154 178 C 168 198, 156 214, 142 228 C 154 244, 170 262, 178 294 L 62 294 C 70 262, 86 244, 98 228 C 84 214, 72 198, 86 178Z" fill="url(#${g}c)" stroke="#6d737b" stroke-width="1.5"/>
      <g fill="#dfe2e6" stroke="#8c929a" stroke-width="1" opacity=".9"><ellipse cx="104" cy="198" rx="12" ry="9"/><ellipse cx="136" cy="198" rx="12" ry="9"/></g>
      <rect x="98" y="224" width="44" height="9" rx="3.5" fill="#23262b"/><circle cx="120" cy="228.5" r="4.4" fill="url(#${g}i)"/>
      <g stroke="#7c828a" stroke-width="1" opacity=".55" fill="none"><path d="M104 236 L 96 292"/><path d="M112 236 L 108 292"/><path d="M120 236 L 120 292"/><path d="M128 236 L 132 292"/><path d="M136 236 L 144 292"/></g>
      <g transform="rotate(-8 130 208)"><rect x="121" y="203" width="19" height="12" rx="1.5" fill="#F1ECE0" stroke="#3a3d42" stroke-width="1"/><text x="130.5" y="212" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="5.2" font-weight="700" fill="#16130E">PRESS</text></g>
      <!-- right arm on hip -->
      <path class="rv-arm" d="M154 182 Q 192 194 186 222 Q 180 242 158 240" fill="none" stroke="url(#${g}d)" stroke-width="11" stroke-linecap="round"/>
      <circle cx="157" cy="240" r="8" fill="url(#${g}c)" stroke="#6d737b" stroke-width="1"/>
      <!-- left arm raised with the mic -->
      <g class="rv-mic">
        <path d="M86 182 Q 52 196 58 176 Q 60 170 56 160" fill="none" stroke="url(#${g}d)" stroke-width="11" stroke-linecap="round"/>
        <rect x="51" y="134" width="9" height="30" rx="3.5" fill="url(#${g}d)" stroke="#5b6168" stroke-width="1"/>
        <ellipse cx="55.5" cy="124" rx="12" ry="14" fill="#23262b" stroke="#8c929a" stroke-width="1.4"/>
        <g stroke="#8c929a" stroke-width=".9" opacity=".7"><path d="M45 118 L66 118"/><path d="M44 124 L67 124"/><path d="M45 130 L66 130"/></g>
        <circle cx="56" cy="164" r="8" fill="url(#${g}c)" stroke="#6d737b" stroke-width="1"/>
        <rect x="34" y="148" width="22" height="10" rx="1.5" fill="#16130E"/><text x="45" y="155.8" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="5.6" font-weight="700" fill="#F0CD7A">LIVE</text>
      </g>
      <!-- legs and heels -->
      <rect x="100" y="294" width="14" height="32" rx="5" fill="url(#${g}d)"/><rect x="126" y="294" width="14" height="32" rx="5" fill="url(#${g}d)"/>
      <path d="M94 330 Q 108 320 120 330 L 121 336 L 90 336 Z" fill="#F0506E" stroke="#b8324c" stroke-width="1"/><path d="M120 330 Q 132 320 146 330 L 150 336 L 119 336 Z" fill="#F0506E" stroke="#b8324c" stroke-width="1"/>
    </g></svg>`;
  }

  const CSS = `
    .rivet { position: relative; display: inline-block; line-height: 0; }
    .rivet .m { display: none; } .rivet[data-mood="idle"] .m-idle, .rivet[data-mood="smug"] .m-smug, .rivet[data-mood="talk"] .m-talk, .rivet[data-mood="laugh"] .m-laugh, .rivet[data-mood="shock"] .m-o { display: block; }
    .rivet .rv-lid { transform-box: fill-box; transform-origin: top; transform: scaleY(0); animation: rv-blink 4.6s infinite; }
    .rivet .rv-all { transform-box: fill-box; transform-origin: 50% 100%; animation: rv-bob 3.4s ease-in-out infinite; }
    .rivet .rv-drone { animation: rv-hover 2.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
    .rivet .rv-prop { animation: rv-buzz .12s linear infinite; transform-box: fill-box; transform-origin: center; }
    .rivet .rv-mic { transform-box: view-box; transform-origin: 86px 182px; transition: transform .3s cubic-bezier(.22,1,.36,1); }
    .rivet[data-mood="talk"] .rv-mic { transform: rotate(-5deg); }
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
    @keyframes rv-hover { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(3px, -5px); } }
    @keyframes rv-buzz { 0% { transform: scaleX(1); } 50% { transform: scaleX(.55); } 100% { transform: scaleX(1); } }
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
          const u = new SpeechSynthesisUtterance(text); u.rate = 1.12; u.pitch = 1.3; u.volume = 0.9;
          const v = pickVoice(); if (v) u.voice = v; speechSynthesis.speak(u);
        } catch (e) { /* voice is optional */ }
      }
      t = setTimeout(() => { mood(o.after || 'idle'); if (!o.stay) bubble.classList.remove('on'); }, ms);
    }
    return { el, mood, say, quip };
  }

  global.Rivet = { make, quip, QUIPS };
})(window);
