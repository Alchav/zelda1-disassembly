#!/usr/bin/env python3
"""Shuffle Zelda 1 underworld room bundles by directional exit mask.

This script patches a Zelda 1 NES ROM (U PRG0 layout expected) by shuffling
underworld room bundles (attrs A-F) only within pools that share the same
computed directional exit mask (N/E/S/W).

Result: level map topology remains unchanged at each room ID (same exit mask at
that slot), while room content bundles are permuted.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

# ROM offsets from src/bins.xml in this repository.
LEVEL_BLOCKS = {
    "uw1_q1": (100_096, 768),
    "uw2_q1": (100_864, 768),
    "uw1_q2": (101_632, 768),
    "uw2_q2": (102_400, 768),
}

ROOMS_PER_BLOCK = 128
ATTR_PLANES = 6  # LevelBlockAttrsA..F

# Door directions in output mask ordering.
DIR_N = 0b1000
DIR_E = 0b0100
DIR_S = 0b0010
DIR_W = 0b0001

# Door type decoding from attr bytes A/B:
#   south = A low 3 bits
#   north = A high nibble low 3 bits
#   east  = B low 3 bits
#   west  = B high nibble low 3 bits
#
# By default we treat door types 1 and 7 as non-exit (solid/no doorway-like)
# and all others as exits. This is configurable.
DEFAULT_NON_EXIT_TYPES = {1, 7}
DEFAULT_NON_EXIT_TYPES_CSV = ",".join(str(v) for v in sorted(DEFAULT_NON_EXIT_TYPES))


@dataclass(frozen=True)
class RoomSlot:
    block_name: str
    block_offset: int
    room_id: int


@dataclass
class RoomBundle:
    slot: RoomSlot
    attrs: List[int]  # [A, B, C, D, E, F]
    exit_mask: int


def parse_non_exit_types(value: str) -> set[int]:
    out: set[int] = set()
    if not value:
        return out
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        n = int(token, 0)
        if n < 0 or n > 7:
            raise ValueError(f"door type out of range 0..7: {n}")
        out.add(n)
    return out


def decode_door_types(attr_a: int, attr_b: int) -> Dict[str, int]:
    south = attr_a & 0b111
    north = (attr_a >> 4) & 0b111
    east = attr_b & 0b111
    west = (attr_b >> 4) & 0b111
    return {"N": north, "E": east, "S": south, "W": west}


def compute_exit_mask(attr_a: int, attr_b: int, non_exit_types: set[int]) -> int:
    doors = decode_door_types(attr_a, attr_b)
    mask = 0
    if doors["N"] not in non_exit_types:
        mask |= DIR_N
    if doors["E"] not in non_exit_types:
        mask |= DIR_E
    if doors["S"] not in non_exit_types:
        mask |= DIR_S
    if doors["W"] not in non_exit_types:
        mask |= DIR_W
    return mask


def format_mask(mask: int) -> str:
    return "".join(
        d
        for bit, d in ((DIR_N, "N"), (DIR_E, "E"), (DIR_S, "S"), (DIR_W, "W"))
        if mask & bit
    ) or "NONE"


def read_room_bundle(rom: bytearray, block_offset: int, room_id: int) -> List[int]:
    bundle: List[int] = []
    for plane in range(ATTR_PLANES):
        bundle.append(rom[block_offset + plane * ROOMS_PER_BLOCK + room_id])
    return bundle


def write_room_bundle(rom: bytearray, block_offset: int, room_id: int, attrs: Sequence[int]) -> None:
    for plane, val in enumerate(attrs):
        rom[block_offset + plane * ROOMS_PER_BLOCK + room_id] = val


def collect_bundles(
    rom: bytearray,
    block_names: Sequence[str],
    non_exit_types: set[int],
) -> List[RoomBundle]:
    bundles: List[RoomBundle] = []
    for name in block_names:
        block_offset, block_len = LEVEL_BLOCKS[name]
        if block_len != 768:
            raise RuntimeError(f"unexpected level block size for {name}: {block_len}")
        for room_id in range(ROOMS_PER_BLOCK):
            attrs = read_room_bundle(rom, block_offset, room_id)
            exit_mask = compute_exit_mask(attrs[0], attrs[1], non_exit_types)
            bundles.append(
                RoomBundle(
                    slot=RoomSlot(name, block_offset, room_id),
                    attrs=attrs,
                    exit_mask=exit_mask,
                )
            )
    return bundles


def shuffle_by_exit_mask(bundles: List[RoomBundle], rng: random.Random) -> Dict[int, int]:
    pools: Dict[int, List[RoomBundle]] = {}
    for b in bundles:
        pools.setdefault(b.exit_mask, []).append(b)

    for pool in pools.values():
        if len(pool) <= 1:
            continue
        shuffled_attrs = [b.attrs[:] for b in pool]
        rng.shuffle(shuffled_attrs)
        for slot_bundle, new_attrs in zip(pool, shuffled_attrs):
            slot_bundle.attrs = new_attrs

    return {mask: len(pool) for mask, pool in pools.items()}


def select_blocks(quests: str) -> List[str]:
    if quests == "q1":
        return ["uw1_q1", "uw2_q1"]
    if quests == "q2":
        return ["uw1_q2", "uw2_q2"]
    if quests == "both":
        return ["uw1_q1", "uw2_q1", "uw1_q2", "uw2_q2"]
    raise ValueError(f"unexpected quests value: {quests}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_rom", type=Path, help="Path to source .nes ROM")
    parser.add_argument("output_rom", type=Path, help="Path to write shuffled .nes ROM")
    parser.add_argument(
        "--quests",
        choices=["q1", "q2", "both"],
        default="both",
        help="Which underworld quest block set(s) to shuffle (default: both)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed (omit for non-deterministic shuffle)",
    )
    parser.add_argument(
        "--non-exit-types",
        default=DEFAULT_NON_EXIT_TYPES_CSV,
        help=(
            "Comma-separated door type ids (0..7) to treat as non-exits when pooling "
            f"rooms (default: {DEFAULT_NON_EXIT_TYPES_CSV})"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    rom = bytearray(args.input_rom.read_bytes())
    if len(rom) < 102_400 + 768:
        raise RuntimeError("ROM file is too small for expected Zelda 1 PRG0 layout")

    non_exit_types = parse_non_exit_types(args.non_exit_types)
    blocks = select_blocks(args.quests)
    rng = random.Random(args.seed)

    bundles = collect_bundles(rom, blocks, non_exit_types)
    pool_sizes = shuffle_by_exit_mask(bundles, rng)

    # Write shuffled bundles back to original slots.
    for b in bundles:
        write_room_bundle(rom, b.slot.block_offset, b.slot.room_id, b.attrs)

    args.output_rom.write_bytes(rom)

    print(f"Input : {args.input_rom}")
    print(f"Output: {args.output_rom}")
    print(f"Quests shuffled: {args.quests} ({', '.join(blocks)})")
    print(f"Seed: {args.seed}")
    print(f"Non-exit door types: {sorted(non_exit_types)}")
    print("Pools:")
    for mask in sorted(pool_sizes):
        print(f"  {format_mask(mask):<4} -> {pool_sizes[mask]} room(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
