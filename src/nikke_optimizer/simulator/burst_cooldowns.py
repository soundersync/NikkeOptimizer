"""Per-character burst-skill cooldowns in seconds.

Most NIKKE bursts are 20s, 40s, or 60s. The cooldown determines how
often a Nikke can fire her burst — material for sub-30s matches and
extremely material for matches that go past 20s where the second-chain
selection diverges based on which Nikkes are off cooldown.

Sources:
- nikke.gg burst gauge generation
- bittopup.com/article/NIKKE-F2P-Burst-Guide-Master-112Flex-Teams-and-Rotations
- in-game burst skill descriptions
"""

# Per-character burst cooldown overrides. Default is 20s for chars
# not listed (most B1/B2 sit at 20s). Standard B3 = 40s — listed
# explicitly only for chars known to deviate from that default.
BURST_COOLDOWN_SEC: dict[str, float] = {
    # ============ Burst 1 ============
    # 20s (standard B1 — listed for documentation; actually default)
    "Liter": 20.0,
    "N102": 20.0,
    "Volume": 20.0,
    "Pepper": 20.0,
    "Dorothy": 20.0,
    "Jackal": 20.0,
    "Tia": 20.0,
    "Rapunzel: Pure Grace": 20.0,
    "Anis: Star": 20.0,
    "Mary: Bay Goddess": 20.0,
    "Soldier OW": 20.0,

    # 40s B1
    "Emma": 40.0,
    "Noise": 40.0,
    "Sakura": 40.0,
    "Rosanna": 40.0,

    # 60s B1
    "Rapunzel": 60.0,

    # ============ Burst 2 ============
    # 20s B2
    "Centi": 20.0,
    "Centi (Treasure)": 20.0,
    "Anis": 20.0,
    "Rupee": 20.0,
    "Dolla": 20.0,
    "Guilty": 20.0,
    "Viper": 20.0,
    "Mast": 20.0,
    "Anchor": 20.0,
    "Anchor: Innocent Maid": 20.0,

    # 40s B2
    "Noah": 40.0,
    "Poli": 40.0,
    "Aria": 40.0,

    # 60s B2
    "Blanc": 60.0,
    "Anne: Miracle Fairy": 60.0,

    # ============ Burst 3 ============
    # All standard B3 = 40s — not listed here since the loader
    # defaults missing entries to 20s. We override to 40s by reading
    # burst_position from Character.burst_type and applying 40s when
    # position == "3" if no override exists.
    # Specific B3s with non-standard cooldowns would be listed here.
    "Modernia": 40.0,
    "Snow White: Heavy Arms": 40.0,
    "Crown": 40.0,
    "Red Hood": 40.0,
    "Scarlet": 40.0,
    "Scarlet: Black Shadow": 40.0,
    "Cinderella": 40.0,
    "Maiden: Ice Rose": 40.0,
    "Asuka Shikinami Langley": 40.0,
    "Snow White": 40.0,
    "Privaty": 40.0,
    "Privaty: Unkind Maid": 40.0,
    "Drake": 40.0,
    "Helm": 40.0,
}


def get_burst_cooldown(name: str, burst_position: str) -> float:
    """Return the burst cooldown in seconds for a Nikke.

    Falls back to:
      - 40s for B3 chars (all standard B3s)
      - 20s for B1/B2/flex (most common)
    """
    if name in BURST_COOLDOWN_SEC:
        return BURST_COOLDOWN_SEC[name]
    if burst_position == "3":
        return 40.0
    return 20.0
