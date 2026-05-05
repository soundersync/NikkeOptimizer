"""Tests for the Phase 3 skill DSL data model + registry."""

from __future__ import annotations

import pytest

from nikke_optimizer.simulator.dsl import (
    CharacterSkillSet,
    DSLValidationError,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
    assert_well_formed,
)
from nikke_optimizer.simulator.registry import (
    all_encoded_names,
    coverage_against,
    get,
)


def _minimal_skillset(name: str = "Test"):
    return CharacterSkillSet(
        character_name=name,
        skill1=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ALWAYS),
                effects=(
                    Effect(
                        kind=EffectKind.BUFF_ATK,
                        target=Target(kind=TargetKind.SELF),
                        magnitude=10.0,
                        duration_seconds=999.0,
                    ),
                ),
            ),
        ),
        skill2=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
                effects=(
                    Effect(
                        kind=EffectKind.GAIN_BURST_GAUGE,
                        target=Target(kind=TargetKind.ALL_ALLIES),
                        magnitude=20.0,
                    ),
                ),
            ),
        ),
        burst_skill=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
                effects=(
                    Effect(
                        kind=EffectKind.DEAL_DAMAGE,
                        target=Target(kind=TargetKind.ALL_ENEMIES),
                        magnitude=5.0,
                    ),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Validator unit tests — pure DSL primitives, no registry dependency
# ---------------------------------------------------------------------------


def test_assert_well_formed_accepts_valid_skillset():
    assert_well_formed(_minimal_skillset())


def test_well_formed_rejects_empty_name():
    bad = CharacterSkillSet(
        character_name="",
        skill1=_minimal_skillset().skill1,
        skill2=_minimal_skillset().skill2,
        burst_skill=_minimal_skillset().burst_skill,
    )
    with pytest.raises(DSLValidationError):
        assert_well_formed(bad)


def test_well_formed_rejects_buff_without_duration():
    bad = CharacterSkillSet(
        character_name="Test",
        skill1=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ALWAYS),
                effects=(
                    Effect(
                        kind=EffectKind.BUFF_ATK,
                        target=Target(kind=TargetKind.SELF),
                        magnitude=10.0,
                        # duration_seconds defaults to 0 — invalid for a buff
                    ),
                ),
            ),
        ),
        skill2=_minimal_skillset().skill2,
        burst_skill=_minimal_skillset().burst_skill,
    )
    with pytest.raises(DSLValidationError, match="duration_seconds"):
        assert_well_formed(bad)


def test_well_formed_rejects_negative_buff_magnitude():
    bad = CharacterSkillSet(
        character_name="Test",
        skill1=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ALWAYS),
                effects=(
                    Effect(
                        kind=EffectKind.BUFF_ATK,
                        target=Target(kind=TargetKind.SELF),
                        magnitude=-5.0,
                        duration_seconds=10.0,
                    ),
                ),
            ),
        ),
        skill2=_minimal_skillset().skill2,
        burst_skill=_minimal_skillset().burst_skill,
    )
    with pytest.raises(DSLValidationError, match="negative"):
        assert_well_formed(bad)


def test_well_formed_rejects_skill_with_no_effects():
    bad = CharacterSkillSet(
        character_name="Test",
        skill1=(
            SkillEffect(
                trigger=Trigger(kind=TriggerKind.ALWAYS),
                effects=(),  # no effects — invalid
            ),
        ),
        skill2=_minimal_skillset().skill2,
        burst_skill=_minimal_skillset().burst_skill,
    )
    with pytest.raises(DSLValidationError, match="no effects"):
        assert_well_formed(bad)


# ---------------------------------------------------------------------------
# Registry — every encoded character must validate + be retrievable
# ---------------------------------------------------------------------------


