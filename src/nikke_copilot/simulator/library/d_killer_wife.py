"""D: Killer Wife — B1 Fire SR anti-shield specialist, Elysion.

Encoded from the live ``Character`` skill descriptions in the DB.
D:KW is the canonical anti-shield-meta unit — her burst applies
"Wipe Out" debuff and her S1+S2 ramp Pierce + team burst CD with
sustained Full Charge attacks.

**Source description (S1)**:

    Activates when attacking with Full Charge for 3 time(s). Affects
    self. Gain Pierce for 1 round.

    Activates when entering Full Burst. Affects all allies with a
    Sniper Rifle. Pierce Damage ▲ 13.55% for 10 sec.

**Source description (S2)**:

    Activates when attacking with Full Charge for 8 time(s). Affects
    all allies. Cooldown of Burst Skill ▼ 7 sec.

    Activates when attacking with Full Charge for 5 time(s). Affects
    all allies. Attack damage ▲ 5.06% for 10 sec.

**Source description (Burst)**:

    Affects the enemy nearest to the crosshair. Deals 269.28% of final
    ATK as additional damage. Inflicts Wipe Out on the target for 10 sec.

    Activates when allies' normal attack hits a certain area of the
    target afflicted with Wipe Out. Affects allies. Buff takes effect
    depending on the area hit:
        Allies that hit parts:
            Damage dealt when attacking core ▲ 16.26% for 10 sec.
        Allies that hit the body:
            ATK ▲ 12.19% of caster's ATK for 10 sec.

**DSL gaps**:

  * "Pierce Damage" is distinct from raw Pierce — encoded as a note.
  * "Wipe Out" debuff is a state flag with hit-zone-conditional team
    buffs — modeled as a CONDITIONAL trigger; simulator must track the
    debuff plus track which body part allies hit.
  * "1 round" duration on S1 — same gap as SW:HA: not seconds.
  * Allies-with-SR-only filter on S1 second clause — the DSL has no
    weapon-class target filter; encoded as ALL_ALLIES with a note.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
    WeaponClass,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="D: Killer Wife",
    skill1=(
        SkillEffect(
            description=(
                "Every 3 Full Charge attacks: self gains Pierce for 1 round."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="3rd full-charge attack landed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=1.0,
                    notes="duration is '1 round', not '1 second'",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry: all SR-equipped allies gain Pierce "
                "Damage +13.55% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_weapon=WeaponClass.SR,
                    ),
                    magnitude=13.55,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 Full Charges: all allies Attack damage +5.06% "
                "for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="5th full-charge attack landed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=5.06,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 8 Full Charges: all allies burst CD -7 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="8th full-charge attack landed",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: nukes crosshair-nearest enemy for 269.28% of ATK "
                "and inflicts Wipe Out for 10 sec. Allies hitting the "
                "Wipe-Out target get conditional buffs based on hit zone."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=2.6928,
                    notes=(
                        "actually 'enemy nearest to crosshair'; PvP "
                        "fallback is the front-most enemy"
                    ),
                ),
                # Hit-zone-conditional ally buffs — encoded as separate
                # SkillEffects below would split them out, but we keep
                # them here as the headline effect since the simulator
                # will need a Wipe-Out tracker anyway.
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=12.19,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "Wipe Out body-hit: allies who hit body get "
                        "+12.19% of caster's ATK. Encoded greedily — "
                        "simulator must track body vs parts hits."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_CORE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=16.26,
                    duration_seconds=10.0,
                    notes=(
                        "Wipe Out parts-hit: allies who hit parts get "
                        "+16.26% damage to core (PvE-leaning)"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "D:KW's value is anti-shield: Pierce ramping over Full Charges "
        "+ Wipe Out debuff that boosts team damage on the marked target. "
        "Slots into shield-heavy defense matchups (vs Helm/Centi/Blanc "
        "stalls)."
    ),
)
register_character(_SKILL)
