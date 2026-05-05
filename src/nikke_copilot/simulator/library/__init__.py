"""Hand-encoded character skill libraries.

Each module in this package defines exactly one
:class:`CharacterSkillSet` and registers it via
:func:`register_character`. Import order doesn't matter — the registry
auto-loads every module here at import time.

Naming convention: ``library/<lowercase_safe_name>.py`` — e.g.
``snow_white_heavy_arms.py`` for "Snow White: Heavy Arms".

**Encoding rule.** Every skill effect must be translated from the actual
``Character.skill1_description`` / ``skill2_description`` /
``burst_description`` fields in the DB (scraped from Prydwen). Don't
paraphrase from memory — open the DB, paste the prose into the
docstring as a "Source description" block, then translate it to DSL
records. An earlier batch of hand-encoded characters (Modernia,
Red Hood, Snow White: Heavy Arms) was deleted because the encoded
mechanics didn't match the real game data; they'll be re-encoded
once the translation pattern is established by Liter + Crown.

See ``BACKLOG.md`` → "Phase 3 prep" for the broader translation
methodology questions raised by this work.
"""