# Encoded library: the canonical Crown attack-comp + the canonical
# defense trio. All translated from real ``Character.skill_*_description``
# text in the DB. See ``library/__init__.py`` for the encoding rule.
# Widening past this set is a future slice — see BACKLOG.md.
_EXPECTED_ENCODED = {
    # Attack — Crown carry comp
    "Liter",
    "Crown",
    "Modernia",
    "Red Hood",
    "Snow White: Heavy Arms",
    # Defense — Helm/Centi/Blanc trio
    "Helm",
    "Centi",
    "Blanc",
    # Priority batch — burst-gen, alt B1s, top B3, anti-shield
    "Tia",
    "Naga",
    "Dorothy",
    "Anis: Star",
    "Scarlet: Black Shadow",
    "D: Killer Wife",
    # Defense quartet finisher
    "Noah",
    # Defensive supporters + alt B3 attacker
    "Bay",
    "Anchor",
    "Asuka Shikinami Langley",
    # Alt B3 attackers + alt B1 supports
    "Alice",
    "Cinderella",
    "Rapi: Red Hood",
    "Volume",
    "Rapunzel: Pure Grace",
    # Tier-2 niche utility
    "Mast: Romantic Maid",
    "Anis: Sparkling Summer",
    "Sakura",
    "Diesel",
    "Privaty",
    # Champion-tier B3 / collab carries + alt B2/B1 supports
    "Maxwell",
    "2B",
    "A2",
    "Drake",
    "Anis",
    "Soda",
    # Champion-tier specialists + Treasure forms
    "Phantom",
    "Bay (Treasure)",
    "Centi (Treasure)",
    "Marciana",
    "Folkwang",
    "Trony",
    # Niche utility / budget alts
    "Pepper",
    "Ade",
    "Soldier OW",
    "Quency",
    # Base story forms + true-damage carry + cumulative-tier supports
    "Snow White",
    "Rapi",
    "Ein",
    "Mary: Bay Goddess",
    "Anchor: Innocent Maid",
    "Helm: Aquamarine",
    # MP-scaling, single-target burst-amp, SG-comp, collab carries
    "Maiden: Ice Rose",
    "Jackal",
    "Leona",
    "Chisato Nishikigi",
    "Power",
    "Privaty: Unkind Maid",
    # Pilgrim AOE / Pierce SR / collab tanks / Highway-to-Hell
    "Scarlet",
    "Nihilister",
    "Makima",
    "Rem",
    "Emilia",
    "Mihara",
    # Parts-stack support / cumulative defender / Nano Coating / Memory Absorption
    "Rosanna: Chic Ocean",
    "Sin",
    "Kilo",
    "Quiry",
    "Yulha",
    "Nayuta",
    # Base healers + Eva/Chainsaw collab supports + Hero Level scaling
    "Rapunzel",
    "Eve",
    "Laplace",
    "Pascal",
    "Guillotine: Winter Slayer",
    "Mari Makinami Illustrious",
    # Eva/Lycoris/RE collab carries + supports
    "Rei Ayanami (Tentative Name)",
    "Misato Katsuragi",
    "Takina Inoue",
    "Claire Redfield",
    "Ada Wong",
    "Jill Valentine",
    # Tier-2 expansion batch
    "Brid: Silent Track",
    "Soda: Twinkling Bunny",
    "Mihara: Bonding Chain",
    "Elegg: Boom and Shock",
    "Sakura: Bloom in Summer",
    "Snow Crane",
    # PvP-relevant unencoded fill-in batch (#76)
    "Asuka Shikinami Langley: Wille",
    "Dolla",
    "Brid",
    "D",
    "Cocoa",
    "Drake (Treasure)",
    # Coverage push batch (#80)
    "Anne: Miracle Fairy",
    "Alice: Wonderland Bunny",
    "Dorothy: Serendipity",
    "Diesel: Winter Sweets",
    "Chime",
    "Aria",
    # 50% milestone batch (#84)
    "Crow",
    "Belorta",
    "Crust",
    "Frima",
    "Emma: Tactical Upgrade",
    "Admi",
    # Push-to-60 batch (#87)
    "Helm (Treasure)",
    "Bready",
    "Exia",
    "Poli",
    "Miranda",
    "Avistar",
}


