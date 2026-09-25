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
