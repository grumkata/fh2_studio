"""
fh2agg.sound — .82M sound-effect handling.

Sound entries in HEROES2.AGG are raw 8-bit unsigned mono PCM at 22 050 Hz
with NO header (just raw sample bytes).  fheroes2's LoadWAV() prepends a
standard 44-byte RIFF/WAV header at runtime (audio_manager.cpp lines
194-219).  We replicate that here so the GUI can play effects directly,
and provide import/export helpers for the replace workflow.
"""

from __future__ import annotations

import io
import struct
import wave

# Fixed format for every .82M entry (matches audio_manager.cpp LoadWAV)
_SAMPLE_RATE   = 22050
_CHANNELS      = 1
_SAMPLE_WIDTH  = 1   # bytes — 8-bit unsigned PCM


# ---------------------------------------------------------------------------
# .82M <-> WAV conversion
# ---------------------------------------------------------------------------

def m82_to_wav_bytes(raw_pcm: bytes) -> bytes:
    """Wrap raw .82M PCM bytes in a RIFF/WAV header and return the full
    WAV blob (suitable for writing to a file or feeding to pygame/wave)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframesraw(raw_pcm)
    return buf.getvalue()


def wav_bytes_to_m82(wav_bytes: bytes) -> bytes:
    """Read any WAV blob and convert it back to raw 8-bit unsigned mono
    PCM @ 22 050 Hz, as expected by .82M.

    Conversion steps performed by the stdlib wave module:
      - mono downmix is NOT done here (wav must already be mono or this will
        interleave channels and sound wrong — most UI sound files are mono)
      - resampling is NOT done here (supply a 22 050 Hz file for best results)
      - 16-bit->8-bit is NOT done here

    For anything more complex (stereo, wrong sample rate, 16-bit), the caller
    should pre-convert with ffmpeg / pydub before calling this function.
    """
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        if wf.getsampwidth() != _SAMPLE_WIDTH:
            raise ValueError(
                f"Expected 8-bit PCM (1 byte/sample), got {wf.getsampwidth()*8}-bit. "
                "Convert to 8-bit mono 22050 Hz first (e.g. with ffmpeg)."
            )
        return wf.readframes(wf.getnframes())


def audio_file_to_m82(path: str) -> bytes:
    """Load a .wav file from ``path`` and return raw .82M PCM bytes."""
    with open(path, "rb") as f:
        return wav_bytes_to_m82(f.read())


def export_m82_as_wav(raw_pcm: bytes, out_path: str) -> None:
    """Write an .82M PCM blob to ``out_path`` as a playable .wav file."""
    with open(out_path, "wb") as f:
        f.write(m82_to_wav_bytes(raw_pcm))


# ---------------------------------------------------------------------------
# Sound-effect catalogue (from m82.h / M82::GetString)
# All 83 names in enum order; the AGG entry name is "<NAME>.82M"
# ---------------------------------------------------------------------------

#  (internal_enum_name, friendly_description, category)
SOUND_CATALOGUE: list[tuple[str, str, str]] = [
    ("AELMATTK", "Air Elem. Attack",       "Creature"),
    ("AELMKILL", "Air Elem. Death",         "Creature"),
    ("AELMMOVE", "Air Elem. Move",          "Creature"),
    ("AELMWNCE", "Air Elem. Flinch",        "Creature"),
    ("ANTIMAGK",  "Antimagic",              "Spell"),
    ("ARCHATTK",  "Archer Attack",          "Creature"),
    ("ARCHKILL",  "Archer Death",           "Creature"),
    ("ARCHMOVE",  "Archer Move",            "Creature"),
    ("ARCHSHOT",  "Archer Shot",            "Creature"),
    ("ARCHWNCE",  "Archer Flinch",          "Creature"),
    ("ARMGEDN",   "Armageddon",             "Spell"),
    ("BADLUCK",   "Bad Luck",               "Spell"),
    ("BADMRLE",   "Bad Morale",             "Spell"),
    ("BERZERK",   "Berserk",                "Spell"),
    ("BLESS",     "Bless",                  "Spell"),
    ("BLIND",     "Blind",                  "Spell"),
    ("BLOODLUS",  "Bloodlust",              "Spell"),
    ("BOARATTK",  "Boar Attack",            "Creature"),
    ("BOARKILL",  "Boar Death",             "Creature"),
    ("BOARMOVE",  "Boar Move",              "Creature"),
    ("BOARWNCE",  "Boar Flinch",            "Creature"),
    ("BONEATTK",  "Bone Dragon Attack",     "Creature"),
    ("BONEKILL",  "Bone Dragon Death",      "Creature"),
    ("BONEMOVE",  "Bone Dragon Move",       "Creature"),
    ("BONEWNCE",  "Bone Dragon Flinch",     "Creature"),
    ("BUILDTWN",  "Build Town",             "UI"),
    ("CATSND00",  "Catapult Fire",          "Siege"),
    ("CATSND02",  "Catapult Hit",           "Siege"),
    ("CAVLATTK",  "Cavalry Attack",         "Creature"),
    ("CAVLKILL",  "Cavalry Death",          "Creature"),
    ("CAVLMOVE",  "Cavalry Move",           "Creature"),
    ("CAVLWNCE",  "Cavalry Flinch",         "Creature"),
    ("CHAINLTE",  "Chain Lightning",        "Spell"),
    ("CNTRATTK",  "Centaur Attack",         "Creature"),
    ("CNTRKILL",  "Centaur Death",          "Creature"),
    ("CNTRMOVE",  "Centaur Move",           "Creature"),
    ("CNTRSHOT",  "Centaur Shot",           "Creature"),
    ("CNTRWNCE",  "Centaur Flinch",         "Creature"),
    ("COLDRAY",   "Cold Ray",               "Spell"),
    ("COLDRING",  "Ice Ring",               "Spell"),
    ("CURE",      "Cure",                   "Spell"),
    ("CURSE",     "Curse",                  "Spell"),
    ("CYCLATTK",  "Cyclops Attack",         "Creature"),
    ("CYCLKILL",  "Cyclops Death",          "Creature"),
    ("CYCLMOVE",  "Cyclops Move",           "Creature"),
    ("CYCLWNCE",  "Cyclops Flinch",         "Creature"),
    ("DIGSOUND",  "Dig",                    "UI"),
    ("DIPMAGK",   "Dispel Magic",           "Spell"),
    ("DISRUPTR",  "Disrupting Ray",         "Spell"),
    ("DRAWBRG",   "Drawbridge",             "UI"),
    ("DRGNATTK",  "Dragon Attack",          "Creature"),
    ("DRGNKILL",  "Dragon Death",           "Creature"),
    ("DRGNMOVE",  "Dragon Move",            "Creature"),
    ("DRGNSLAY",  "Dragon Slayer",          "Spell"),
    ("DRGNWNCE",  "Dragon Flinch",          "Creature"),
    ("DRUIATTK",  "Druid Attack",           "Creature"),
    ("DRUIKILL",  "Druid Death",            "Creature"),
    ("DRUIMOVE",  "Druid Move",             "Creature"),
    ("DRUISHOT",  "Druid Shot",             "Creature"),
    ("DRUIWNCE",  "Druid Flinch",           "Creature"),
    ("DWRFATTK",  "Dwarf Attack",           "Creature"),
    ("DWRFKILL",  "Dwarf Death",            "Creature"),
    ("DWRFMOVE",  "Dwarf Move",             "Creature"),
    ("DWRFWNCE",  "Dwarf Flinch",           "Creature"),
    ("EELMATTK",  "Earth Elem. Attack",     "Creature"),
    ("EELMKILL",  "Earth Elem. Death",      "Creature"),
    ("EELMMOVE",  "Earth Elem. Move",       "Creature"),
    ("EELMWNCE",  "Earth Elem. Flinch",     "Creature"),
    ("ELF_ATTK",  "Elf Attack",             "Creature"),
    ("ELF_KILL",  "Elf Death",              "Creature"),
    ("ELF_MOVE",  "Elf Move",               "Creature"),
    ("ELF_SHOT",  "Elf Shot",               "Creature"),
    ("ELF_WNCE",  "Elf Flinch",             "Creature"),
    ("ERTHQUAK",  "Earthquake",             "Spell"),
    ("EXPERNCE",  "Experience",             "UI"),
    ("FELMATTK",  "Fire Elem. Attack",      "Creature"),
    ("FELMKILL",  "Fire Elem. Death",       "Creature"),
    ("FELMMOVE",  "Fire Elem. Move",        "Creature"),
    ("FELMWNCE",  "Fire Elem. Flinch",      "Creature"),
    ("FIREBALL",  "Fireball",               "Spell"),
    ("GARGATTK",  "Gargoyle Attack",        "Creature"),
    ("GARGKILL",  "Gargoyle Death",         "Creature"),
    ("GARGMOVE",  "Gargoyle Move",          "Creature"),
    ("GARGWNCE",  "Gargoyle Flinch",        "Creature"),
    ("GBLNATTK",  "Goblin Attack",          "Creature"),
    ("GBLNKILL",  "Goblin Death",           "Creature"),
    ("GBLNMOVE",  "Goblin Move",            "Creature"),
    ("GBLNWNCE",  "Goblin Flinch",          "Creature"),
    ("GENIATTK",  "Genie Attack",           "Creature"),
    ("GENIKILL",  "Genie Death",            "Creature"),
    ("GENIMOVE",  "Genie Move",             "Creature"),
    ("GENIWNCE",  "Genie Flinch",           "Creature"),
    ("GHSTATTK",  "Ghost Attack",           "Creature"),
    ("GHSTKILL",  "Ghost Death",            "Creature"),
    ("GHSTMOVE",  "Ghost Move",             "Creature"),
    ("GHSTWNCE",  "Ghost Flinch",           "Creature"),
    ("GOLMATTK",  "Golem Attack",           "Creature"),
    ("GOLMKILL",  "Golem Death",            "Creature"),
    ("GOLMMOVE",  "Golem Move",             "Creature"),
    ("GOLMWNCE",  "Golem Flinch",           "Creature"),
    ("GOODLUCK",  "Good Luck",              "Spell"),
    ("GOODMRLE",  "Good Morale",            "UI"),
    ("GRIFATTK",  "Griffin Attack",         "Creature"),
    ("GRIFKILL",  "Griffin Death",          "Creature"),
    ("GRIFMOVE",  "Griffin Move",           "Creature"),
    ("GRIFWNCE",  "Griffin Flinch",         "Creature"),
    ("H2MINE",    "Mine",                   "UI"),
    ("HALFATTK",  "Halfling Attack",        "Creature"),
    ("HALFKILL",  "Halfling Death",         "Creature"),
    ("HALFMOVE",  "Halfling Move",          "Creature"),
    ("HALFSHOT",  "Halfling Shot",          "Creature"),
    ("HALFWNCE",  "Halfling Flinch",        "Creature"),
    ("HASTE",     "Haste",                  "Spell"),
    ("HYDRATTK",  "Hydra Attack",           "Creature"),
    ("HYDRKILL",  "Hydra Death",            "Creature"),
    ("HYDRMOVE",  "Hydra Move",             "Creature"),
    ("HYDRWNCE",  "Hydra Flinch",           "Creature"),
    ("HYPNOTIZ",  "Hypnotize",              "Spell"),
    ("KEEPSHOT",  "Castle Tower Shot",      "Siege"),
    ("KILLFADE",  "Fade Kill",              "UI"),
    ("LICHATTK",  "Lich Attack",            "Creature"),
    ("LICHEXPL",  "Lich Explosion",         "Creature"),
    ("LICHKILL",  "Lich Death",             "Creature"),
    ("LICHMOVE",  "Lich Move",              "Creature"),
    ("LICHSHOT",  "Lich Shot",              "Creature"),
    ("LICHWNCE",  "Lich Flinch",            "Creature"),
    ("LIGHTBLT",  "Lightning Bolt",         "Spell"),
    ("LMAXATTK",  "Master Lich Attack",     "Creature"),
    ("LMAXKILL",  "Master Lich Death",      "Creature"),
    ("LMAXMOVE",  "Master Lich Move",       "Creature"),
    ("LMAXWNCE",  "Master Lich Flinch",     "Creature"),
    ("MAGIC02",   "Magic 02",               "Spell"),
    ("MEDUATTK",  "Medusa Attack",          "Creature"),
    ("MEDUKILL",  "Medusa Death",           "Creature"),
    ("MEDUMOVE",  "Medusa Move",            "Creature"),
    ("MEDUWNCE",  "Medusa Flinch",          "Creature"),
    ("MINÉATTK",  "Minotaur Attack",        "Creature"),
    ("MINEATTK",  "Minotaur Attack",        "Creature"),
    ("MINEKILL",  "Minotaur Death",         "Creature"),
    ("MINEMOVE",  "Minotaur Move",          "Creature"),
    ("MINEWNCE",  "Minotaur Flinch",        "Creature"),
    ("MIRRORM",   "Mirror Image",           "Spell"),
    ("MUMMATTK",  "Mummy Attack",           "Creature"),
    ("MUMMKILL",  "Mummy Death",            "Creature"),
    ("MUMMMOVE",  "Mummy Move",             "Creature"),
    ("MUMMWNCE",  "Mummy Flinch",           "Creature"),
    ("NCRPATTK",  "Necromancer Attack",     "Creature"),
    ("NCRPKILL",  "Necromancer Death",      "Creature"),
    ("NCRPMOVE",  "Necromancer Move",       "Creature"),
    ("NCRPWNCE",  "Necromancer Flinch",     "Creature"),
    ("NITEATTK",  "Black Knight Attack",    "Creature"),
    ("NITEKILL",  "Black Knight Death",     "Creature"),
    ("NITEMOVE",  "Black Knight Move",      "Creature"),
    ("NITEWNCE",  "Black Knight Flinch",    "Creature"),
    ("NOMATTK",   "Nomad Attack",           "Creature"),
    ("NOMKILL",   "Nomad Death",            "Creature"),
    ("NOMMOVE",   "Nomad Move",             "Creature"),
    ("NOMWNCE",   "Nomad Flinch",           "Creature"),
    ("OGRMATTK",  "Ogre Lord Attack",       "Creature"),
    ("OGRMKILL",  "Ogre Lord Death",        "Creature"),
    ("OGRMMOVE",  "Ogre Lord Move",         "Creature"),
    ("OGRMWNCE",  "Ogre Lord Flinch",       "Creature"),
    ("OGRATTK",   "Ogre Attack",            "Creature"),
    ("OGRKILL",   "Ogre Death",             "Creature"),
    ("OGRMOVE",   "Ogre Move",              "Creature"),
    ("OGRWNCE",   "Ogre Flinch",            "Creature"),
    ("PALADIN2",  "Paladin Attack 2",       "Creature"),
    ("PALADKIL",  "Paladin Death",          "Creature"),
    ("PALADMOV",  "Paladin Move",           "Creature"),
    ("PALADWN2",  "Paladin Flinch 2",       "Creature"),
    ("PALADN2",   "Paladin 2",              "Creature"),
    ("PALADNK2",  "Paladin Death 2",        "Creature"),
    ("PARALYZE",  "Paralyze",               "Spell"),
    ("PEASATTK",  "Peasant Attack",         "Creature"),
    ("PEASKILL",  "Peasant Death",          "Creature"),
    ("PEASMOVE",  "Peasant Move",           "Creature"),
    ("PEASWNCE",  "Peasant Flinch",         "Creature"),
    ("PHOEATTK",  "Phoenix Attack",         "Creature"),
    ("PHOEKILL",  "Phoenix Death",          "Creature"),
    ("PHOEMOVE",  "Phoenix Move",           "Creature"),
    ("PHOEWNCE",  "Phoenix Flinch",         "Creature"),
    ("PIKEMEN",   "Pikeman Move",           "Creature"),
    ("PIKEATTK",  "Pikeman Attack",         "Creature"),
    ("PIKEKILL",  "Pikeman Death",          "Creature"),
    ("PIKESHOT",  "Pikeman Shot",           "Creature"),
    ("PIKEWNCE",  "Pikeman Flinch",         "Creature"),
    ("RESURECT",  "Resurrection",           "Spell"),
    ("REZDEAD",   "Animate Dead",           "Spell"),
    ("ROCATTK",   "Roc Attack",             "Creature"),
    ("ROCKILL",   "Roc Death",              "Creature"),
    ("ROCMOVE",   "Roc Move",               "Creature"),
    ("ROCWNCE",   "Roc Flinch",             "Creature"),
    ("ROGUEKIL",  "Rogue Death",            "Creature"),
    ("ROGUEMOV",  "Rogue Move",             "Creature"),
    ("ROGUE",     "Rogue Attack",           "Creature"),
    ("ROGUEWNC",  "Rogue Flinch",           "Creature"),
    ("SCLTATTK",  "Scorpicor Attack",       "Creature"),
    ("SCLTKILL",  "Scorpicor Death",        "Creature"),
    ("SCLTMOVE",  "Scorpicor Move",         "Creature"),
    ("SCLTWNCE",  "Scorpicor Flinch",       "Creature"),
    ("SHIELD",    "Shield",                 "Spell"),
    ("SKELATTK",  "Skeleton Attack",        "Creature"),
    ("SKELKILL",  "Skeleton Death",         "Creature"),
    ("SKELMOVE",  "Skeleton Move",          "Creature"),
    ("SKELWNCE",  "Skeleton Flinch",        "Creature"),
    ("SLOW",      "Slow",                   "Spell"),
    ("SNAKATK2",  "Royal Snake Attack",     "Creature"),
    ("SNAKATK",   "Snake Attack",           "Creature"),
    ("SNAKKIL2",  "Royal Snake Death",      "Creature"),
    ("SNAKKILL",  "Snake Death",            "Creature"),
    ("SNAKWNCE",  "Snake Flinch",           "Creature"),
    ("SORCEROR",  "Sorcerer Move",          "Creature"),
    ("SORCATK",   "Sorcerer Attack",        "Creature"),
    ("SORCKIL",   "Sorcerer Death",         "Creature"),
    ("SORCWNCE",  "Sorcerer Flinch",        "Creature"),
    ("SPENERGY",  "Spend Energy",           "UI"),
    ("SPLSOUND",  "Splash",                 "UI"),
    ("STERNUM",   "Sternum Hit",            "UI"),
    ("STONEGOL",  "Stone Golem Move",       "Creature"),
    ("STRLKILL",  "Steel Golem Death",      "Creature"),
    ("STRLMOVE",  "Steel Golem Move",       "Creature"),
    ("STRLWNCE",  "Steel Golem Flinch",     "Creature"),
    ("SUMMELEM",  "Summon Elemental",       "Spell"),
    ("SWRDATTK",  "Swordsman Attack",       "Creature"),
    ("SWRDKILL",  "Swordsman Death",        "Creature"),
    ("SWRDMOVE",  "Swordsman Move",         "Creature"),
    ("SWRDWNCE",  "Swordsman Flinch",       "Creature"),
    ("TELEPORT",  "Teleport",               "Spell"),
    ("THUNDER",   "Thunder",                "Spell"),
    ("TITNATTK",  "Titan Attack",           "Creature"),
    ("TITNKILL",  "Titan Death",            "Creature"),
    ("TITNMOVE",  "Titan Move",             "Creature"),
    ("TITNWNCE",  "Titan Flinch",           "Creature"),
    ("TITNSHOT",  "Titan Shot",             "Creature"),
    ("TRLFATTK",  "Evil Troll Attack",      "Creature"),
    ("TRLFKILL",  "Evil Troll Death",       "Creature"),
    ("TRLFMOVE",  "Evil Troll Move",        "Creature"),
    ("TRLFWNCE",  "Evil Troll Flinch",      "Creature"),
    ("TROLLATTK", "Troll Attack",           "Creature"),
    ("TROLLKIL",  "Troll Death",            "Creature"),
    ("TROLLMOV",  "Troll Move",             "Creature"),
    ("TROLLWNC",  "Troll Flinch",           "Creature"),
    ("UNICORN",   "Unicorn Move",           "Creature"),
    ("UNRATK",    "Unicorn Attack",         "Creature"),
    ("UNRKILL",   "Unicorn Death",          "Creature"),
    ("UNRWNCE",   "Unicorn Flinch",         "Creature"),
    ("VAMPATTK",  "Vampire Attack",         "Creature"),
    ("VAMPKILL",  "Vampire Death",          "Creature"),
    ("VAMPMOVE",  "Vampire Move",           "Creature"),
    ("VAMPWNCE",  "Vampire Flinch",         "Creature"),
    ("WELMATTK",  "Water Elem. Attack",     "Creature"),
    ("WELMKILL",  "Water Elem. Death",      "Creature"),
    ("WELMMOVE",  "Water Elem. Move",       "Creature"),
    ("WELMWNCE",  "Water Elem. Flinch",     "Creature"),
    ("WOLFATTK",  "Wolf Attack",            "Creature"),
    ("WOLFKILL",  "Wolf Death",             "Creature"),
    ("WOLFMOVE",  "Wolf Move",              "Creature"),
    ("WOLFWNCE",  "Wolf Flinch",            "Creature"),
    ("WSND00",    "Sail Sound 1",           "UI"),
    ("WSND01",    "Sail Sound 2",           "UI"),
    ("WSND02",    "Sail Sound 3",           "UI"),
    ("WSND03",    "Sail Sound 4",           "UI"),
    ("WSND04",    "Sail Sound 5",           "UI"),
    ("WSND05",    "Sail Sound 6",           "UI"),
    ("WSND10",    "Ship Sound 1",           "UI"),
    ("WSND11",    "Ship Sound 2",           "UI"),
    ("WSND12",    "Ship Sound 3",           "UI"),
    ("WSND13",    "Ship Sound 4",           "UI"),
    ("WSND14",    "Ship Sound 5",           "UI"),
    ("WSND15",    "Ship Sound 6",           "UI"),
    ("WSND20",    "Sea Sound 1",            "UI"),
    ("WSND21",    "Sea Sound 2",            "UI"),
    ("WSND22",    "Sea Sound 3",            "UI"),
    ("WSND23",    "Sea Sound 4",            "UI"),
    ("WSND24",    "Sea Sound 5",            "UI"),
    ("WSND25",    "Sea Sound 6",            "UI"),
    ("ZOMBIEATTK","Zombie Attack",          "Creature"),
    ("ZOMBIEKIL", "Zombie Death",           "Creature"),
    ("ZOMBIEMOV", "Zombie Move",            "Creature"),
    ("ZOMBIEWNC", "Zombie Flinch",          "Creature"),
]

# Build a set of known entry names for fast "is this a sound?" lookups
SOUND_AGG_NAMES: set[str] = {f"{name}.82M" for name, _, _ in SOUND_CATALOGUE}
# Lookup: AGG entry name -> (friendly_name, category)
SOUND_INFO: dict[str, tuple[str, str]] = {
    f"{name}.82M": (friendly, cat)
    for name, friendly, cat in SOUND_CATALOGUE
}