def test_registry_loads_all_expected_characters():
    encoded = set(all_encoded_names())
    assert _EXPECTED_ENCODED.issubset(encoded), (
        f"missing encoded characters: {_EXPECTED_ENCODED - encoded}"
    )


def test_get_is_case_insensitive():
    assert get("crown") is not None
    assert get("CROWN") is not None
    assert get("Crown") is not None
    assert get("not-a-character") is None


def test_every_encoded_skillset_validates():
    """Every entry in the registry must satisfy DSL invariants. Catches
    typos in newly-added library files at test time."""
    for name in all_encoded_names():
        skills = get(name)
        assert skills is not None
        assert_well_formed(skills)


def test_coverage_separates_encoded_orphans_from_unencoded():
    db_names = ["Crown", "Liter", "SomeOtherChar"]
    cov = coverage_against(db_names)
    assert "Crown" in cov["encoded"]
    assert "Liter" in cov["encoded"]
    assert "SomeOtherChar" in cov["unencoded_in_db"]


# ---------------------------------------------------------------------------
# Encoded-content spot checks — verify the *real* skills (per the DB
# descriptions) are encoded, not the fictional ones from my training memory
# ---------------------------------------------------------------------------


def test_liter_burst_grants_team_atk_not_burst_gauge():
    """Liter's *real* burst (per Prydwen / DB scrape) is a team-wide
    ATK buff for 5 seconds. An older encoding mistakenly had this as a
    burst-gauge gain — this assertion guards against that regression."""
    skills = get("Liter")
    assert skills is not None
    found_atk_buff = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_ATK
                and eff.target.kind is TargetKind.ALL_ALLIES
                and eff.duration_seconds > 0
            ):
                found_atk_buff = True
            # Negative regression: must NOT include burst-gauge gain.
            assert eff.kind is not EffectKind.GAIN_BURST_GAUGE, (
                "Liter's burst gives ATK, not burst gauge — encoding regression"
            )
    assert found_atk_buff, "Liter's burst must grant team ATK"


def test_liter_skill2_is_cover_heal_not_atk_buff():
    """Liter S2 is a cover-heal effect, not an ATK buff. Older encoding
    had this wrong — assertion guards against re-introduction."""
    skills = get("Liter")
    assert skills is not None
    found_heal = False
    for se in skills.skill2:
        for eff in se.effects:
            if eff.kind is EffectKind.HEAL_HP_FLAT:
                found_heal = True
    assert found_heal, "Liter S2 should be a heal effect"


def test_crown_burst_grants_shield_and_atk_buff():
    """Crown's burst grants both an ATK buff and a shield (a mandatory
    fact for the simulator — Crown's value is mostly in the shield)."""
    skills = get("Crown")
    assert skills is not None
    found_shield = False
    found_atk = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if eff.kind is EffectKind.GRANT_SHIELD:
                found_shield = True
            # Source description says "Attack Damage ▲ 36.24%", encoded
            # as BUFF_ATTACK_DAMAGE post-DSL-slice (was BUFF_ATK proxy).
            if (
                eff.kind is EffectKind.BUFF_ATTACK_DAMAGE
                and eff.target.kind is TargetKind.ALL_ALLIES
            ):
                found_atk = True
    assert found_shield, "Crown's burst must include the shield effect"
    assert found_atk, "Crown's burst must include the team Attack Damage buff"


def test_modernia_s1_per_hit_damage():
    """Modernia's S1 deals 3.05% of ATK on every normal hit — encoding
    regression check (an earlier draft had this as 'every 200 hits')."""
    skills = get("Modernia")
    assert skills is not None
    found_per_hit = False
    for se in skills.skill1:
        if se.trigger.kind is TriggerKind.ON_HIT and se.trigger.every_n_hits == 1:
            for eff in se.effects:
                if eff.kind is EffectKind.DEAL_DAMAGE:
                    found_per_hit = True
                    # 3.05% encoded as 0.0305
                    assert abs(eff.magnitude - 0.0305) < 1e-6
    assert found_per_hit, "Modernia S1 must have per-hit damage at 3.05%"


