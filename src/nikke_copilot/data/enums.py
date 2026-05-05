from enum import Enum


class Element(str, Enum):
    FIRE = "Fire"
    WATER = "Water"
    ELECTRIC = "Electric"
    IRON = "Iron"
    WIND = "Wind"


class WeaponClass(str, Enum):
    SMG = "SMG"
    AR = "AR"
    SR = "SR"
    RL = "RL"
    SG = "SG"
    MG = "MG"


class BurstType(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    FLEX = "I/II/III"


class Rarity(str, Enum):
    R = "R"
    SR = "SR"
    SSR = "SSR"


class Manufacturer(str, Enum):
    ELYSION = "Elysion"
    MISSILIS = "Missilis"
    TETRA = "Tetra"
    PILGRIM = "Pilgrim"
    ABNORMAL = "Abnormal"


class OLBonusType(str, Enum):
    ELEMENT_DAMAGE = "Element Damage Dealt"
    ATK = "ATK"
    AMMUNITION_CAPACITY = "Ammunition Capacity"
    MAX_AMMUNITION_CAPACITY = "Max Ammunition Capacity"
    CHARGE_SPEED = "Charge Speed"
    CHARGE_DAMAGE = "Charge Damage"
    HIT_RATE = "Hit Rate"
    CRITICAL_RATE = "Critical Rate"
    CRITICAL_DAMAGE = "Critical Damage"
    DEFENSE = "Defense"
    HP = "HP"


class OLGearSlot(str, Enum):
    HEAD = "head"
    BODY = "body"
    ARMS = "arms"
    LEGS = "legs"
