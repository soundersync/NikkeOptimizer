"""Helm — B3 Water SR DPS-with-sustain, Elysion. Hybrid carry/defender.

Encoded from the live ``Character`` skill descriptions in the DB.

Helm sits in the awkward middle of the role spectrum: she has a single
massive burst nuke (anti-tank), but her S1+S2 buff allied attackers and
her burst grants the team a 10-second lifesteal-like recovery. Most
PvP usage treats her as a wall-and-counter unit (high HP/DEF + her
burst kills the highest-ATK enemy outright) hence her presence in
defensive comps.

**Source description (S1)**:

    Activates when the last bullet hits the target. Affects all allies.
    Critical Rate of normal attack ▲ 14.64% for 5 seconds.

**Source description (S2)**:

    Affects all allies.
    Damage to interruption part ▲ 3.08% permanently.

    Activates when entering Full Burst. Affects all allies.
    ATK damage ▲ 11.85% for 10 sec.

**Source description (Burst)**:

    Affects the enemy with the highest ATK.
    Deals 1237.5% of final ATK as damage.

    Affects all allies. Restores 54.45% of attack damage as HP for 10 sec.

**DSL gaps**:

  * "Damage to interruption part" is a PvE-only stat (boss interrupt
    parts) — encoded as a note on a placeholder buff.
  * "Restores 54.45% of attack damage as HP" is a lifesteal proxy —
    encoded as ``HEAL_PER_SECOND`` with a note (true value depends on
    runtime damage output).
  * "ATK damage" vs "ATK" is a real distinction in NIKKE: ATK damage
    multiplies output, ATK multiplies the source stat. Encoded as
    BUFF_ATK with a note; the simulator must distinguish.
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
    character_name="Helm",
    skill1=(
        SkillEffect(
            description=(
                "On the last bullet of the magazine hitting: all allies "
                "Crit Rate +14.64% for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=14.64,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Permanent passive: all allies gain 'Damage to interruption "
                "part +3.08%' (PvE boss-only stat)."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'Damage to interruption part +3.08%'; "
                        "PvE boss stat, irrelevant in PvP. DSL gap."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On entering Full Burst: all allies ATK damage +11.85% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.85,
                    duration_seconds=10.0,
                    notes="actually 'ATK damage +11.85%' — distinct from BUFF_ATK",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: deals 1237.5% of final ATK to the highest-ATK enemy. "
                "All allies gain a 10-second lifesteal-like recovery: 54.45% "
                "of attack damage restored as HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=12.375,
                    notes=(
                        "1237.5% of final ATK; targets highest-ATK enemy "
                        "(DSL has ENEMY_HIGHEST_HP not ENEMY_HIGHEST_ATK — "
                        "minor gap; both target 'biggest threat' in PvP)"
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.445,  # 54.45% / 10s as a proxy
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Restores 54.45% of attack damage as HP' — "
                        "lifesteal scaling on damage dealt; HEAL_PER_SECOND "
                        "is a coarse proxy"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Helm's defensive value isn't from shielding — it's from the "
        "team-wide lifesteal during her burst window combined with her "
        "single-target nuke removing the strongest opposing attacker. "
        "Pairs especially well with attackers in PvP (she keeps them "
        "alive while clearing the threat)."
    ),
)
register_character(_SKILL)