def test_modernia_burst_extends_full_burst_window():
    """Modernia's burst extends Full Burst time by 5 sec — encoded as a
    note (DSL gap). Regression check ensures the note is present so the
    simulator knows to look for it."""
    skills = get("Modernia")
    assert skills is not None
    notes = []
    for se in skills.burst_skill:
        for eff in se.effects:
            if eff.notes:
                notes.append(eff.notes)
    assert any("Full Burst" in n for n in notes), (
        "Modernia's burst extends Full Burst time — must be documented in effect notes"
    )


def test_red_hood_burst_has_three_stages():
    """Red Hood's burst progresses through Beast Cage / Last Howl / Red
    Wolf — three SkillEffect entries with distinct stage conditions."""
    skills = get("Red Hood")
    assert skills is not None
    assert len(skills.burst_skill) == 3, (
        "Red Hood's burst has 3 sequential stages — Beast Cage, "
        "The Last Howl, Red Wolf"
    )
    stages_found = []
    for se in skills.burst_skill:
        cond = (se.trigger.condition or "").lower()
        for stage_keyword in ("beast cage", "last howl", "red wolf"):
            if stage_keyword in cond:
                stages_found.append(stage_keyword)
    assert set(stages_found) == {"beast cage", "last howl", "red wolf"}, (
        f"missing stages in Red Hood burst: {stages_found}"
    )


def test_red_hood_step_one_buffs_team_atk():
    """Red Hood's Beast Cage step buffs all-ally ATK by 77.55%."""
    skills = get("Red Hood")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        cond = (se.trigger.condition or "").lower()
        if "beast cage" not in cond:
            continue
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_ATK
                and eff.target.kind is TargetKind.ALL_ALLIES
                and abs(eff.magnitude - 77.55) < 0.1
            ):
                found = True
    assert found, "Red Hood Step 1 must grant team ATK +77.55%"


def test_snow_white_heavy_arms_burst_uses_self_atk_buff():
    """SW:HA's burst grants self ATK +84.48% for 10s — the headline
    damage multiplier she rides through Burst Stage 3."""
    skills = get("Snow White: Heavy Arms")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_ATK
                and eff.target.kind is TargetKind.SELF
                and abs(eff.magnitude - 84.48) < 0.1
                and eff.duration_seconds >= 10.0
            ):
                found = True
    assert found, "SW:HA's burst must self-ATK +84.48% for 10s"


def test_snow_white_heavy_arms_s1_lock_on_via_charging():
    """SW:HA's S1 lock-on triggers fire while charging — every-0.2-sec
    timer triggers, conditional on charge state."""
    skills = get("Snow White: Heavy Arms")
    assert skills is not None
    found_charging_trigger = False
    for se in skills.skill1:
        if (
            se.trigger.kind is TriggerKind.ON_TIMER
            and abs(se.trigger.cooldown_seconds - 0.2) < 1e-6
            and "charging" in (se.trigger.condition or "").lower()
        ):
            found_charging_trigger = True
    assert found_charging_trigger, (
        "SW:HA's S1 must have a 0.2-sec timer trigger gated on charging"
    )


# ---------------------------------------------------------------------------
# Defense trio (Helm / Centi / Blanc) spot checks
# ---------------------------------------------------------------------------


def test_helm_burst_targets_a_specific_enemy_with_huge_damage():
    """Helm's burst nukes a single high-priority enemy for ~1237.5% of ATK."""
    skills = get("Helm")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.DEAL_DAMAGE
                and eff.magnitude >= 12.0  # 1200%+
                and eff.target.kind in (
                    TargetKind.ENEMY_HIGHEST_HP,
                    TargetKind.ENEMY_LOWEST_HP,
                )
            ):
                found = True
    assert found, "Helm's burst must include the single-target nuke (~1237%)"


