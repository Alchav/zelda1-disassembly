# External randomizer feasibility: entrance shuffle and dungeon door shuffle

This note summarizes how the current Zelda 1 disassembly stores room/level connectivity, what an **external** randomizer can patch safely, and the expected implementation difficulty.

## Quick take

- **(a) Entrance shuffle:** very feasible as a data-patching workflow (moderate overall difficulty).
- **(b) Door shuffle between arbitrary dungeon rooms:** feasible, but significantly harder if you want true graph shuffling; the vanilla engine computes adjacent rooms from room ID math, not per-door destination tables (high difficulty unless you also inject code).

---

## Relevant data and code surfaces

### 1) Level blocks and level info are copied to RAM on level load

On mode 2, the game copies a selected `LevelBlock*` source to RAM `$687E..$6B7D` and a selected `LevelInfo*` source to RAM `$6B7E..$6C7D`. This is foundational for any patch strategy because it defines where the active room metadata comes from. `LevelBlockAddrsQ1/Q2` and `LevelInfoAddrs` select quest/level sources. `FetchLevelBlockDestInfo` and `FetchLevelInfoDestInfo` define those RAM ranges. `LevelBlock*` and `LevelInfo*` data come from `.INCBIN` files. 【F:src/Z_06.asm†L15-L50】【F:src/Z_06.asm†L55-L95】【F:src/Z_06.asm†L110-L145】【F:src/Z_06.asm†L390-L432】

Also, `bins.xml` gives ROM offsets and lengths for all level block/info binaries (useful for direct ROM patchers that don’t assemble source):

- `LevelBlockOW.dat` and UW block files: each `768` bytes.
- `LevelInfoOW.dat` and each `LevelInfoUW*.dat`: each `252` bytes. 【F:src/bins.xml†L31-L45】

### 2) Room IDs are grid-based

Room coordinates are encoded in the room ID nibble layout (high nibble row, low nibble column), and HUD marker logic derives map position from those nibbles. This is one reason the engine naturally assumes geometric adjacency rather than arbitrary graph edges. 【F:src/Z_01.asm†L4140-L4164】

### 3) Door traversal target is computed arithmetically

For door movement, next room is computed as `RoomId + offset` with offsets `[$F0, $10, $FF, $01]` (N/S/W/E ordering as used by the internal mapping function), i.e. -16/+16/-1/+1 in room-ID space. There is no vanilla per-door destination pointer table for UW room-to-room travel. 【F:src/Z_05.asm†L7474-L7511】

### 4) Door types are stored in room attribute bytes A/B

`FindDoorTypeByDoorBit` decodes 3-bit door types from `LevelBlockAttrsA` (S/N) and `LevelBlockAttrsB` (E/W). So A/B already control whether each side behaves as wall, open, bombable/false wall, key door, shutter, etc. 【F:src/Z_05.asm†L4541-L4577】

### 5) Overworld entrance → destination mapping comes from OW room attributes

When entering OW warps (`HandleWarpOW`), the engine reads `LevelBlockAttrsB` for current OW room, masks to cave-index bits (`AND #$FC`), and:

- if `< $40`: treats it as a dungeon level index (`>>2`) and sets `CurLevel`;
- if `>= $40`: dispatches to cave/shortcut modes (`$0B/$0C`).

This is the primary hook for entrance randomization. 【F:src/Z_05.asm†L7332-L7395】

### 6) Dungeon load entry room is level-info driven

When initializing a UW level, `InitMode3_Sub1` uses `LevelInfo_StartRoomId` as the initial room (unless coming from `CaveSourceRoomId` in OW logic). So entry point randomization per dungeon is data-driven as well. 【F:src/Z_07.asm†L1442-L1454】

### 7) Cave/cellar special paths exist

- Caves set `UndergroundExitType` and use `CaveSourceRoomId` for return flow. 【F:src/Z_01.asm†L3019-L3023】【F:src/Z_07.asm†L1442-L1454】
- UW cellar transitions use `LevelInfo_CellarRoomIdArray` and treat cellar rooms specially, reading destination room IDs from level block attrs A/B in cellar context. This is separate from ordinary doorway transitions. 【F:src/Z_05.asm†L3072-L3095】

### 8) Per-room persistent flags are level-specific

