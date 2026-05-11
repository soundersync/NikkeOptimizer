"""Delta: Ninja Thief — B2 Water MG Elysion Scouting. Defender / sustain.

Encoded from the live ``Character`` skill descriptions in the DB. Delta:NT
is a hybrid Defender / distributed-damage applier — her S2 forks based
on whether another Defender is in the squad (taunt shield form vs.
single-target-immunity sustain form), and her burst applies Distributed
Damage + ATK buff to the team along with an AOE distributed nuke.

**Source description (S1)**:

    Activates when entering Full Burst. Affects all enemies. Niinjutsu
    Acid Bomb: Damage Taken ▲ 12% for 15 sec.

    Activates when using Burst Skill. Affects self. ATK ▲ 15.04% for 10 sec.

    Activates when using Burst Skill. Affects enemies within attack
    range nearest to the crosshair. Niinjutsu Hyper Acid Bomb: Damage
    Taken ▲ 8% for 10 sec.

**Source description (S2)**:

    Activates at the start of battle. Effects differ according to squad
    formation.

    Affects self if no other Defender allies in squad:
        Effect 1: Shield 12.25% of caster's max HP for 10 sec.
        Effect 2: Attract: Taunt all enemies continuously.

    Affects self if another Defender ally in squad:
        Effect 1: Niinjutsu Camouflage: single-target-attack immunity
            for 10 sec. Loses effect when damaged.
        Effect 2: Niinjutsu Injection: Recover 0.22% of attack damage
            as HP continuously.

    Every 200 normal attacks while in Attract: Shield 12.25% max HP 10s.
    Every 4 sec while in Niinjutsu Injection: Niinjutsu IFAK 4 sec —
        accumulates up to 165.28% caster ATK, heals all allies on expiry.

**Source description (Burst)**:

    Affects all allies. Distributed Damage ▲ 20% for 10 sec. ATK ▲ 15%
    of caster's ATK for 10 sec.

    Affects all enemies. Deals 170% of final ATK as distributed damage.

    Affects self while in Attract: Next shield's HP ▲ 20.53% for 10 sec.
    Affects self while in Niinjutsu Injection: Max IFAK accumulation
    ▲ 20.53% for 10 sec.
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
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Delta: Ninja Thief",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: all enemies Damage Taken +12% for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=12.0,
                    duration_seconds=15.0,
                    notes="Niinjutsu Acid Bomb — Damage Taken debuff proxy",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Burst use: self ATK +15.04% 10s; nearest enemies "
                "Damage Taken +8% 10s."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=15.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=8.0,
                    duration_seconds=10.0,
                    notes="Niinjutsu Hyper Acid Bomb — nearest-to-crosshair",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Battle start (no other Defender in squad): self shield "
                "12.25% max HP 10s + Taunt all enemies."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                condition="no other Defender ally in squad",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.25,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    duration_seconds=999.0,
                    notes="Attract — taunt all enemies continuously",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Battle start (another Defender in squad): self "
                "Camouflage (single-target immunity 10s, breaks on hit) "
                "+ Niinjutsu Injection (0.22% lifesteal continuous)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BATTLE_START,
                condition="another Defender ally in squad",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "Niinjutsu Camouflage — single-target-attack "
                        "immunity (breaks on damage). DSL gap."
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.22,
                    duration_seconds=999.0,
                    notes="Niinjutsu Injection: 0.22% of attack damage → HP",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 200 attacks while in Attract: self shield 12.25% "
                "max HP for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=200,
                condition="self in Attract status",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=12.25,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 4 sec while in Niinjutsu Injection: accumulate "
                "up to 165.28% caster ATK and heal all allies on expiry."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=4.0,
                condition="self in Niinjutsu Injection",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=165.28,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "Niinjutsu IFAK — accumulates 165.28% ATK as "
                        "delayed team heal. DSL approximates as direct "
                        "heal at expiry."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Distributed Damage +20% and ATK "
                "+15% of caster's ATK 10s; all enemies take 170% "
                "distributed damage; shield/IFAK self-buffs while in "
                "matching status."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.0,
                    duration_seconds=10.0,
                    notes=(
                        "Distributed Damage +20% — encoded as generic "
                        "Attack Damage proxy. DSL gap (DISTRIBUTED)."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.70,
                    notes="distributed damage (split across enemies)",
                ),
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.53,
                    duration_seconds=10.0,
                    notes=(
                        "while in Attract: next shield HP +20.53%; "
                        "while in Niinjutsu Injection: IFAK accumulation "
                        "cap +20.53%. DSL has no compound modifier — "
                        "encoded as a self shield buff."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Water MG B2 Scouting — squad-dependent tank/sustainer. Solo-"
        "Defender form: shield + taunt. Paired-Defender form: stealth + "
        "sustain via Niinjutsu IFAK accumulating ATK-scaled team heal. "
        "Burst delivers team distributed-damage buff + ATK + AOE nuke."
    ),
)
register_character(_SKILL)
