"""E.H. — B3 Wind SMG Elysion Exotic. Scrap-stacking self-buff carry.

Encoded from the live ``Character`` skill descriptions in the DB. E.H.'s
identity is a unique Scrap/homemade-magazine economy: she accumulates
Scraps from battle events (battle start, projectile/part destruction,
enemy kills), turns them into magazines for a stacking ATK buff, and
her burst swaps her weapon to a high-damage charge-shot form whose ammo
count scales with the magazines she crafted.

**Source description (S1)**:

    On obtaining 10 Scraps while < 4 homemade magazines: removes
    Scraps; crafts 1 homemade magazine (max 4, continuous).
    ATK ▲ 7.5% continuously × number of magazines.

**Source description (S2)**:

    Scrap economy buff:
      Battle start: Scraps +10 (cap 10).
      Ally/self destroys destructible projectile: Scraps +1 (cap 10).
      Ally/self destroys enemy part: Scraps +5 (cap 10).
      Enemy neutralized: Scraps +2 (cap 10).
      On obtaining Scraps: Elemental Advantage Attack Damage +16.36%
      for 15 sec.

**Source description (Burst)**:

    Self weapon swap (10 sec):
        Charge Time 0.4 sec, Damage 61% final ATK, Full Charge 250%
        of damage, Max Ammo = 1 × number of homemade magazines.
        Expires when duration ends or all rounds fired.
        Additional: ATK ▲ 430.05% for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="E.H.",
    skill1=(
        SkillEffect(
            description=(
                "Per 10 Scraps (while magazines < 4): craft 1 magazine "
                "(cap 4). Self ATK +7.5% × magazine count (continuous)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="obtain 10 Scraps and homemade magazines < 4",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=7.5,
                    duration_seconds=999.0,
                    stacks_max=4,
                    notes=(
                        "stacks once per crafted magazine (max 4). DSL "
                        "gap (Scrap/magazine economy)."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start: Scraps +10 (cap 10)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "Scraps +10 cap 10 — DSL gap (no Scrap resource); "
                        "0-mag placeholder."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Scrap acquisition: self Elemental Advantage Attack "
                "Damage +16.36% for 15 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="on Scrap gain (kills/parts/projectile destruction)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=16.36,
                    duration_seconds=15.0,
                    notes=(
                        "Elemental Advantage Attack Damage +16.36% — "
                        "applies only vs weak element."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: weapon swap 10s (charged shots 61% / full-charge "
                "250%, ammo = magazines crafted) + self ATK +430.05% 10s."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=430.05,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=150.0,
                    duration_seconds=10.0,
                    notes=(
                        "weapon swap: 250% full-charge damage on 61% "
                        "base shot. DSL gap (WEAPON_SWAP). 150% = "
                        "150% over baseline charge."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.61,
                    notes=(
                        "per-shot 61% ATK (250% on full charge). Ammo "
                        "count tied to crafted magazines (1-4 shots)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind SMG B3 Exotic — self-buff carry with Scrap/magazine "
        "economy. Sustained value is poor in PvP (Scraps trickle slowly), "
        "but burst-window damage is high with full +430% self-ATK. Best "
        "in part-destruction comps where Scrap gains are reliable."
    ),
)
register_character(_SKILL)
