# SAWT call interface

The Arabic call page is served by FastAPI from `static/v2/index.html`. React mounts the supplied OGL orb and Lucide icons as small islands; the existing LiveKit connection and transactional order workflow remain in `static/v2/app.js` and `playback.js`.

## Build

From the repository root, with Node 22.14+:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
node --experimental-default-type=module --test tests/playback.test.mjs tests/audio-meter.test.mjs
```

Open the running V2 server at `http://127.0.0.1:8766/`. The build writes `static/v2/ui/orb.js` and `orb.css`. Keep those generated assets in the repository so the Python-only deployment can serve them. No separate frontend server is required. `npm run dev --prefix frontend` watches and rebuilds; refresh only after an active call ends.

## Components and styles

- `components/ui/voice-powered-orb.tsx`: the reusable orb and its lifecycle.
- `components/ui/orb-shaders.ts`: the supplied visual's vertex/fragment shaders.
- `components/ui/button.tsx`: shadcn-compatible Button.
- `demo.tsx`: component usage example with an externally supplied audio level.
- `src/orb.tsx`: mounts the orb and subscribes to the call's audio meter.
- `styles/globals.css`: Tailwind v4 and shadcn color tokens.
- `../static/v2/call.css`: minimal call screen, RTL layout, mobile controls, and order dialog.
- `components.json`: shadcn paths. Run any shadcn CLI additions inside `frontend`; UI components belong in `components/ui`, and `@/` resolves to this directory.

The page uses locally hosted IBM Plex Sans Arabic fonts, matching the family used on the Sawt site; their OFL license is in `static/v2/fonts/Plex-OFL.txt`. It is a single call surface on a flat dark background: orb, status, call controls and a compact order link. The text at the orb's center is the call target. The small header uses the official Sawt logo with normal Arabic challenge lettering. The original official SVG is preserved separately; the generated header source and correction prompt are documented in `static/v2/sawt-challenge-wordmark.source.txt`. There are no landing-page sections or navigation. Orders are demo orders and do not go to a real restaurant.

`static/v2/order-view.js` renders a compact receipt: quantities and choices, destination, delivery fee and server-calculated total. Status sits beside the title; missing choices and order issues remain visible. It skips unchanged snapshots so polling does not rebuild an open order sheet. Order edits and confirmation still go through the existing voice workflow.

## Audio and accessibility

The orb **never requests a microphone**. It reads the existing LiveKit participant levels through the `sawt:audio-level` event. Exact readback is measured from an optional `captureStream()` copy of the native audio element. That analysis graph has no speaker output and never changes the native audio route. Browsers without capture support keep audio playback and ambient animation.

Updates are capped at 20 Hz for the bridge and approximately 30 fps for the shader. A small noise gate and asymmetric smoothing calm the speech meter. Idle color drift is slow; measured audio drives modest ripple, rotation and expansion instead of a continuous artificial pulse. Device pixel ratio is capped at 1.5. WebGL resources are released on unmount, hidden tabs pause animation, reduced-motion users get a still visual, and unavailable WebGL gets a CSS ring. Status text remains visible independently of animation. Controls retain keyboard focus styles, accessible labels and the native order dialog.

The localhost-only `/lab` route accepts synthetic fixtures for browser end-to-end checks without using the microphone. Keep browser testing in a separate tab from a user's ongoing call.