def test_helm_burst_grants_team_lifesteal():
    """Helm's burst gives all allies a 10-second damage-restores-as-HP
    buff. Encoded as HEAL_PER_SECOND with a note since the DSL doesn't
    have a true lifesteal kind."""
    skills = get("Helm")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.HEAL_PER_SECOND
                and eff.target.kind is TargetKind.ALL_ALLIES
                and eff.duration_seconds >= 10.0
            ):
                found = True
    assert found, "Helm's burst must heal-per-second the team for ≥10s"


def test_centi_s2_grants_team_shield():
    """Centi's S2 is the periodic team shield — 6.38% of her max HP for 5s."""
    skills = get("Centi")
    assert skills is not None
    found_shield = False
    for se in skills.skill2:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.GRANT_SHIELD
                and eff.target.kind is TargetKind.ALL_ALLIES
                and abs(eff.magnitude - 6.38) < 0.1
            ):
                found_shield = True
    assert found_shield, "Centi S2 must grant a 6.38% all-ally shield"


def test_centi_burst_debuffs_def():
    """Centi's burst applies a 14.54% DEF debuff to the 5 lowest-HP enemies."""
    skills = get("Centi")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.DEBUFF_DEFENSE
                and abs(eff.magnitude - 14.54) < 0.1
                and eff.duration_seconds >= 10.0
            ):
                found = True
    assert found, "Centi's burst must debuff DEF -14.54% for 10s"


def test_blanc_s1_grants_shield_after_120_attacks():
    """Blanc's S1 fires every 120 normal attacks, granting a 5-sec shield."""
    skills = get("Blanc")
    assert skills is not None
    found = False
    for se in skills.skill1:
        if se.trigger.kind is TriggerKind.ON_HIT and se.trigger.every_n_hits == 120:
            for eff in se.effects:
                if (
                    eff.kind is EffectKind.GRANT_SHIELD
                    and eff.target.kind is TargetKind.ALL_ALLIES
                ):
                    found = True
    assert found, "Blanc S1 must shield the team every 120 normal attacks"


def test_naga_burst_buffs_team_atk_twice_with_shield_condition():
    """Naga's burst grants ALL_ALLIES ATK +16.18%, plus an additional
    +31.02% conditional on shield application."""
    skills = get("Naga")
    assert skills is not None
    base_atk_buffs = []
    conditional_atk_buffs = []
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_ATK
                and eff.target.kind is TargetKind.ALL_ALLIES
            ):
                if "shield" in (eff.notes or "").lower():
                    conditional_atk_buffs.append(eff.magnitude)
                else:
                    base_atk_buffs.append(eff.magnitude)
    assert any(abs(m - 16.18) < 0.1 for m in base_atk_buffs), (
        "Naga burst must include base team ATK +16.18%"
    )
    assert any(abs(m - 31.02) < 0.1 for m in conditional_atk_buffs), (
        "Naga burst must include shield-conditional team ATK +31.02%"
    )


def test_sbs_s1_has_three_phase_thresholds():
    """SBS's S1 has three phases with escalating damage at the 3rd, 6th,
    and 9th full charge — encoded as three CONDITIONAL SkillEffects."""
    skills = get("Scarlet: Black Shadow")
    assert skills is not None
    phase_count = 0
    for se in skills.skill1:
        cond = (se.trigger.condition or "").lower()
        if "phase" in cond or "full-charge" in cond:
            phase_count += 1
    assert phase_count == 3, (
        f"SBS S1 should have 3 phase-conditional SkillEffects; got {phase_count}"
    )


def test_dorothy_burst_brand_payload_is_capped_at_8900_pct():
    """Dorothy's Brand caps at 8900.83% of caster ATK — encoded as
    a DEAL_DAMAGE with magnitude 89.0083."""
    skills = get("Dorothy")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.DEAL_DAMAGE
                and abs(eff.magnitude - 89.0083) < 0.01
            ):
                found = True
    assert found, "Dorothy burst must include the 8900.83% Brand cap payload"