Room flags (visited/item/kill/open-door state dependencies) are addressed through `LevelInfo_WorldFlagsAddr`. Shuffling should preserve consistency between room semantics and flag usage because this storage is indexed by room ID. 【F:src/Z_07.asm†L796-L803】

### 9) Second quest has runtime patches to level data

On mode-2 load for quest 2, code applies replacement bytes to OW/UW data (`LevelBlockAttrsBQ2Replacement*`, `LevelInfoUWQ2Replacements*`). If your randomizer supports both quests, account for these differences explicitly. 【F:src/Z_06.asm†L197-L262】【F:src/Z_06.asm†L265-L376】

---

## (a) Entrance shuffle prospects

## Recommended external-tool approach

1. Build an OW entrance table by parsing OW `LevelBlockAttrsB` cave-index bits.
2. Randomize mapping from OW entrance rooms to destinations (levels/caves/shortcuts), with constraints.
3. Patch OW block bytes (or direct ROM offsets from `bins.xml`).
4. Optionally patch each destination dungeon’s `LevelInfo_StartRoomId` to control where entry lands inside the target dungeon.
5. Validate round-trip behavior for exits (`UndergroundExitType`, `CaveSourceRoomId`) and start-room viability.

## Key constraints

- OW entrance tile logic expects specific tiles (`$24`, `$70-$73`, etc.) and only then triggers warp handling.
- Cave index encoding is bucketed (level indexes vs cave/shortcut ranges), so shuffled values must stay valid encoded values.
- If you shuffle dungeon identities, ensure associated level-specific assumptions (boss room, triforce room, item locations, palettes/song feel) still produce intended gameplay.

## Expected difficulty

- **Core entrance randomization:** **Medium**.
- **Entrance randomization with robust logic constraints and quest parity:** **Medium-High**.

Why not low: there are many game-logic constraints and special cave/cellar cases, even though the primary hook is data-driven.

---

## (b) Door shuffle (arbitrary dungeon room-to-room graph) prospects

## What is easy

- Randomizing **door types** (open/key/shutter/etc.) within A/B nibble encoding is straightforward data work.
- Applying consistency rules (e.g., reciprocal openability on both sides) is algorithmically straightforward.

## What is hard

Vanilla destination selection for doorway traversal is geometric (`RoomId +/- 1 or +/- 0x10`), not table-driven per edge. So arbitrary graph rewiring (“door in room X east leads to room Y south”) is **not** achievable by only editing room data bytes unless you constrain shuffle to permutations compatible with coordinate adjacency.

To get true door-graph shuffle, an external tool likely needs to inject an engine patch, e.g.:

- Replace/augment next-room calculation with a custom lookup table keyed by `(roomId, direction)`.
- Preserve special handling (dark-room transitions, doorway states, shutters, cellars, map marker behavior, room-history interactions).
- Potentially alter minimap/status-map assumptions if room IDs no longer represent physical adjacency.

## Practical implementation tiers

1. **Tier 1 (Low-Medium):** only shuffle door *types* (no destination rewiring).
2. **Tier 2 (Medium-High):** constrained destination shuffle that keeps grid-consistent adjacencies (effectively remapping room contents more than edges).
3. **Tier 3 (High-Very High):** true arbitrary edge shuffle via code injection + new data tables + compatibility fixes.

## Expected difficulty

- **True arbitrary door shuffle:** **High** (or **Very High** if full compatibility/polish expected).

---

## Suggested planning checklist for tool authors

- Parse/build support for:
  - Level block arrays (A-F attrs per room).
  - Level info arrays (`StartRoomId`, cellar list, world flags pointers).
  - Quest 1 vs quest 2 variant behavior, including runtime replacement data.
- Decide patch target format:
  - Source asset rewrite + rebuild, or
  - Direct ROM patching using offsets from `bins.xml`.
- Implement validators:
  - Entrance encoding validity.
  - Room reachability.
  - No softlock from required items/keys/doors.
  - Proper cellar/cave/return behavior.
- If doing true door graph shuffle, design and test a minimal injected lookup system before broad randomization logic.

---

## Bottom line

- **Entrance shuffle:** practical with current data structures; good candidate for an external randomizer without deep engine surgery.
- **Door shuffle between individual dungeon rooms:** doable only at high effort for true arbitrary connectivity, because vanilla transition logic is arithmetic and grid-assumptive rather than table-routed.
