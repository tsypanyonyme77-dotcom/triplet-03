# 3D Viewer

A Vite + React 19 + three.js app (`src/viewer/`) that shows the Twin running now, streamed over `/twin` (Vite proxy in development, nginx in Docker), or a recording made by `src/twin/world/record.py`.
`/timeline` is the live timeline across the layers (`src/timeline/`).
Stack: three 0.187, @react-three/fiber 9, @react-three/drei 10, TypeScript 6 (kept at 6 to match the POC frontend; 7 is the new native compiler and was not tried).

## What It Shows

- Ground, asphalt, kerbs, lane markings, zebra crossings, stop lines, parking bay outlines (a white line along the lane edge and across each end, open to the kerb; older recordings without bay sizes show none), two blocks with box buildings, traffic lights with live lamp colours.
- Accidents: a pulsing ring and label at each open accident in the scene; the overlay lists them (see The Overlay). Nothing in the sim dispatches help on its own.
- Buildings (`scene/Buildings.tsx`, from `map.buildings`: the engine's own list, with ids): buildings behind the sidewalks, each in a look chosen from its id (`buildingStyle.ts`): brick or plaster, its window grid, a shop with an awning on its street face or plain ground-floor windows, a cornice, a parapet and plant on the roof. Facades are canvas textures drawn once per look and repeated over the walls (`facadeTextures.ts`), so no image files are needed. Click one to select it (a yellow outline); a live run then shows a card (`hud/SelectionCard.tsx`) with `Start a fire`, which calls the Twin's fire simulator. Click anywhere else to deselect. Recordings made before the engine listed its buildings get the viewer's old generated ring, which cannot be selected.
- Fires (`scene/FireEffects.tsx`, from `frame.fires`): on every burning building a red glow, flames on the roof and a rising column of smoke, all growing with the fire's strength, and a `FIRE` label. Not looked at in a browser yet (see Not Verified Yet).
- Stations (`scene/Station.tsx`, from `map.stations`): a hospital, a fire station and a police station behind the outer sidewalks, each a box building with a coloured band (and a red cross for the hospital), a floating label, and its vehicle's bay painted in the station colour.
- Cars and emergency vehicles (Kenney models: civilian cars are sedan, taxi, SUV, van, hatchback; `amb*` ids are drawn as the ambulance, `police*` as the police car, `fire*` as the fire truck, `modelCatalog.unitModel`) with spinning wheels, following curved paths through turns (from the engine). Emergency vehicles are in every frame, parked at their station until called.
  Each model is scaled to the largest size that fits inside the sim's vehicle body (`map.vehicle`, 4.5 x 2.0 m) and centred on it (`actors/carFit.ts`), so cars that look like they touch really overlap in the sim; at 2.0 m wide they are 3.4 to 4.4 m long.
- People are a mix of the two models (three in four Soldier, one in four Robot), each with their own outfit colour and a height from 0.9 to 1.08 times the model's, all chosen from their id (`actors/personLook.ts`), so a crowd does not look cloned. There is no setting for it.
- Pedestrians with idle, walk and run animations, chosen by speed with separate start and stop thresholds (`locomotion.nextGait`), so a speed near a threshold does not restart clips. Clips play at a rate that matches ground speed, from 0.2x (about 0.28 m/s for a walk) to 1.6x: a higher floor (it was 0.5x) made the legs outrun the ground for people shuffling through a crowd at 0.2 to 0.5 m/s, which looked like gliding (3.7% of the `busy` recording, now 0.2%; `actors/locomotion.test.ts`).
Gait changes crossfade over 0.25 s (`actors/gaitAnimator.ts`); when no clip is playing yet, or the mixer stopped every action (drei's `useAnimations` cleanup does, e.g. on a hot reload), the clip starts at full weight instead, so the model's T-pose never shows, even while paused. The model follows the recorded facing at any speed (the engine keeps it steady while standing), smoothed over about 0.12 s, and an injured pedestrian falls over in 0.4 s, then freezes.
- Rain and floods: falling rain over each street it rains on, with as many drops as that street's rain (`frame.flood`, mm/h) calls for, all of them at 120 mm/h (`scene/Rain.tsx`; older recordings use `frame.rain` everywhere). Every street's drain is a grate by the kerb (`scene/Drain.tsx`): click it or the street round it and the drain card (`hud/DrainCard.tsx`) shows the water, rain, drain and pump, with `Block and flood` in a live run. Water in each of `map.flood_zones`, as deep as `frame.flood` says: a translucent surface over the flat street, thinning out along the engine's parabolic dip, which the raised sidewalk hides until the water is deeper than the kerb (`scene/FloodWater.tsx`, `scene/waterSurface.ts`). A blue label gives the depth and whether the pump is on. A car stalled in it, and a pedestrian trapped in it, get their own red label.
- Emergency calls: a green phone badge with the call id over every witness on the phone (`scene/CallMarkers.tsx`, from `frame.calls`); the pedestrian stands idle facing the accident.
- The overlay over the scene: see The Overlay below.
- `?rec=<scenario>` in the URL (e.g. `?rec=ped-hit`) plays `recording-<scenario>.json` instead of `recording.json`; make it with `python -m twin.world.record --scenario <scenario>`.

## The Overlay (`src/hud/`)

Everything drawn over the scene as HTML.
`Hud.tsx` puts the parts in place, `hud.css` styles them: rounded white cards, a colour per meaning (orange fire, blue police, rose ambulance, green good news, amber on its way), bouncy hovers, and pulsing alerts; motion is off under `prefers-reduced-motion`.
Icons are lucide-react.
It shows only what helps someone watching a demo, and leaves out ids, raw seconds and counters nobody acts on.

| Where | What |
|---|---|
| Top left | `StatusPill`: Live, Recording, Paused or Reconnecting, the scenario in words, and the simulated time as `mm:ss`. |
| Top right | `StatChips` (cars on the road, people, calls in progress), `IncidentFeed` (one card per accident, and one for all the burning buildings, saying whether nobody is coming, help is on the way, or help is working; click a card and the camera goes there), `UnitTray` (the ambulance, police car and fire truck: ready, on the way, working or heading home; click one to follow it). |
| Top centre | `RunBanner` (a Test Book scenario running, then a pass or fail with its log), a banner when the Twin is not answering or the engine stopped, and `ToastStack`: short notices when a fire starts, spreads or goes out, an accident happens or clears, and a unit leaves or arrives. |
| Left | `Toolbar` with four drawers: Scenarios (T1 to T3 as cards, and whether the mock Brain decides or you do), City sandbox (sliders for cars, people and the three risks), Camera (follow a car or person, or the free camera), Settings (whether the GPU or the CPU draws the scene, a link to the timeline page). A recording has only Camera and Settings. |
| Bottom | `Dock`: restart, play and pause, speed chips, and a time slider with "Back to live". In a live run these steer the Twin's own clock (speed 0.5x to 8x); the slider only looks back through what was streamed. Playing a recording they steer the playback clock. |
| Bottom left | `SelectionCard` for the clicked building. |

The data comes from the frames, so the overlay needs nothing the recording lacks: `derive.ts` turns a frame into counts, units and incidents (how help is going is worked out from which units are moving, not asked of the Twin), and `events.ts` turns the difference between two looks into toasts, unless the clock jumped (a seek is not news).
`useHud` looks four times a second.
`LiveContext` asks the Twin for the live status and the scenario list once a second and is shared by every part that needs them.
Both are tested (`hud/hud.test.ts`); how it looks has only been type-checked and built, not seen in a browser.

## Recording Format (`public/recording.json`)

```
{ dt: 0.1,
  map: { lane_width_m, roads: {nodes, edges}, parking: [{id, x, y, heading, length, width}], vehicle: {length, width},
         profile: {driving_outer_m, parking_lane_m, kerb_m, sidewalk_width_m},
         crosswalks: [{id, a: [x, y], b: [x, y], width, signalised}],
         stop_lines: [{approach: [u, v], x, y, heading, length}],
         stations: [{id, kind, unit_kind, label, bays: [{spot_id, x, y, heading}], front: [x, y], facing}],
         buildings: [{id, x, y, width, depth, height, street: [u, v], front: [x, y]}],
         flood_zones: [{id, x, y, heading, half_length_m, dip_depth_m, road_half_width_m, sidewalk_width_m, kerb_height_m}] },
  frames: [{ t,
             cars:        [[id, x, y, heading, speed, status, steer, accel], ...]
                          + emergency vehicles, every frame: [id, x, y, heading, speed, kind, steer, accel, call_status]
                            id amb1 / police1 / fire1, kind ambulance | police | fire,
                            call_status idle (parked at its station) | dispatched | cleaning | returning
             pedestrians: [[id, x, y, heading, speed, status], ...],
             lights:      {node_id: {from_node_id: "green"|"yellow"|"red"}},
             calls:       [[reporter_id, "pedestrian" | "driver", call_id], ...],   who is on the phone now
             rain:        mm/h
             flood:       [[zone_id, depth_m at the low point, pump_on, rain mm/h there, drain_blocked], ...]
             accidents:   [[id, x, y, car_id, other_id, kind], ...],   other_id: pedestrian, car, or null;
                                                                     kind: car_pedestrian | car_car | flooded_car | trapped_pedestrian
             fires:       [[building_id, strength 0..1, fire_id], ...] }] }   the buildings burning now
Pedestrian status can be `calling` (stands still, on the phone to the emergency number).
```

Types are in `src/recording/types.ts`; keep them in step with `record.py`.

## Coordinates (`src/scene/coords.ts`)

- Simulation: x east, y north, heading = `atan2(dy, dx)`.
- three.js: y up, ground on XZ. A sim point `(x, y)` maps to world `(x, 0, -y)` (a rotation, nothing mirrored).
- Yaw for a model facing +Z: `heading + π/2`; facing -Z: add π. Verified numerically.
- Vehicles: the sim position is the front bumper, so the car model is drawn 2.25 m behind it (`CarActor`).
- Vehicle tuples carry `steer` (front-wheel angle, + = left) and `accel` after the six common fields. `CarActor` draws front wheels steered by `steer`, the body pitching with `accel` and rolling with lateral acceleration (speed^2 tan(steer) / 2.7 m), and brake lights on when `accel < -0.4` or when stopped.

## Code Map (`src/`)

- `recording/`: types, loading hook, id collection.
- `scene/coords.ts` also has `angleDelta` and `dampAngle`, shared by playback and actors.
- `playback/`: `PlaybackClock` (mutable time read at 60 fps), `ClockDriver`, interpolation between 10 Hz frames (`sampleEntity`, with jump detection), `frameAt`.
- `scene/`: `CityScene` (canvas), `StaticCity` and its parts (`Ground`, `StreetSegment`, `Kerbs`, `Crosswalk`, `StopLine`, `ParkingBay` (with `bayMarkings`, tested), `CityBlock`, `Building`, `Station`, `TrafficLights`/`TrafficLight`), `Lighting`, `CameraRig`, `AccidentMarkers`, `cityLayout` (street list, blocks, profile).
- `actors/`: `Traffic` (one actor per id), `CarActor`, `PedestrianActor`, `locomotion` (gait and clip rate from speed), `gaitAnimator` (plays and crossfades the gait clips, tested in `gaitAnimator.test.ts`), `modelCatalog` (per-model scale, facing, clip names, clip speeds), `useClonedScene`, `actorRegistry` (for the follow camera).
- `api/twinApi.ts`: every request to the Twin, and the shapes of its answers.
- `timeline/`: `TimelinePage` and its parts, and `timelineView` (tested).
- `hud/`: the overlay (see The Overlay). `ui/ScenarioButtons.tsx` is left for the timeline page.

## Models (`public/models/`)

Facts per model (size, facing, clip names) were measured with `tools/inspect_glb.py`; sources and licenses are in `public/models/SOURCES.md`.
`clipSpeed` in `modelCatalog.ts` (the ground speed each walk/run clip shows at normal rate) is an estimate; tune it by eye so feet do not slide.

## Not Verified Yet

The viewer has only been type-checked, unit-tested and built.
Nobody has looked at it in a browser: check model scale and facing, kerb and crosswalk placement, light pole positions, animation speeds and the follow camera first, then the fire effects (flame and smoke shapes, glow, label), building selection and its panel.

## Camera views and the sequence timeline

- **Following** someone (Camera drawer, the People drawer, a unit chip) glides the camera in to 7 m from a person or 14 m from a vehicle over 0.8 s, keeping the compass direction it looked from; after that the orbit moves with them and the zoom is the user's (`scene/CameraRig.tsx`).
- **CCTV:** the Camera drawer lists every traffic camera once per street it looks down (`map.cameras`, `scene/cctv.ts`). Picking one puts the camera on a 7 m pole at the junction's corner, wide-angle and fixed, with a recording badge (`hud/CctvBadge.tsx`); Free camera, following someone or looking at an incident leaves it.
- **Timeline** (`/timeline`, `timeline/`): the three layers as a sequence diagram, oldest at the top: lifelines for the Twin, the Guardian and the City Brain, arrows for what passed between them (signed readings, verdicts, actuator calls and their answers, failed deliveries dashed red) and notes for what happened inside one (`timeline/sequence.ts` works out who said what to whom from each layer's own events). Switches show or hide routine events (periodic readings and notifications) and the engine's ground truth. It shows the live run, or any finished scenario run: the run banner links to `/timeline?run=N` while a scenario runs and once it ends, and a menu lists the last 20 runs.