def test_anis_star_has_state_conditional_branches():
    """Anis: Star has 'My Own Star' and 'Everyone's Star' state branches —
    multiple SkillEffects gated by state condition."""
    skills = get("Anis: Star")
    assert skills is not None
    states_seen = set()
    for slot in (skills.skill1, skills.skill2, skills.burst_skill):
        for se in slot:
            cond = (se.trigger.condition or "").lower()
            if "my own star" in cond:
                states_seen.add("solo")
            if "everyone's star" in cond:
                states_seen.add("paired")
    assert states_seen == {"solo", "paired"}, (
        f"Anis: Star must have both state branches; saw {states_seen}"
    )


def test_d_killer_wife_burst_inflicts_wipe_out_buffs():
    """D:KW's burst applies team-wide buffs gated on Wipe Out hits.
    Body-hit grants ATK (cross-stat); parts-hit grants core damage."""
    skills = get("D: Killer Wife")
    assert skills is not None
    wipe_out_buff_count = 0
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind in (EffectKind.BUFF_ATK, EffectKind.BUFF_CORE_DAMAGE)
                and "wipe out" in (eff.notes or "").lower()
            ):
                wipe_out_buff_count += 1
    assert wipe_out_buff_count >= 2, (
        "D:KW burst must include both Wipe-Out body-hit + parts-hit buffs"
    )


def test_noah_burst_grants_invincibility_and_def_buff():
    """Noah's burst gives all allies a 3-sec invincibility window plus
    a 10-sec DEF +133.48% buff. Both must be encoded."""
    skills = get("Noah")
    assert skills is not None
    found_invincibility = False
    found_def_buff = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_DEFENSE
                and eff.target.kind is TargetKind.ALL_ALLIES
                and "invincib" in (eff.notes or "").lower()
            ):
                found_invincibility = True
            if (
                eff.kind is EffectKind.BUFF_DEFENSE
                and eff.target.kind is TargetKind.ALL_ALLIES
                and abs(eff.magnitude - 133.48) < 0.1
            ):
                found_def_buff = True
    assert found_invincibility, (
        "Noah's burst must encode the 3-sec invincibility window "
        "(captured as BUFF_DEFENSE with 'invincib' in notes since "
        "the DSL has no INVINCIBILITY effect kind)"
    )
    assert found_def_buff, "Noah's burst must include DEF +133.48% for 10 sec"


def test_bay_burst_grants_self_hp_and_team_damage_reduction():
    """Bay's burst extends her own cover pool by 18% and reduces the
    team's damage taken by 8.87%."""
    skills = get("Bay")
    assert skills is not None
    found_self_hp = False
    found_team_dr = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_HP
                and eff.target.kind is TargetKind.SELF
                and abs(eff.magnitude - 18.0) < 0.1
            ):
                found_self_hp = True
            if (
                eff.kind is EffectKind.BUFF_DEFENSE
                and eff.target.kind is TargetKind.ALL_ALLIES
                and abs(eff.magnitude - 8.87) < 0.1
            ):
                found_team_dr = True
    assert found_self_hp, "Bay burst must include self Cover Max HP +18%"
    assert found_team_dr, "Bay burst must include team Damage Taken -8.87%"


def test_anchor_s1_taunts_target_on_last_bullet():
    """Anchor's S1 taunts the hit target and self-buffs DEF on last bullet."""
    skills = get("Anchor")
    assert skills is not None
    found_taunt = False
    found_def = False
    for se in skills.skill1:
        if se.trigger.kind is not TriggerKind.ON_LAST_AMMO:
            continue
        for eff in se.effects:
            if (
                eff.kind is EffectKind.TAUNT
                and eff.target.kind is TargetKind.PRIMARY_TARGET
            ):
                found_taunt = True
            if (
                eff.kind is EffectKind.BUFF_DEFENSE
                and eff.target.kind is TargetKind.SELF
                and abs(eff.magnitude - 23.82) < 0.1
            ):
                found_def = True
    assert found_taunt, "Anchor S1 must taunt the target hit by the last bullet"
    assert found_def, "Anchor S1 must self-buff DEF +23.82%"


