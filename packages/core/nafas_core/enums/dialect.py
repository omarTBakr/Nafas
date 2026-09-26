from enum import StrEnum


class Dialect(StrEnum):
    """
    The dialect-router's labels, from the model's config.json.

    The model card lists 11 codes and calls Moroccan "mo"; the model itself
    emits these 12, including "en" for English text.
    """

    MSA = "ar"
    EGYPTIAN = "eg"
    ENGLISH = "en"
    IRAQI = "iq"
    LEBANESE = "lb"
    LIBYAN = "ly"
    MOROCCAN = "ma"
    PALESTINIAN = "ps"
    SAUDI = "sa"
    SUDANESE = "sd"
    SYRIAN = "sy"
    TUNISIAN = "tn"


class SpokenDialect(StrEnum):
    """
    The dialect a patient chooses to be spoken to in: the 13 that the
    Lahgtna OmniVoice voices and the Arabic-dialect Whisper both cover.

    Separate from Dialect above, which is what the dialect-router can
    *detect* in text (it has MSA and English, and lacks Bahraini, Algerian
    and Yemeni). A detection only ever suggests one of these.
    """

    EGYPTIAN = "eg"
    SAUDI = "sa"
    MOROCCAN = "ma"
    BAHRAINI = "bh"
    SUDANESE = "sd"
    IRAQI = "iq"
    LEBANESE = "lb"
    SYRIAN = "sy"
    LIBYAN = "ly"
    PALESTINIAN = "ps"
    TUNISIAN = "tn"
    ALGERIAN = "dz"
    YEMENI = "ye"

    @property
    def lahgtna_language(self) -> str:
        """The name OmniVoice takes as `language` for this dialect: "egyptian lahgtna"."""
        return f"{self.name.lower()} lahgtna"


# a detected dialect → the spoken one to suggest; MSA and English suggest nothing
SUGGESTED_FROM_DETECTED: dict[Dialect, SpokenDialect] = {
    Dialect.EGYPTIAN: SpokenDialect.EGYPTIAN,
    Dialect.SAUDI: SpokenDialect.SAUDI,
    Dialect.MOROCCAN: SpokenDialect.MOROCCAN,
    Dialect.SUDANESE: SpokenDialect.SUDANESE,
    Dialect.IRAQI: SpokenDialect.IRAQI,
    Dialect.LEBANESE: SpokenDialect.LEBANESE,
    Dialect.SYRIAN: SpokenDialect.SYRIAN,
    Dialect.LIBYAN: SpokenDialect.LIBYAN,
    Dialect.PALESTINIAN: SpokenDialect.PALESTINIAN,
    Dialect.TUNISIAN: SpokenDialect.TUNISIAN,
}


class VoiceGender(StrEnum):
    FEMALE = "female"
    MALE = "male"