def test_asuka_burst_gives_self_pierce_and_atk_buffs():
    """Asuka's burst grants 25-sec Pierce, 10-sec Attack Damage +150.04%
    (BUFF_ATTACK_DAMAGE per source), and Hit Rate +101.37% — all on self."""
    skills = get("Asuka Shikinami Langley")
    assert skills is not None
    found_pierce = False
    found_atk = False
    found_hit = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_PIERCE
                and eff.target.kind is TargetKind.SELF
                and eff.duration_seconds >= 20.0
            ):
                found_pierce = True
            if (
                eff.kind is EffectKind.BUFF_ATTACK_DAMAGE
                and eff.target.kind is TargetKind.SELF
                and abs(eff.magnitude - 150.04) < 0.1
            ):
                found_atk = True
            if eff.kind is EffectKind.BUFF_HIT_RATE:
                found_hit = True
    assert found_pierce, "Asuka burst must give 25-sec self Pierce"
    assert found_atk, "Asuka burst must give self Attack Damage +150.04% for 10 sec"
    assert found_hit, "Asuka burst must give self Hit Rate buff"


def test_alice_s2_has_hp_gated_pierce_and_lifesteal():
    """Alice's S2 has two HP-gated branches: high-HP → Pierce, low-HP → lifesteal."""
    skills = get("Alice")
    assert skills is not None
    high_hp_branch = False
    low_hp_branch = False
    for se in skills.skill2:
        cond = (se.trigger.condition or "").lower()
        if "> 80" in cond or "high-hp" in cond:
            for eff in se.effects:
                if eff.kind is EffectKind.BUFF_PIERCE:
                    high_hp_branch = True
        if "< 80" in cond or "low-hp" in cond:
            for eff in se.effects:
                if eff.kind is EffectKind.HEAL_PER_SECOND:
                    low_hp_branch = True
    assert high_hp_branch and low_hp_branch, (
        "Alice S2 must encode both HP-gated branches"
    )


def test_cinderella_burst_includes_10_sequential_hits():
    """Cinderella's burst fires 10 sequential 1365.92% hits — encoded
    as a single DEAL_DAMAGE with target.count=10."""
    skills = get("Cinderella")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.DEAL_DAMAGE
                and eff.target.count == 10
                and abs(eff.magnitude - 13.6592) < 0.01
            ):
                found = True
    assert found, "Cinderella burst must encode the 10× 1365.92% sequential hits"


def test_rapi_rh_has_combat_assist_state_branches():
    """Rapi: Red Hood's S1 has two state branches (Combat Assist + non)."""
    skills = get("Rapi: Red Hood")
    assert skills is not None
    states_seen = set()
    for slot in (skills.skill1, skills.skill2, skills.burst_skill):
        for se in slot:
            cond = (se.trigger.condition or "").lower()
            if "combat assist mode active" in cond:
                states_seen.add("combat_assist_on")
            if "combat assist mode not active" in cond:
                states_seen.add("combat_assist_off")
    assert states_seen == {"combat_assist_on", "combat_assist_off"}, (
        f"Rapi: RH must encode both Combat Assist branches; saw {states_seen}"
    )


def test_volume_burst_grants_team_crit_rate():
    """Volume's burst gives the team Crit Chance +31.59% for 5 sec."""
    skills = get("Volume")
    assert skills is not None
    found = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_CRIT_RATE
                and eff.target.kind is TargetKind.ALL_ALLIES
                and abs(eff.magnitude - 31.59) < 0.1
            ):
                found = True
    assert found, "Volume burst must give team Crit Chance +31.59%"


def test_rapunzel_pure_grace_has_two_self_shields():
    """Rapunzel: Pure Grace's S1 grants TWO self-shields — one on battle
    start and another on burst, both at 20.59% of max HP."""
    skills = get("Rapunzel: Pure Grace")
    assert skills is not None
    self_shield_count = 0
    for se in skills.skill1:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.GRANT_SHIELD
                and eff.target.kind is TargetKind.SELF
                and abs(eff.magnitude - 20.59) < 0.1
            ):
                self_shield_count += 1
    assert self_shield_count == 2, (
        f"Rapunzel: PG S1 must have 2 self-shields (battle-start + burst); "
        f"got {self_shield_count}"
    )


def test_asuka_s1_anti_shield_multiplier_uses_buff_shield_damage_kind():
    """Asuka's anti-shield multiplier is now BUFF_SHIELD_DAMAGE (was
    a BUFF_ATK proxy with a notes flag pre-DSL-slice). This regression
    test ensures the kind switch survives future re-encodings."""
    skills = get("Asuka Shikinami Langley")
    assert skills is not None
    found_note = False
    for se in skills.skill1:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.BUFF_SHIELD_DAMAGE
                and abs(eff.magnitude - 601.01) < 0.1
            ):
                found_note = True
    assert found_note, (
        "Asuka S1 must encode the 601.01% shield damage multiplier "
        "in its effect notes (DSL gap)"
    )


def test_noah_s2_targets_primary_with_taunt_and_debuff():
    """Noah's S2 single-target taunts and ATK-debuffs the Full-Charge
    target. Encoding regression check."""
    skills = get("Noah")
    assert skills is not None
    found_taunt = False
    found_debuff = False
    for se in skills.skill2:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.TAUNT
                and eff.target.kind is TargetKind.PRIMARY_TARGET
            ):
                found_taunt = True
            if (
                eff.kind is EffectKind.DEBUFF_ATK
                and eff.target.kind is TargetKind.PRIMARY_TARGET
                and abs(eff.magnitude - 13.25) < 0.1
            ):
                found_debuff = True
    assert found_taunt, "Noah S2 must single-target taunt the Full-Charge target"
    assert found_debuff, "Noah S2 must apply ATK -13.25% to the target"


def test_tia_burst_grants_dual_shield():
    """Tia's burst grants a self shield AND a different all-allies shield."""
    skills = get("Tia")
    assert skills is not None
    self_shields = []
    team_shields = []
    for se in skills.burst_skill:
        for eff in se.effects:
            if eff.kind is EffectKind.GRANT_SHIELD:
                if eff.target.kind is TargetKind.SELF:
                    self_shields.append(eff.magnitude)
                else:
                    team_shields.append(eff.magnitude)
    assert any(abs(m - 35.07) < 0.1 for m in self_shields), (
        "Tia burst must include self shield 35.07%"
    )
    assert any(abs(m - 10.21) < 0.1 for m in team_shields), (
        "Tia burst must include all-allies shield 10.21%"
    )


def test_blanc_burst_includes_team_regen_and_enemy_damage_debuff():
    """Blanc's burst combines team regen, an indomitability buff on the
    weakest ally, and a damage-taken debuff on enemies."""
    skills = get("Blanc")
    assert skills is not None
    found_regen = False
    found_enemy_debuff = False
    for se in skills.burst_skill:
        for eff in se.effects:
            if (
                eff.kind is EffectKind.HEAL_PER_SECOND
                and eff.target.kind is TargetKind.ALL_ALLIES
            ):
                found_regen = True
            if (
                eff.kind is EffectKind.DEBUFF_DEFENSE
                and eff.target.kind is TargetKind.ALL_ENEMIES
            ):
                found_enemy_debuff = True
    assert found_regen, "Blanc's burst must regen all allies"
    assert found_enemy_debuff, "Blanc's burst must apply a damage-taken debuff to enemies"
